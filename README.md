# pecas-fast-assign

Simplified traffic assignment using PECAS land use for alternate scenarios and intermediate years.

## Setup

```
make install
```

This creates a `venv/` and installs dependencies from `requirements.txt`. On macOS, `aequilibrae` has no prebuilt wheel on PyPI, so pip builds its C++ extension from source; `make install` handles the required OpenMP-capable compiler env vars automatically via `scripts/native_build_env.py` (see `settings.yaml` for the Homebrew packages it expects: `llvm` and `libomp`).

## Configuration

Runtime settings (input paths, AM peak period definitions, car modes, macOS build packages) live in `settings.yaml`. Point `PECAS_SETTINGS_PATH` at an alternate file to override the default (e.g. for test/scratch runs against a different data folder).

## Scripts

- `trips_to_trip_matrix.py` — filters PECAS trip data down to AM peak car trips and builds an AequilibraE trip matrix (`.aem`). Pass `--from-trip-list` to skip the filter step and reuse an existing trip list CSV.
- `diagnostic_trip_data.py` — inspects trip data to check whether rows represent person-trips or vehicle-trips, and lists trip mode values.
- `compare_trip_data_files.py` — compares candidate trip data files for duplicates/differences.

## AequilibraE reference docs

We use the `aequilibrae` package via pip; this is unrelated to that runtime dependency. For local reference to the API docs, `vendor/aequilibrae` is a shallow git submodule pointing at our fork ([hbaspecto-com/aequilibrae](https://github.com/hbaspecto-com/aequilibrae)), sparse-checked-out to just the `docs/` folder. After cloning, run:

```
make aequilibrae-docs
```

(Plain `git submodule update --init` also works, but pulls the full aequilibrae source tree instead of just `docs/`, since sparse-checkout config isn't stored in `.gitmodules`.)
