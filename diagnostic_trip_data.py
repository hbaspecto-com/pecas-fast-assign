
import pandas as pd

folder = '/nfs/samba/ProjectWork/Atlanta PECAS 107080x0/2026 Project/Assignment_Simplified'
path = folder + '/tripData.csv'

df = pd.read_csv(path)

# --- Check if rows are person-trips or vehicle-trips ---
# For joint trips (num_participants > 1), count rows per (tour_id_uniq, stop_id, inbound)
joint = df[df['num_participants'] > 1]
rows_per_joint_stop = joint.groupby(['tour_id_uniq', 'stop_id', 'inbound']).size()
print("Rows per joint trip stop (if >1, rows are person-trips; if always 1, rows are vehicle-trips):")
print(rows_per_joint_stop.value_counts().sort_index())
print()

# --- All unique trip_mode_name values ---
print("All trip_mode_name values:")
print(df['trip_mode_name'].value_counts().sort_index())