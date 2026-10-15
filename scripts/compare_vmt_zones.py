"""Compare the legacy AM assignment (AM_Link in OUTPUTS.GDB) against an AequilibraE
result on two more measures:

  1. VMT per link: volume * DISTANCE (miles)
  2. Trips departing / arriving each zone, from centroid-connector volumes

Old volume. On every non-connector link VC_1 * AMCAPACITY == V_TOTAM * k with
k = 1/3.66 (V_TOTAM is the period total; dividing by 3.66 puts it on the hourly
basis VC_1 uses). Connectors have AMCAPACITY = VC_1 = 0, so their volume is
taken as V_TOTAM * k, with k measured from the non-connector links. V_TOTAM
includes commercial vehicles and trucks, which the new run does not, so every
comparison is also reported against an autos-only old volume,
(V_SOVAM + V_HOVAM) * k.

New volume is trips_ab from <results_name>_links.csv (same basis as VOC_AB).

Zone totals use connector volumes for both runs: departures are flows on
connectors leaving a centroid (a_node is a centroid), arrivals are flows on
connectors entering one. Intrazonal trips never load onto the network, so the
new demand matrix's row/column sums are reported alongside for reference.

Writes <results_name>_vs_old_vmt_report.txt / .png and
<results_name>_vs_old_zone_trips_report.txt / .png next to the results CSV.

Usage: python scripts/compare_vmt_zones.py [results_name]   (default: am3_auto)
"""
import os
import sqlite3
import sys
from pathlib import Path

import numpy as np
import openmatrix as omx
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from compare_vc import load_joined, stats, fmt_stats, save_hexbin_figure
from config import load_settings

GDB_COLUMNS = ("FACTYPE", "DISTANCE", "AMCAPACITY", "VC_1", "V_TOTAM", "V_SOVAM", "V_HOVAM")


def old_volumes(df):
    """Add old_vol (all vehicles) and old_auto (SOV + HOV) on the VC_1 * capacity basis."""
    connector = df["FACTYPE"] == 0
    nc = df[~connector & (df["V_TOTAM"] > 0) & (df["VC_1"] > 0)]
    k = float(np.median(nc["VC_1"] * nc["AMCAPACITY"] / nc["V_TOTAM"]))
    df["old_vol"] = np.where(connector, df["V_TOTAM"].fillna(0) * k,
                             (df["VC_1"] * df["AMCAPACITY"]).fillna(0))
    df["old_auto"] = (df["V_SOVAM"].fillna(0) + df["V_HOVAM"].fillna(0)) * k
    df["new_vol"] = df["trips_ab"].fillna(0)
    return k


