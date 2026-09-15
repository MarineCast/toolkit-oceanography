"""Water-path influence kernels; never spread a land gauge directly into marine cells."""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree
from shapely.geometry import LineString, Point, box
from shapely.ops import nearest_points


def water_distances(doc, cfg, seeds):
    """Distance from explicit marine seed coordinates over the existing R8 water graph.

    Short seed connectors must lie within the water mask buffered by the explicitly
    configured shoreline tolerance. Canonical terminal connectors are target-only;
    they cannot open a new route through land. Disconnected targets stay infinite.
    """
    root = doc.resolve_path(cfg.support_dir)
    support = (
        pd.read_parquet(root / "h3_geometry/H3_MODEL_AREA_SUPPORT_RES_8.parquet")
        .sort_values("H3_INDEX")
        .reset_index(drop=True)
    )
    edges = pd.read_parquet(
        root / "water_network/H3_WATER_PASSABLE_EDGES_RES_8.parquet",
        columns=["SOURCE_H3_INDEX", "TARGET_H3_INDEX", "EDGE_DISTANCE_M", "EDGE_IS_WATER_PASSABLE"],
        filters=[("SOURCE_H3_INDEX", "in", support.H3_INDEX.tolist())],
    )
    edges = edges.loc[edges.EDGE_IS_WATER_PASSABLE.astype(bool)].copy()
    pos = {h: i for i, h in enumerate(support.H3_INDEX)}
    edges = edges.loc[edges.SOURCE_H3_INDEX.isin(pos) & edges.TARGET_H3_INDEX.isin(pos)]
    # Stored edges may include both orientations; do not sum reciprocal distances.
    pairs = {}
    for a, b, w in edges[["SOURCE_H3_INDEX", "TARGET_H3_INDEX", "EDGE_DISTANCE_M"]].itertuples(
        index=False, name=None
    ):
        i, j = sorted((pos[a], pos[b]))
        pairs[i, j] = min(float(w) / 1000, pairs.get((i, j), np.inf))
    ii, jj, ww = [], [], []
    for (i, j), w in pairs.items():
        ii += [i, j]
        jj += [j, i]
        ww += [w, w]
    graph = coo_matrix((ww, (ii, jj)), shape=(len(support), len(support))).tocsr()
    project = Transformer.from_crs(4326, 32610, always_xy=True)
    x, y = project.transform(
        support.REPRESENTATIVE_POINT_LONGITUDE.to_numpy(),
        support.REPRESENTATIVE_POINT_LATITUDE.to_numpy(),
    )
    eligible = np.flatnonzero(
        support.GRAPH_NODE_ELIGIBLE.fillna(False).to_numpy() & (support.GRAPH_DEGREE.to_numpy() > 0)
    )
    tree = cKDTree(np.column_stack([x[eligible], y[eligible]]))
    water_frame = gpd.read_parquet(
        root / "water_geometry/TERRITORIAL_WATER_POLYGON.parquet"
    ).to_crs(4326)
    b = cfg.bbox
    water_frame.geometry = water_frame.geometry.intersection(
        box(b["min_lon"] - 0.1, b["min_lat"] - 0.1, b["max_lon"] + 0.1, b["max_lat"] + 0.1)
    )
    coast_water = water_frame.to_crs(32610).geometry.union_all()
    water = coast_water.buffer(cfg.seed_shore_tolerance_m)
    unproject = Transformer.from_crs(32610, 4326, always_xy=True)
    distances = np.full((len(seeds), len(support)), np.inf)
    audit = []
    for si, seed in enumerate(seeds):
        sx, sy = project.transform(seed["lon"], seed["lat"])
        origin = Point(sx, sy)
        coastal = nearest_points(origin, coast_water)[1]
        coast_distance = origin.distance(coastal)
        max_coast = (
            cfg.mouth_coast_snap_max_m
            if seed.get("kind") == "river_mouth"
            else cfg.tide_coast_snap_max_m
        )
        if coast_distance <= max_coast:
            sx, sy = coastal.x, coastal.y
        dd, ix = tree.query([sx, sy], k=min(30, len(eligible)))
        picked = None
        for dist, ni in zip(np.atleast_1d(dd), np.atleast_1d(ix)):
            if dist > cfg.seed_snap_max_km * 1000 or coast_distance > max_coast:
                break
            node = eligible[ni]
            line = LineString([(sx, sy), (x[node], y[node])])
            if water.covers(line):
                picked = (node, (dist + coast_distance) / 1000)
                break
        item = {
            **seed,
            "status": "unmapped",
            "snap_distance_km": None,
            "seed_h3": None,
            "coast_snap_distance_m": coast_distance,
            "marine_seed_lon": unproject.transform(sx, sy)[0],
            "marine_seed_lat": unproject.transform(sx, sy)[1],
        }
        if picked is not None:
            node, connector = picked
            row = dijkstra(graph, directed=False, indices=int(node)) + connector
            for ti, target in support.loc[
                support.GRAPH_CONNECTION_STATUS == "terminal_connector"
            ].iterrows():
                dest = pos.get(target.CONNECTOR_TARGET_H3_INDEX)
                if dest is not None:
                    row[ti] = row[dest] + target.CONNECTOR_DISTANCE_M / 1000
            distances[si] = row
            item.update(
                status="mapped", snap_distance_km=connector, seed_h3=support.iloc[node].H3_INDEX
            )
        audit.append(item)
    return support, distances, audit


def kernel_features(distances, values, scale, cutoff=3.0, normalize=False):
    """Missing contributing gauges invalidate a cell; outside support is null, not zero.

    Discharge sums Q*exp(-water_distance/scale). Tides normalize the same weights.
    Neither is a calibrated transport or hydrodynamic model.
    """
    values = np.asarray(values, dtype=float)
    weights = np.where(distances <= scale * cutoff, np.exp(-distances / scale), 0.0)
    present = np.isfinite(values)
    expected = (weights > 0).sum(axis=0)
    observed = ((weights > 0) & present[:, None]).sum(axis=0)
    result = (weights * np.where(present, values, 0)[:, None]).sum(axis=0)
    total = weights.sum(axis=0)
    if normalize:
        result = np.divide(result, total, out=np.full_like(total, np.nan), where=total > 0)
    result[(expected == 0) | (observed != expected)] = np.nan
    fraction = np.divide(
        observed, expected, out=np.full(expected.shape, np.nan), where=expected > 0
    )
    nearest = np.min(np.where(weights > 0, distances, np.inf), axis=0)
    nearest[~np.isfinite(nearest)] = np.nan
    return result, expected, observed, fraction, nearest
