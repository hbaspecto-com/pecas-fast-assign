import os
import sys
import time

from aequilibrae.project import Project
from aequilibrae.matrix import AequilibraeMatrix
from aequilibrae.paths import TrafficClass, TrafficAssignment

from config import load_settings

def main():
    settings = load_settings()
    folder = settings["paths"]["folder"]
    project_path = os.path.join(folder, settings["aequilibrae_network"]["project_path"])
    matrix_stem = os.path.splitext(os.path.basename(settings["paths"]["trip_list_file"]))[0]  # e.g. "tripData_am_cars"

    # Assignment controls
    vdf_name = "BPR"
    vdf_params = {"alpha": 0.15, "beta": 4.0}
    max_iter = int(os.getenv("ASSIGN_MAX_ITERS", "200"))
    target_rgap = float(os.getenv("ASSIGN_TARGET_RGAP", "1e-4"))

    print(f"Opening project: {project_path}")
    prj = Project()
    prj.open(project_path)

    # Get demand matrix by name registered in the project
    if not prj.matrices.check_exists(matrix_stem):
        print(f"Error: matrix '{matrix_stem}' not found in project. Run trips_to_trip_matrix.py first.", file=sys.stderr)
        sys.exit(1)
    aem_path = os.path.join(prj.matrices.fldr, prj.matrices.get_record(matrix_stem).file_name)
    mat = AequilibraeMatrix()
    mat.load(aem_path)
    mat.computational_view(["trips"])

    # Use the default car mode and its link fields for time/capacity
    modes = prj.network.modes()
    car_mode = modes.get("c") or next(iter(modes.values()))  # fallback to first if 'c' not present
    graph = prj.network.graphs[car_mode]
    # Confirm graph has the necessary fields (free-flow time and capacity must be present)
    # If your project uses different field names, set them here:
    graph.set_graph("free_flow_time", "capacity", "link_id")

    # Build class and assignment
    tc = TrafficClass(graph, mat)

    ta = TrafficAssignment()
    ta.set_classes([tc])
    ta.set_vdf(vdf_name)
    ta.set_vdf_parameters(vdf_params)
    ta.set_capacity_field("capacity")
    ta.set_time_field("free_flow_time")
    ta.set_algorithm("fw")  # Frank-Wolfe
    ta.max_iter = max_iter
    ta.rgap_target = target_rgap
    ta.store_skims = False  # set True if you want OD skims
    ta.report = True

    print(f"Starting assignment: VDF={vdf_name} {vdf_params}, max_iter={max_iter}, rgap_target={target_rgap}")
    t0 = time.time()
    ta.execute()

    # Console summary and iteration-by-iteration log (AequilibraE prints per-iter when report=True)
    print(f"Done in {time.time() - t0:.1f}s")
    print(f"Final gap: {getattr(ta, 'rgap', None)}")

    # Save final link results to project as 'am_auto' result set
    results_name = os.getenv("ASSIGN_RESULTS_NAME", "am_auto")
    prj.results.save_assignment(ta, results_name)
    print(f"Saved assignment results as: {results_name}")

    # Optionally write a CSV of link flows/times
    if os.getenv("ASSIGN_WRITE_CSV", "1") == "1":
        out_csv = os.path.join(project_path, f"{results_name}_links.csv")
        prj.results.export_link_results(results_name, out_csv)
        print(f"Wrote link results CSV: {out_csv}")

    mat.close()
    prj.close()

if __name__ == "__main__":
    main()
