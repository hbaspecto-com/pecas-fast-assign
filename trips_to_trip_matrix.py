
import os
import shutil
import numpy as np
import pandas as pd
from aequilibrae.matrix import AequilibraeMatrix
from aequilibrae.project import Project

from config import load_settings

# --- Configuration ---
settings = load_settings()
folder = settings['paths']['folder']
input_path = os.path.join(folder, settings['paths']['input_file'])
trip_list_path = os.path.join(folder, settings['paths']['trip_list_file'])
project_path = os.path.join(folder, settings['aequilibrae_network']['project_path'])

# Period numbering: period 1 = 3:00am, each period = 30 min
# 7:00am = period 9, 7:30am = period 10 (covers 7:00-8:00am)
AM_PEAK_PERIODS = settings['trip_filter']['am_peak_periods']

CAR_MODES = set(settings['trip_filter']['car_modes'])

# --- Step 1: Filter trip data and write trip list CSV ---
# Skip this step by passing --from-trip-list on the command line
# e.g.: python trips_to_trip_matrix.py --from-trip-list
import sys
skip_to_trip_list = '--from-trip-list' in sys.argv

if skip_to_trip_list:
    print(f"Skipping CSV filter step, using existing trip list: {trip_list_path}")
else:
    print("Loading trip data...")
    df = pd.read_csv(input_path)
    print(f"  Total rows: {len(df):,}")

    df_filtered = df[
        df['depart_period'].isin(AM_PEAK_PERIODS) &
        df['trip_mode_name'].isin(CAR_MODES)
    ].copy()
    print(f"  AM peak car trips: {len(df_filtered):,}")

    df_filtered['trips'] = 1
    df_filtered[['orig_taz', 'dest_taz', 'trips']].to_csv(trip_list_path, index=False)
    print(f"  Trip list written to: {trip_list_path}")

# --- Step 2: Create AequilibraE matrix from trip list ---
# Built directly against the network's full centroid set rather than via
# create_from_trip_list(), for two reasons:
#  1. create_from_trip_list() never writes the actual TAZ numbers into the
#     matrix's zone index - it's left at all zeros (AequilibraE bug/gap,
#     confirmed against the installed version).
#  2. TrafficClass requires the matrix's zone index to be *exactly* equal
#     (np.array_equal) to the graph's centroid list. Some centroids have no
#     AM-peak car trips at all, so deriving the zone list purely from the
#     trip list's unique TAZs would omit them; those zones must still be
#     present in the matrix as empty rows/columns.
print("Creating AequilibraE matrix...")
trip_df = pd.read_csv(trip_list_path)

centroid_project = Project()
centroid_project.open(project_path)
with centroid_project.db_connection as conn:
    zones_list = [row[0] for row in conn.execute(
        "select node_id from nodes where is_centroid=1 order by node_id;"
    ).fetchall()]
centroid_project.close()

missing = (set(trip_df['orig_taz']) | set(trip_df['dest_taz'])) - set(zones_list)
if missing:
    raise SystemExit(
        f"Trip list references {len(missing):,} TAZ(s) that are not centroids "
        f"in the network, e.g. {sorted(missing)[:20]}"
    )

zone_index = {zone: i for i, zone in enumerate(zones_list)}
nb_zones = len(zones_list)
full = np.zeros((nb_zones, nb_zones), dtype=np.float64)
for (orig, dest), trips in trip_df.groupby(['orig_taz', 'dest_taz'])['trips'].sum().items():
    full[zone_index[orig], zone_index[dest]] += trips

# AequilibraE saves the .aem alongside the trip list CSV with the same stem
aem_path = os.path.splitext(trip_list_path)[0] + '.aem'
mat = AequilibraeMatrix()
mat.create_empty(file_name=aem_path, zones=nb_zones, matrix_names=['trips'], memory_only=False)
mat.indices[:, 0] = np.array(zones_list)
mat.set_index(mat.index_names[0])
mat.matrix['trips'][:, :] = full
mat.save()
mat.close()
print(f"  Matrix written to: {aem_path}")
print(f"  Zone index set to {nb_zones:,} network centroid ids (range {zones_list[0]}-{zones_list[-1]})")

# --- Step 3: Load and summarise ---
mat2 = AequilibraeMatrix()
mat2.load(aem_path)
mat2.computational_view(['trips'])
print(f"  Zones: {mat2.zones}")
print(f"  Total demand: {mat2.matrix['trips'].sum():,.0f}")
mat2.close()

# --- Step 4: Register the matrix in the AequilibraE network project ---
# so it shows up alongside the nodes/links built by build_aequilibrae_network.py
# (see that script's project_path setting) instead of living only as a
# standalone .aem next to the trip list CSV.
print("Registering matrix in the AequilibraE network project...")
project = Project()
project.open(project_path)

matrix_name = os.path.splitext(os.path.basename(trip_list_path))[0]
project_aem_name = os.path.basename(aem_path)

if project.matrices.check_exists(matrix_name):
    # delete_record() unlinks the file at this path too, so it must run
    # before we copy the new matrix in - otherwise it deletes the copy we
    # just made instead of the stale one. It also leaves a stale record
    # object in the in-memory registry, which would make new_record() below
    # falsely detect a file_name collision with the record just deleted, so
    # reload the registry from the (now updated) database afterwards.
    project.matrices.delete_record(matrix_name)
    project.matrices.reload()
shutil.copy2(aem_path, os.path.join(project.matrices.fldr, project_aem_name))
project.matrices.new_record(matrix_name, project_aem_name)
project.close()
print(f"  Matrix '{matrix_name}' registered in project: {project_path}")

print("Done.")