def vmt_report(df, results_name, k):
    df = df.copy()
    df["old_vmt"] = df["old_vol"] * df["DISTANCE"]
    df["old_auto_vmt"] = df["old_auto"] * df["DISTANCE"]
    df["new_vmt"] = df["new_vol"] * df["DISTANCE"]
    core = df[df["FACTYPE"] != 0]

    def st(g, old_col):
        return stats(g[old_col].to_numpy(), g["new_vmt"].to_numpy(),
                     old_name="old_vmt", new_name="new_vmt", over_one=False)

    lines = [
        f"Link VMT (volume * DISTANCE miles): old AM_Link vs new {results_name}",
        "",
        f"Old volume = VC_1 * AMCAPACITY (connectors: V_TOTAM * k), k = {k:.5f} (1/{1 / k:.3f})",
        f"Old autos-only volume = (V_SOVAM + V_HOVAM) * k",
        "New volume = trips_ab",
        "",
        fmt_stats("Non-connector links, old = all vehicles", st(core, "old_vmt")),
        "",
        fmt_stats("Non-connector links, old = autos only (SOV + HOV)", st(core, "old_auto_vmt")),
        "",
        fmt_stats("All links incl. connectors, old = all vehicles", st(df, "old_vmt")),
        "",
        "VMT totals by FACTYPE",
        "---------------------",
        f"  {'FACTYPE':>7} {'n':>8} {'old_all':>12} {'old_auto':>12} {'new':>12} "
        f"{'new/all':>8} {'new/auto':>9} {'pearson':>8}",
    ]
    for ft, g in df.groupby("FACTYPE"):
        o, a, n = g["old_vmt"].sum(), g["old_auto_vmt"].sum(), g["new_vmt"].sum()
        r = np.corrcoef(g["old_vmt"], g["new_vmt"])[0, 1] if len(g) > 2 and g["old_vmt"].std() > 0 else np.nan
        lines.append(f"  {int(ft):>7} {len(g):>8,} {o:>12,.0f} {a:>12,.0f} {n:>12,.0f} "
                     f"{n / o if o else np.nan:>8.3f} {n / a if a else np.nan:>9.3f} {r:>8.3f}")
    o, a, n = df["old_vmt"].sum(), df["old_auto_vmt"].sum(), df["new_vmt"].sum()
    lines.append(f"  {'all':>7} {len(df):>8,} {o:>12,.0f} {a:>12,.0f} {n:>12,.0f} {n / o:>8.3f} {n / a:>9.3f}")

    panels = []
    for old_col, label in [("old_vmt", "all vehicles"), ("old_auto_vmt", "autos only")]:
        s = st(core, old_col)
        panels.append(dict(
            x=core[old_col].to_numpy(), y=core["new_vmt"].to_numpy(), s=s,
            xlabel=f"Old VMT, {label} (veh-mi)", ylabel=f"New VMT, {results_name} (veh-mi)",
            subtitle=f"Old = {label}   n = {s['n']:,} non-connector links   r = {s['pearson_r']:.3f}   "
                     f"ρ = {s['spearman_rho']:.3f}   new/old total = {s['ratio_total (new/old)']:.3f}",
            decimals=0,
        ))
    return "\n".join(lines), panels


def zone_totals(df, centroids):
    dep = df[df["a_node"].isin(centroids)].groupby("a_node")[["old_vol", "old_auto", "new_vol"]].sum()
    arr = df[df["b_node"].isin(centroids)].groupby("b_node")[["old_vol", "old_auto", "new_vol"]].sum()
    idx = pd.Index(sorted(centroids), name="zone")
    return dep.reindex(idx, fill_value=0.0), arr.reindex(idx, fill_value=0.0)


def matrix_totals(omx_path):
    f = omx.open_file(omx_path, "r")
    try:
        m = np.array(f["trips"])
        mapping = f.mapping(f.list_mappings()[0])  # zone id -> matrix offset
        zones = np.array(sorted(mapping, key=mapping.get), dtype=int)
    finally:
        f.close()
    # Intrazonal trips never reach a connector, so drop the diagonal from both sums
    diag = np.diag(m)
    return (pd.Series(m.sum(axis=1) - diag, index=zones), pd.Series(m.sum(axis=0) - diag, index=zones),
            float(diag.sum()), float(m.sum()))


