# RESULT: Looks like tripData.csv and tripData_2.csv are identical. tripData_1.csv looks to be half the data.

import pandas as pd

folder = '/nfs/samba/ProjectWork/Atlanta PECAS 107080x0/2026 Project/Assignment_Simplified'

for f in ['tripData.csv', 'tripData_1.csv', 'tripData_2.csv']:
    path = folder + '/' + f
    df = pd.read_csv(path)
    print(f"--- {f} ---")
    print(f"  Rows: {len(df)}")
    print(f"  inbound value counts:\n{df['inbound'].value_counts().sort_index()}")
    print(f"  depart_period value counts:\n{df['depart_period'].value_counts().sort_index()}")
    print()
    
