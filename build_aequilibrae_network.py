"""Build an AequilibraE project (nodes + links) from the AM_Node/AM_Link
feature layers in the ARC OUTPUTS.GDB file geodatabase.

A/B (link endpoints) in AM_Link and N (node id) in AM_Node share the same id
space with 100% coverage (verified against the source data), so a_node/b_node
are taken directly from A/B rather than resolved by AequilibraE's usual
geometry-matching triggers. Those triggers are disabled for the bulk insert
(matching millions of link endpoints against node geometry is slow and, for
this data, redundant) and re-enabled afterwards so later edits in QGIS/the
AequilibraE API stay consistent.

FACTYPE == 0 ("Centroid or external connector" per the ABM data dictionary)
identifies centroid connectors and external-station connectors. A node is
flagged as a centroid if every link touching it is one of those connectors -
this also catches external-station nodes, which behave like centroids for
routing purposes (through-paths shouldn't pass through them either).
"""
import argparse
import shutil
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from aequilibrae.project import Project
from aequilibrae.project.project_creation import add_triggers, remove_triggers

from config import load_settings

MILES_TO_METERS = 1609.344
CENTROID_FACTYPE = 0.0

settings = load_settings()
folder = Path(settings["paths"]["folder"])
net_settings = settings["aequilibrae_network"]
gdb_path = folder / net_settings["gdb"]
link_layer = net_settings["link_layer"]
node_layer = net_settings["node_layer"]
project_path = folder / net_settings["project_path"]


def centroid_node_ids(links: pd.DataFrame) -> set:
    connectors = links[links["FACTYPE"] == CENTROID_FACTYPE]
    connector_nodes = set(connectors["A"]) | set(connectors["B"])
    other = links[links["FACTYPE"] != CENTROID_FACTYPE]
    other_nodes = set(other["A"]) | set(other["B"])
    return connector_nodes - other_nodes


def build_nodes(centroid_ids: set) -> pd.DataFrame:
    nodes = gpd.read_file(gdb_path, layer=node_layer, columns=["N"]).to_crs(4326)
    nodes["node_id"] = nodes["N"].astype(int)
    nodes["is_centroid"] = nodes["node_id"].isin(centroid_ids).astype(int)
    nodes["modes"] = "c"
    nodes["lon"] = nodes.geometry.x
    nodes["lat"] = nodes.geometry.y
    return nodes[["node_id", "is_centroid", "modes", "lon", "lat"]]


