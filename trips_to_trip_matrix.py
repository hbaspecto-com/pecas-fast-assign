
import os
import pandas as pd
from aequilibrae.matrix import AequilibraeMatrix

from config import load_settings

# --- Configuration ---
settings = load_settings()
folder = settings['paths']['folder']
input_path = os.path.join(folder, settings['paths']['input_file'])
trip_list_path = os.path.join(folder, settings['paths']['trip_list_file'])

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
print("Creating AequilibraE matrix...")
mat = AequilibraeMatrix()
mat.create_from_trip_list(
    path_to_file=trip_list_path,
    from_column='orig_taz',
    to_column='dest_taz',
    list_cores=['trips'],
)

# AequilibraE saves the .aem alongside the trip list CSV with the same stem
aem_path = os.path.splitext(trip_list_path)[0] + '.aem'
print(f"  Matrix written to: {aem_path}")

# --- Step 3: Load and summarise ---
mat2 = AequilibraeMatrix()
mat2.load(aem_path)
mat2.computational_view(['trips'])
print(f"  Zones: {mat2.zones}")
print(f"  Total demand: {mat2.matrix['trips'].sum():,.0f}")
mat2.close()

print("Done.")