"""Compare the legacy assignment's VC_1 (AM_Link in OUTPUTS.GDB) against the
AequilibraE result's VOC_AB, link by link.

AM_Link rows are one travel direction each (A -> B), and build_aequilibrae_network.py
copies A/B straight into a_node/b_node, so rows are matched on (A, B) via the
project's links table rather than on link_id (which is renumbered after any
bad-capacity links are dropped).

Writes <results_name>_vs_VC_1_report.txt and <results_name>_vs_VC_1.png next to
the results CSV.

Usage: python scripts/compare_vc.py [results_name]   (default: am3_auto)
"""
import os
import sqlite3
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, LogNorm
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import load_settings

# Chart tokens (light mode)
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BLUE_RAMP = ["#cde2fb", "#86b6ef", "#3987e5", "#256abf", "#184f95", "#0d366b"]
REF_LINE = "#52514e"
FIT_LINE = "#eb6834"


def load_joined(folder, project_path, results_name, gdb, link_layer,
                gdb_columns=("FACTYPE", "AMCAPACITY", "VC_1"), result_columns=("trips_ab", "VOC_AB")):
    gdb_df = gpd.read_file(
        os.path.join(folder, gdb), layer=link_layer,
        columns=["A", "B", *gdb_columns], ignore_geometry=True,
    )
    gdb_df = gdb_df.rename(columns={"A": "a_node", "B": "b_node"})
    dup = gdb_df.duplicated(["a_node", "b_node"], keep=False)
    if dup.any():
        print(f"Warning: dropping {dup.sum()} AM_Link rows with duplicate (A, B).")
        gdb_df = gdb_df[~dup]

    with sqlite3.connect(os.path.join(project_path, "project_database.sqlite")) as con:
        links = pd.read_sql("SELECT link_id, a_node, b_node FROM links", con)

    res = pd.read_csv(os.path.join(project_path, f"{results_name}_links.csv"),
                      usecols=["link_id", *result_columns])

    df = links.merge(res, on="link_id", how="inner").merge(gdb_df, on=["a_node", "b_node"], how="inner")
    return df, len(gdb_df), len(links), len(res)


def stats(x, y, old_name="old_VC_1", new_name="new_VOC_AB", over_one=True):
    n = len(x)
    pearson = np.corrcoef(x, y)[0, 1]
    spearman = np.corrcoef(pd.Series(x).rank(), pd.Series(y).rank())[0, 1]
    slope, intercept = np.polyfit(x, y, 1)
    diff = y - x
    s = {
        "n": n,
        "pearson_r": pearson,
        "r_squared": pearson ** 2,
        "spearman_rho": spearman,
        "ols_slope (new ~ old)": slope,
        "ols_intercept": intercept,
        f"total_{old_name}": x.sum(),
        f"total_{new_name}": y.sum(),
        "ratio_total (new/old)": y.sum() / x.sum(),
        f"mean_{old_name}": x.mean(),
        f"mean_{new_name}": y.mean(),
        f"median_{old_name}": np.median(x),
        f"median_{new_name}": np.median(y),
        "mean_diff (new-old)": diff.mean(),
        "mean_abs_diff": np.abs(diff).mean(),
        "rmse": np.sqrt((diff ** 2).mean()),
        "%rmse (rmse/mean_old)": 100 * np.sqrt((diff ** 2).mean()) / x.mean(),
    }
    if over_one:
        # Totals of a ratio are meaningless; share over capacity is the useful V/C summary
        for k in [f"total_{old_name}", f"total_{new_name}", "ratio_total (new/old)", "%rmse (rmse/mean_old)"]:
            del s[k]
        s["share_old_vc>1"] = (x > 1).mean()
        s["share_new_vc>1"] = (y > 1).mean()
    return s


def fmt_stats(title, s):
    lines = [title, "-" * len(title)]
    for k, v in s.items():
        if k == "n" or k.startswith("total_"):
            lines.append(f"  {k:<28} {v:>14,.0f}")
        else:
            lines.append(f"  {k:<28} {v:>14.4f}")
    return "\n".join(lines)


