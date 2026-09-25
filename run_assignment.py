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
    results_name = os.getenv("ASSIGN_RESULTS_NAME", "am_auto")
    write_csv = os.getenv("ASSIGN_WRITE_CSV", "1") == "1"

    # Field mapping from your network
    time_field = os.getenv("ASSIGN_TIME_FIELD", "TIME1")          # free-flow time
    alt_time_field = os.getenv("ASSIGN_ALT_TIME_FIELD", "TIME_1") # if needed for diagnostics
    capacity_field = os.getenv("ASSIGN_CAPACITY_FIELD", "AMCAPACITY")
    vc_field = os.getenv("ASSIGN_VC_FIELD", "VC_1")               # V/C that we’ll multiply by AMCAPACITY for preload
    link_id_field = os.getenv("ASSIGN_LINK_ID_FIELD", "link_id")  # internal unique ID if available

    print(f"Opening project: {project_path}")
    prj = Project()
    prj.open(project_path)

    # Demand matrix
    if not prj.matrices.check_exists(matrix_stem):
        print(f"Error: matrix '{matrix_stem}' not found in project. Run trips_to_trip_matrix.py first.", file=sys.stderr)
        sys.exit(1)
    aem_path = os.path.join(prj.matrices.fldr, prj.matrices.get_record(matrix_stem).file_name)
    mat = AequilibraeMatrix()
    mat.load(aem_path)
    mat.computational_view(["trips"])

    # Mode/graph
    modes = prj.network.modes()
    car_mode = modes.get("c") or next(iter(modes.values()))
    graph = prj.network.graphs[car_mode]

    # Ensure fields exist and wire graph attributes
    for f in [time_field, capacity_field]:
        if f not in graph.network.graph.columns:
            print(f"Error: field '{f}' not found in network links.", file=sys.stderr)
            sys.exit(1)

    # If link_id_field missing, fallback to the network’s default ID column
    if link_id_field not in graph.network.graph.columns:
        # Heuristic fallback commonly present in AequilibraE graphs
        link_id_field = "link_id" if "link_id" in graph.network.graph.columns else graph.network.graph.columns[0]

    # Set graph: time, capacity, link_id
    graph.set_graph(time_field, capacity_field, link_id_field)

    # Optional preload: VC_1 * AMCAPACITY -> initial flows
    gdf = graph.network.graph  # pandas DataFrame used by AequilibraE under the hood
    preload = None
    if vc_field in gdf.columns and capacity_field in gdf.columns:
        preload = (gdf[vc_field].fillna(0.0) * gdf[capacity_field].fillna(0.0)).to_numpy()
        # Replace negatives/NaNs safely
        preload[~(preload >= 0)] = 0.0
        print("Using preload flows from VC_1 * AMCAPACITY")
    else:
        print("Preload not applied (VC_1 or AMCAPACITY missing).")

    # Build class and assignment
    tc = TrafficClass(graph, mat)
    if preload is not None:
        # If TrafficClass/Assignment supports initial flows on links:
        try:
            tc.set_initial_flows(preload)  # some versions support this
            print("Applied initial flows to traffic class.")
        except Exception:
            # If not available, we proceed without explicit preload
            print("Initial flow seeding not supported in this AequilibraE version; continuing without.")

    ta = TrafficAssignment()
    ta.set_classes([tc])
    ta.set_vdf(vdf_name)
    ta.set_vdf_parameters(vdf_params)
    ta.set_capacity_field(capacity_field)
    ta.set_time_field(time_field)

    # “Fancier” Frank–Wolfe: use FW with line search (AequilibraE’s default FW does line search).
    # If your build exposes variants, you can set algorithm detail; otherwise "fw" selects FW+line search.
    ta.set_algorithm("fw")  # Frank–Wolfe with line search
    ta.max_iter = max_iter
    ta.rgap_target = target_rgap
    ta.store_skims = False
    ta.report = True  # prints per-iteration progress to console

    print(f"Starting assignment: VDF={vdf_name} {vdf_params}, "
          f"time_field={time_field}, capacity_field={capacity_field}, "
          f"max_iter={max_iter}, rgap_target={target_rgap}")
    t0 = time.time()
    ta.execute()
    print(f"Done in {time.time() - t0:.1f}s")
    print(f"Final gap: {getattr(ta, 'rgap', None)}")

    # Save results
    prj.results.save_assignment(ta, results_name)
    print(f"Saved assignment results as: {results_name}")

    if write_csv:
        out_csv = os.path.join(project_path, f"{results_name}_links.csv")
        prj.results.export_link_results(results_name, out_csv)
        print(f"Wrote link results CSV: {out_csv}")

    # Diagnostics if convergence seems off
    if getattr(ta, "rgap", 1.0) > max(target_rgap * 5, 1e-3):
        print("Note: High final gap. Consider verifying AMCAPACITY, TIME1 units/values, and connector logic.")
        if alt_time_field in gdf.columns:
            print(f"Alternative time field available: {alt_time_field}. Try ASSIGN_TIME_FIELD={alt_time_field}.")

    mat.close()
    prj.close()

if __name__ == "__main__":
    main()