def zone_report(df, centroids, omx_path, results_name):
    dep, arr = zone_totals(df, centroids)
    row_sum, col_sum, intrazonal, mat_total = matrix_totals(omx_path)

    def st(g, old_col):
        return stats(g[old_col].to_numpy(), g["new_vol"].to_numpy(),
                     old_name="old_trips", new_name="new_trips", over_one=False)

    lines = [
        f"Trips departing / arriving each zone (centroid-connector volumes): old AM_Link vs new {results_name}",
        "",
        f"Zones (network centroids): {len(centroids):,}",
        "Old = connector V_TOTAM * k (all vehicles) or (V_SOVAM + V_HOVAM) * k (autos only)",
        "New = connector trips_ab",
        "",
    ]
    for name, g in [("Departures", dep), ("Arrivals", arr)]:
        lines += [fmt_stats(f"{name}, old = all vehicles", st(g, "old_vol")), "",
                  fmt_stats(f"{name}, old = autos only (SOV + HOV)", st(g, "old_auto")), ""]
    lines += [
        f"New demand matrix ({os.path.basename(omx_path)}) for reference",
        "-" * 40,
        f"  matrix total                 {mat_total:>14,.0f}",
        f"  intrazonal (not assigned)    {intrazonal:>14,.0f}",
        f"  connector departures total   {dep['new_vol'].sum():>14,.0f}",
        f"  connector arrivals total     {arr['new_vol'].sum():>14,.0f}",
        f"  r(row sums excl. intrazonal, connector departures)   "
        f"{np.corrcoef(row_sum.reindex(dep.index, fill_value=0), dep['new_vol'])[0, 1]:.4f}",
        f"  r(col sums excl. intrazonal, connector arrivals)     "
        f"{np.corrcoef(col_sum.reindex(arr.index, fill_value=0), arr['new_vol'])[0, 1]:.4f}",
    ]

    panels = []
    for name, g in [("departing", dep), ("arriving", arr)]:
        s = st(g, "old_auto")
        panels.append(dict(
            x=g["old_auto"].to_numpy(), y=g["new_vol"].to_numpy(), s=s,
            xlabel=f"Old trips {name}, autos only (veh/hr)",
            ylabel=f"New trips {name}, {results_name} (veh/hr)",
            subtitle=f"Trips {name}   n = {s['n']:,} zones   r = {s['pearson_r']:.3f}   "
                     f"ρ = {s['spearman_rho']:.3f}   new/old total = {s['ratio_total (new/old)']:.3f}",
            gridsize=60, decimals=-2,
        ))
    out = pd.concat({"depart": dep, "arrive": arr}, axis=1)
    out.columns = [f"{a}_{b}" for a, b in out.columns]
    return "\n".join(lines), panels, out


def main():
    results_name = sys.argv[1] if len(sys.argv) > 1 else "am3_auto"
    settings = load_settings()
    folder = settings["paths"]["folder"]
    net = settings["aequilibrae_network"]
    project_path = os.path.join(folder, net["project_path"])
    omx_path = os.path.splitext(os.path.join(folder, settings["paths"]["trip_list_file"]))[0] + ".omx"

    df, n_gdb, n_links, n_res = load_joined(folder, project_path, results_name, net["gdb"], net["link_layer"],
                                            gdb_columns=GDB_COLUMNS, result_columns=("trips_ab",))
    print(f"AM_Link rows: {n_gdb:,}   project links: {n_links:,}   result rows: {n_res:,}   "
          f"matched on (A,B): {len(df):,}\n")
    k = old_volumes(df)

    with sqlite3.connect(os.path.join(project_path, "project_database.sqlite")) as con:
        centroids = {r[0] for r in con.execute("SELECT node_id FROM nodes WHERE is_centroid = 1")}

    vmt_text, vmt_panels = vmt_report(df, results_name, k)
    zone_text, zone_panels, zone_df = zone_report(df, centroids, omx_path, results_name)
    print(vmt_text + "\n\n" + zone_text)

    stem = os.path.join(project_path, f"{results_name}_vs_old")
    with open(f"{stem}_vmt_report.txt", "w") as f:
        f.write(vmt_text + "\n")
    with open(f"{stem}_zone_trips_report.txt", "w") as f:
        f.write(zone_text + "\n")
    zone_df.to_csv(f"{stem}_zone_trips.csv")
    save_hexbin_figure(vmt_panels, f"Link VMT: old AM assignment vs new {results_name}",
                       f"{stem}_vmt.png", "Links per hex (log scale)")
    save_hexbin_figure(zone_panels, f"Zone trips from connector volumes: old AM assignment (autos) vs new {results_name}",
                       f"{stem}_zone_trips.png", "Zones per hex (log scale)")
    print(f"\nWrote {stem}_vmt_report.txt, {stem}_vmt.png,\n      {stem}_zone_trips_report.txt, "
          f"{stem}_zone_trips.csv, {stem}_zone_trips.png")


if __name__ == "__main__":
    main()
