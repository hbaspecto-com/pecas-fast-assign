# pecas-fast-assign

Simplified traffic assignment using PECAS land use for alternate scenarios and intermediate years.

## Setup

```
make install
```

This creates a `venv/` and installs dependencies from `requirements.txt`. On macOS, `aequilibrae` has no prebuilt wheel on PyPI, so pip builds its C++ extension from source; `make install` handles the required OpenMP-capable compiler env vars automatically via `scripts/native_build_env.py` (see `settings.yaml` for the Homebrew packages it expects: `llvm` and `libomp`).

`make venv` uses whatever `python3` is first on `PATH`. `build_aequilibrae_network.py` needs that Python's `sqlite3` module built with loadable-extension support (so AequilibraE can load `mod_spatialite`) — the python.org macOS installer ships one that doesn't (`'sqlite3.Connection' object has no attribute 'enable_load_extension'`), while Homebrew's `python@3.13` does. If you hit that error, rebuild the venv against Homebrew's Python instead, e.g.:

```
rm -rf venv

# For linux
make install PYTHON=/usr/bin/python3.13

# For macOS:
# make install PYTHON=/usr/local/opt/python@3.13/bin/python3.13
```

Scripts that only use `AequilibraeMatrix` (like `trips_to_trip_matrix.py`) don't need this — it only matters for building an AequilibraE `Project` (network).

## Configuration

Runtime settings (input paths, AM peak period definitions, car modes, macOS build packages, the AequilibraE network source layers) live in `settings.yaml`. Point `PECAS_SETTINGS_PATH` at an alternate file to override the default (e.g. for test/scratch runs against a different data folder).

The `aequilibrae_network` section controls `build_aequilibrae_network.py`: `gdb`/`link_layer`/`node_layer` locate the source feature layers (relative to `paths.folder`), and `project_path` is where the AequilibraE project gets written (also relative to `paths.folder`).

## Workflow
1) Build the network (nodes/links into an AequilibraE project)
   - From the venv:
     - python build_aequilibrae_network.py --overwrite
   - Output: {paths.folder}/{aequilibrae_network.project_path}/project_database.sqlite

2) Build the AM-peak trips matrix
   - python trips_to_trip_matrix.py
   - Output: trip matrix .aem next to the trip list CSV and registered in the project

3) Run the assignment
   - python run_assignment.py
   - Outputs:
     - Results database table (non-spatial) in results_database.sqlite (managed by AequilibraE)
     - CSV at {project_path}/{ASSIGN_RESULTS_NAME}_links.csv (default am_auto_links.csv)

4) View the base links/nodes in QGIS
   - Data Source Manager (Ctrl+L) > Vector
   - Source Type: File
   - File: {project_path}/project_database.sqlite
   - Add
   - In the layer chooser dialog, pick:
     - links (geometry = LineString, EPSG:4326)
     - nodes (geometry = Point, EPSG:4326)
   - OK

5) View congested results in QGIS (two easy options)

   Option A — Use the CSV (recommended, no DB plugins needed):
   - Data Source Manager (Ctrl+L) > Delimited Text
   - File name: {project_path}/am_auto_links.csv
   - Geometry: None (no geometry)
   - Add
   - Join to links:
     - Right‑click links > Properties > Joins > +
     - Join layer: am_auto_links (the CSV you just added)
     - Join field(s): If the CSV contains link_id, join on link_id.
       If it does not, create a temporary join key in both layers:
       - Links: Field Calculator → ab_key (string) = to_string("a_node") || '_' || to_string("b_node")
       - CSV: Layer styling panel > Open Attribute Table > Field Calculator → ab_key (string) = "a_node" || '_' || "b_node"
       - Join on ab_key.
     - OK
   - Style the links layer using joined fields such as trips_ab, congested_time, VOC, etc.

   Option B — Load the non-spatial results table from a plain SQLite file:
   - Data Source Manager (Ctrl+L) > Vector
   - Source Type: File
   - File: {project_path}/results_database.sqlite
   - Add
   - From the table picker, choose your results table (e.g., am_auto)
   - Then perform the same attribute join to links as in Option A.

Notes
- If the results table doesn’t appear, ensure the assignment finished and printed “Saved assignment results as: <name>”.
- If the CSV lacks link_id, join by a_node/b_node as described above.
- If a layer looks empty, right‑click > Zoom to Layer and verify Project CRS has on‑the‑fly reprojection enabled.

- `trips_to_trip_matrix.py` — filters PECAS trip data down to AM peak car trips and builds an AequilibraE trip matrix (`.aem`). Pass `--from-trip-list` to skip the filter step and reuse an existing trip list CSV.
- `build_aequilibrae_network.py` — builds an AequilibraE project (nodes + links) from the `AM_Link`/`AM_Node` feature layers in the ARC `OUTPUTS.GDB` file geodatabase. Pass `--overwrite` to replace an existing project at the configured `project_path`. See the module docstring for the modeling decisions baked in (centroid detection, direction, units).
- `diagnostic_trip_data.py` — inspects trip data to check whether rows represent person-trips or vehicle-trips, and lists trip mode values.
- `compare_trip_data_files.py` — compares candidate trip data files for duplicates/differences.

## Trip matrix source

The trip demand matrix is built from `tripData.csv` via `trips_to_trip_matrix.py`. The ARC model also produces a Cube Voyager binary matrix (`trips_joint_AM.TPP`) which was considered as an alternative or cross-check source.

Reading a `.TPP` file requires `TPPDLIBX.DLL` and its companion `TPUTLIBC.DLL`, both proprietary Citilabs/Bentley binaries that ship only with a Cube Voyager installation. This project runs on Linux, where those DLLs cannot be used at all. On the Windows machine where the `.TPP` file lives, only `TPPDLIBX.DLL` was available — `TPUTLIBC.DLL` was absent, causing the DLL load to fail. No Cube Voyager licence or install was available to export the matrix to a portable format (OMX or CSV) as an alternative.

Given that `tripData.csv` is already available, is readable with standard Python tools on any platform, and is the authoritative source for the same trips, it is the correct and practical choice. The `.TPP` file is not used.

## AequilibraE reference docs

We use the `aequilibrae` package via pip; this is unrelated to that runtime dependency. For local reference to the API docs, `vendor/aequilibrae` is a shallow git submodule pointing at our fork ([hbaspecto-com/aequilibrae](https://github.com/hbaspecto-com/aequilibrae)), sparse-checked-out to just the `docs/` folder. After cloning, run:

```
make aequilibrae-docs
```

(Plain `git submodule update --init` also works, but pulls the full aequilibrae source tree instead of just `docs/`, since sparse-checkout config isn't stored in `.gitmodules`.)