def _style(ax):
    ax.set_facecolor(SURFACE)
    ax.grid(color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#c3c2b7")


def hexbin_panel(ax, x, y, s, xlabel, ylabel, subtitle, gridsize=90, decimals=1):
    """Old-vs-new density scatter with a 1:1 line and OLS fit; axes clipped at the 99.9th pct."""
    cmap = LinearSegmentedColormap.from_list("blue_seq", BLUE_RAMP)
    step = 10.0 ** -decimals
    lim = float(np.ceil(max(np.quantile(x, 0.999), np.quantile(y, 0.999)) / step) * step)
    _style(ax)
    hb = ax.hexbin(x, y, gridsize=gridsize, extent=(0, lim, 0, lim), cmap=cmap, norm=LogNorm(),
                   mincnt=1, linewidths=0)
    ax.plot([0, lim], [0, lim], color=REF_LINE, lw=1.5, ls="--", label="1:1 line")
    xs = np.array([0, lim])
    slope, icpt = s["ols_slope (new ~ old)"], s["ols_intercept"]
    icpt_txt = f"{abs(icpt):.3f}" if abs(icpt) < 100 else f"{abs(icpt):,.0f}"
    ax.plot(xs, icpt + slope * xs, color=FIT_LINE, lw=2,
            label=f"OLS fit: y = {slope:.3f}x {'-' if icpt < 0 else '+'} {icpt_txt}")
    ax.set_xlim(0, lim)
    ax.set_ylim(0, lim)
    ax.set_aspect("equal")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(subtitle, loc="left", color=INK_2, fontsize=8.5)
    ax.legend(loc="upper left", frameon=False, labelcolor=INK_2)
    return hb


def save_hexbin_figure(panels, title, out_png, count_label):
    """panels: list of dicts with hexbin_panel kwargs (x, y, s, xlabel, ylabel, subtitle, ...)."""
    plt.rcParams.update({"font.size": 10, "text.color": INK, "axes.labelcolor": INK_2,
                         "xtick.color": MUTED, "ytick.color": MUTED})
    fig, axes = plt.subplots(1, len(panels), figsize=(7.5 * len(panels), 7), facecolor=SURFACE, squeeze=False)
    for ax, p in zip(axes[0], panels):
        hb = hexbin_panel(ax, **p)
        cb = fig.colorbar(hb, ax=ax, fraction=0.04, pad=0.02)
        cb.set_label(count_label, color=INK_2)
        cb.outline.set_visible(False)
    fig.suptitle(title, x=0.02, ha="left", color=INK, fontsize=12)
    fig.tight_layout()
    fig.savefig(out_png, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def plot(x, y, s, out_png, results_name):
    save_hexbin_figure(
        [dict(x=x, y=y, s=s,
              xlabel="Old VC_1 (legacy AM assignment)",
              ylabel=f"New VOC_AB ({results_name})",
              subtitle=f"n = {s['n']:,} non-connector links   Pearson r = {s['pearson_r']:.3f}   "
                       f"Spearman ρ = {s['spearman_rho']:.3f}   (axes clipped at 99.9th pct)")],
        f"Link V/C: old VC_1 vs new {results_name} VOC_AB", out_png, "Links per hex (log scale)",
    )


def main():
    results_name = sys.argv[1] if len(sys.argv) > 1 else "am3_auto"
    settings = load_settings()
    folder = settings["paths"]["folder"]
    net = settings["aequilibrae_network"]
    project_path = os.path.join(folder, net["project_path"])

    df, n_gdb, n_links, n_res = load_joined(folder, project_path, results_name, net["gdb"], net["link_layer"])
    df = df.dropna(subset=["VC_1", "VOC_AB"])
    connector = df["FACTYPE"] == 0
    core = df[~connector]

    report = [
        f"Old VC_1 (OUTPUTS.GDB/{net['link_layer']}) vs new VOC_AB ({results_name}_links.csv)",
        "",
        f"AM_Link rows: {n_gdb:,}   project links: {n_links:,}   result rows: {n_res:,}   "
        f"matched on (A,B): {len(df):,}",
        "",
        fmt_stats("Non-connector links (FACTYPE != 0)", stats(core["VC_1"].to_numpy(), core["VOC_AB"].to_numpy())),
        "",
        fmt_stats("All matched links (incl. connectors)", stats(df["VC_1"].to_numpy(), df["VOC_AB"].to_numpy())),
        "",
        "Non-connector links by FACTYPE",
        "------------------------------",
        f"  {'FACTYPE':>7} {'n':>8} {'pearson':>8} {'spearman':>9} {'mean_old':>9} {'mean_new':>9}",
    ]
    for ft, g in core.groupby("FACTYPE"):
        if len(g) < 3:
            continue
        s = stats(g["VC_1"].to_numpy(), g["VOC_AB"].to_numpy())
        report.append(f"  {int(ft):>7} {s['n']:>8,} {s['pearson_r']:>8.3f} {s['spearman_rho']:>9.3f} "
                      f"{s['mean_old_VC_1']:>9.3f} {s['mean_new_VOC_AB']:>9.3f}")
    text = "\n".join(report)
    print(text)

    out_txt = os.path.join(project_path, f"{results_name}_vs_VC_1_report.txt")
    out_png = os.path.join(project_path, f"{results_name}_vs_VC_1.png")
    with open(out_txt, "w") as f:
        f.write(text + "\n")
    plot(core["VC_1"].to_numpy(), core["VOC_AB"].to_numpy(),
         stats(core["VC_1"].to_numpy(), core["VOC_AB"].to_numpy()), out_png, results_name)
    print(f"\nWrote {out_txt}\nWrote {out_png}")


if __name__ == "__main__":
    main()