def build_links(links: gpd.GeoDataFrame, drop_capacity_threshold: float | None = None) -> pd.DataFrame:
    links = links.to_crs(4326)
    links["link_id"] = np.arange(1, len(links) + 1)
    links["a_node"] = links["A"].astype(int)
    links["b_node"] = links["B"].astype(int)
    # Each AM_Link row is already a single travel direction (A -> B); the
    # reverse direction, where it exists, is a separate row.
    links["direction"] = 1
    links["distance"] = links["DISTANCE"] * MILES_TO_METERS
    links["modes"] = "c"
    links["link_type"] = np.where(links["FACTYPE"] == CENTROID_FACTYPE, "centroid_connector", "default")
    links["name"] = links["NAME"]
    links["lanes"] = links["LANES"]
    links["factype"] = links["FACTYPE"]
    links["speed_ab"] = links["AMSPD"]
    links["capacity_ab"] = links["AMCAPACITY"]
    links["travel_time_ab"] = links["TIME1"]

    # Centroid connectors (FACTYPE == 0) have AMCAPACITY == 0 by convention;
    # give them a large dummy value so AequilibraE's set_capacity_field()
    # validation doesn't reject the graph.
    connector_mask = links["factype"] == CENTROID_FACTYPE
    links.loc[connector_mask, "capacity_ab"] = 9999.0

    # Check for any remaining non-connector links with zero/null/negative capacity.
    bad_mask = ~connector_mask & (links["capacity_ab"].isna() | (links["capacity_ab"] <= 0))
    if bad_mask.any():
        bad = links.loc[bad_mask, ["link_id", "a_node", "b_node", "name", "factype", "lanes", "speed_ab", "capacity_ab",
                                   "travel_time_ab"]]
        print(f"\nWARNING: {bad_mask.sum()} non-connector link(s) have zero/null/negative capacity_ab:")
        print(bad.to_string(index=False))
        if drop_capacity_threshold is not None:
            drop_mask = ~connector_mask & (
                        links["capacity_ab"].isna() | (links["capacity_ab"] <= drop_capacity_threshold))
            n_drop = drop_mask.sum()
            links = links[~drop_mask].copy()
            print(f"Dropped {n_drop} link(s) with capacity_ab <= {drop_capacity_threshold}.")
        else:
            raise SystemExit(
                "\nHalting. Review the links above and re-run with --drop-low-capacity [THRESHOLD] to remove them."
            )

        # AM_Link stores geometry as single-part MultiLineString; convert to plain
        # LINESTRING as required by AequilibraE's links table.
    links["wkt"] = links.geometry.apply(lambda g: g.geoms[0].wkt)
    return links[
        [
            "link_id", "a_node", "b_node", "direction", "distance", "modes", "link_type",
            "name", "lanes", "factype", "speed_ab", "capacity_ab", "travel_time_ab", "wkt",
        ]
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing project at project_path")
    parser.add_argument(
        "--drop-low-capacity",
        type=float,
        metavar="THRESHOLD",
        nargs="?",
        const=0.0,
        default=None,
        help="Drop non-connector links with capacity_ab <= THRESHOLD before inserting. "
             "Omit the value to use the default threshold of 0 (i.e. --drop-low-capacity).",
    )
    args = parser.parse_args()

    if project_path.exists():
        if not args.overwrite:
            raise SystemExit(f"{project_path} already exists. Pass --overwrite to replace it.")
        shutil.rmtree(project_path)

    print(f"Reading {link_layer}/{node_layer} from {gdb_path}")
    raw_links = gpd.read_file(
        gdb_path, layer=link_layer,
        columns=["A", "B", "NAME", "FACTYPE", "LANES", "DISTANCE", "AMSPD", "AMCAPACITY", "TIME1"],
    )
    centroid_ids = centroid_node_ids(raw_links)
    nodes_df = build_nodes(centroid_ids)
    links_df = build_links(raw_links, drop_capacity_threshold=args.drop_low_capacity)
    print(f"  {len(nodes_df):,} nodes ({nodes_df['is_centroid'].sum():,} centroids), {len(links_df):,} links")

    project = Project()
    project.new(str(project_path))
    try:
        project.network.links.fields.add("lanes", "Number of through lanes in one direction (AM_Link.LANES)")
        project.network.links.fields.add("factype", "Facility type code (AM_Link.FACTYPE)")

        with project.db_connection as conn:
            remove_triggers(conn, project.logger, "network")

            print("Inserting nodes...")
            node_cols = ["node_id", "is_centroid", "modes"]
            conn.executemany(
                f"INSERT INTO nodes ({','.join(node_cols)}, geometry) VALUES (?,?,?, MakePoint(?,?,4326))",
                nodes_df[node_cols + ["lon", "lat"]].to_records(index=False),
            )

            print("Inserting links...")
            link_cols = [
                "link_id", "a_node", "b_node", "direction", "distance", "modes", "link_type",
                "name", "lanes", "factype", "speed_ab", "capacity_ab", "travel_time_ab",
            ]
            placeholders = ",".join(["?"] * len(link_cols))
            conn.executemany(
                f"INSERT INTO links ({','.join(link_cols)}, geometry) VALUES ({placeholders}, GeomFromText(?, 4326))",
                links_df[link_cols + ["wkt"]].to_records(index=False),
            )

            add_triggers(conn, project.logger, "network")
    finally:
        project.close()

    print(f"AequilibraE project written to {project_path}")


if __name__ == "__main__":
    main()
