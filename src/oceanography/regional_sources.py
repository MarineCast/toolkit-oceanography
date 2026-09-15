"""Public broader-domain alternatives: HYCOM surface flow and DFO tidal harmonics."""

import io
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from .normalization import aggregate_pixels, support_at, validate_times, verified


def collect_regional(cache, cfg, family, day):
    if family == "tidal_model":
        path = cache.get(cfg.tide_model_url, suffix=".sh")
        # Read embedded data only. The downloaded shell/Java installer is never executed.
        with tide_archive(path) as archive:
            if not any(n.endswith("ne_pac4_ll.nod") for n in archive.namelist()):
                raise ValueError("Missing tidal mesh")
        return {
            "paths": [str(path)],
            "dataset": "DFO WebTide Northeast Pacific v0.7",
            "access": "public; installer treated only as a data archive",
        }
    base = f"{cfg.offshore_current_base}/{pd.Timestamp(day).year}"
    metadata = cache.get(base + "/dataset.xml", suffix=".xml")
    root = ET.fromstring(metadata.read_bytes())
    begin, end = root.findtext(".//TimeSpan/begin"), root.findtext(".//TimeSpan/end")
    if not begin or not end:
        raise ValueError("HYCOM archive time bounds missing")
    lo = pd.Timestamp(day + "T00:00:00Z")
    hi = pd.Timestamp(day + "T21:00:00Z")
    if lo < pd.Timestamp(begin) or hi > pd.Timestamp(end):
        raise ValueError(f"HYCOM date outside {begin}..{end}")
    b = cfg.bbox
    params = {
        "var": "water_u,water_v",
        "north": b["max_lat"],
        "south": b["min_lat"],
        "west": b["min_lon"],
        "east": b["max_lon"],
        "horizStride": 1,
        "time_start": lo.isoformat(),
        "time_end": hi.isoformat(),
        "timeStride": 1,
        "vertCoord": 0,
        "accept": "netcdf4",
    }
    path = cache.get(base, params, suffix=".nc")
    return {
        "paths": [str(path)],
        "metadata_paths": [str(metadata)],
        "dataset": "HYCOM GOFS 3.1 GLBy0.08 expt_93.0",
        "archive_start": begin,
        "archive_end": end,
    }


def tide_archive(path):
    data = Path(path).read_bytes()
    # Locate ZIP end-of-central-directory, whose comment length bounds the archive.
    candidates = [m.start() for m in re.finditer(re.escape(b"PK\x05\x06"), data)]
    for offset in candidates:
        if offset + 22 > len(data):
            continue
        end = offset + 22 + int.from_bytes(data[offset + 20 : offset + 22], "little")
        try:
            archive = zipfile.ZipFile(io.BytesIO(data[:end]))
            if any(n.endswith("ne_pac4_ll.nod") for n in archive.namelist()):
                return archive
            archive.close()
        except zipfile.BadZipFile:
            continue
    raise ValueError("No verified WebTide ZIP payload found")


def load_tide_mesh(path):
    with tide_archive(path) as z:

        def read(name):
            matches = [n for n in z.namelist() if n.endswith(name)]
            if len(matches) != 1:
                raise ValueError("Ambiguous tidal archive member")
            return z.read(matches[0])

        nodes = np.loadtxt(io.BytesIO(read("ne_pac4_ll.nod")))
        elements = np.loadtxt(io.BytesIO(read("ne_pac4.ele")), dtype=int)
        if not np.array_equal(nodes[:, 0], np.arange(1, len(nodes) + 1)):
            raise ValueError("Unexpected tidal node identifiers")
        names = ["M2", "S2", "N2", "K2", "K1", "O1", "P1", "Q1"]
        harmonics = []
        for name in names:
            values = np.loadtxt(io.BytesIO(read(name + ".barotropic.s2c")), skiprows=3)
            if not np.array_equal(values[:, 0], nodes[:, 0]):
                raise ValueError("Tidal constituent node mismatch")
            harmonics.append(values[:, 1] * np.exp(-1j * np.deg2rad(values[:, 2])))
    return nodes[:, 1:3], elements[:, 1:4] - 1, np.array(harmonics).T, names


def interpolate_harmonics(nodes, triangles, harmonics, lon, lat):
    import shapely
    from shapely.strtree import STRtree

    lon, lat = np.asarray(lon) % 360, np.asarray(lat)
    nodes = nodes.copy()
    nodes[:, 0] %= 360
    # This Northeast Pacific mesh crosses the dateline. Unwrap it before polygon
    # queries so dateline triangles cannot appear to cover the study area.
    vertices = nodes[triangles]
    near = (
        (vertices[:, :, 0].max(axis=1) >= lon.min())
        & (vertices[:, :, 0].min(axis=1) <= lon.max())
        & (vertices[:, :, 1].max(axis=1) >= lat.min())
        & (vertices[:, :, 1].min(axis=1) <= lat.max())
    )
    source_ids = np.flatnonzero(near)
    polygons = shapely.polygons(vertices[source_ids])
    valid = shapely.is_valid(polygons) & (shapely.area(polygons) > 1e-12)
    source_ids = source_ids[valid]
    polygons = polygons[valid]
    result = np.full((len(lon), harmonics.shape[1]), np.nan + 1j * np.nan)
    indices = np.full(len(lon), -1, dtype=int)
    if not len(polygons):
        return result, indices
    pairs = STRtree(polygons).query(shapely.points(lon, lat), predicate="intersects")
    for point in np.unique(pairs[0]):
        tids = source_ids[pairs[1, pairs[0] == point]]
        vertex = triangles[tids]
        p = nodes[vertex]
        matrix = np.stack([p[:, 0] - p[:, 2], p[:, 1] - p[:, 2]], axis=-1)
        w = np.linalg.solve(matrix, (np.array([lon[point], lat[point]]) - p[:, 2])[..., None])[
            ..., 0
        ]
        weights = np.column_stack([w, 1 - w.sum(axis=1)])
        candidates = (harmonics[vertex] * weights[:, :, None]).sum(axis=1)
        # Shared-edge candidates agree. Rounded/overlapping native triangles that
        # disagree are marked ambiguous, rather than silently repairing the mesh.
        if np.max(np.abs(candidates - candidates[0])) > 1e-6:
            indices[point] = -2
            continue
        result[point] = candidates[0]
        indices[point] = tids[0]
    return result, indices


def predict_tide(times, lat, harmonics, names):
    from utide._time_conversion import _normalize_time
    from utide._ut_constants import ut_constants
    from utide.harmonics import ut_E

    index = np.array([list(ut_constants.const.name).index(n) for n in names])
    t = _normalize_time(np.asarray(times, dtype="datetime64[ns]"))
    result = np.full((len(harmonics), len(t)), np.nan)
    for i, (latitude, coef) in enumerate(zip(lat, harmonics)):
        if not np.isfinite(coef).all():
            continue
        basis = ut_E(
            t,
            float(t.mean()),
            ut_constants.const.freq[index],
            index,
            float(latitude),
            [False, False, False, False],
            None,
        )
        result[i] = np.real(basis @ coef)
    return result


def regional_frame(doc, cfg, family, manifest, out, cache):
    if family == "offshore_currents":
        with xr.open_dataset(verified(manifest["paths"][0])) as ds:
            validate_times(ds, manifest["date"], 8)
            if not np.array_equal(pd.DatetimeIndex(ds.time.values).hour, np.arange(0, 24, 3)):
                raise ValueError("Unexpected HYCOM sampling hours")
            if ds.depth.size != 1 or float(ds.depth.values[0]) != 0:
                raise ValueError("Expected surface HYCOM level")
            for v in ["water_u", "water_v"]:
                if ds[v].attrs.get("units") not in ("m/s", "m s-1"):
                    raise ValueError("Unexpected HYCOM velocity units")
            speed = np.hypot(ds.water_u.values[:, 0], ds.water_v.values[:, 0])
            complete = np.isfinite(speed).sum(axis=0) == 8
            mean = np.where(
                complete, np.where(np.isfinite(speed), speed, 0).sum(axis=0) / 8, np.nan
            )
            peak = np.where(
                complete, np.max(np.where(np.isfinite(speed), speed, -np.inf), axis=0), np.nan
            )
            lon, lat = np.meshgrid((ds.lon.values + 180) % 360 - 180, ds.lat.values)
            metrics = {
                "OFFSHORE_CURRENT_SPEED_SAMPLE_MEAN_MS": mean,
                "OFFSHORE_CURRENT_SPEED_SAMPLE_MAX_MEAN_MS": peak,
            }
            pd.DataFrame(
                {
                    "LATITUDE": lat.ravel(),
                    "LONGITUDE": lon.ravel(),
                    **{k: v.ravel() for k, v in metrics.items()},
                }
            ).to_parquet(out / "LAYER.parquet", index=False)
            frame = aggregate_pixels(lat, lon, metrics, support_at(doc, cfg, 5), 5)
        frame["H3_RESOLUTION"] = 5
        return frame, {
            "interpretation": "HYCOM offshore surface-flow candidate on R5; separate from SalishSeaCast.",
            "spatial_aggregation": "native grid-point means to R5; all eight three-hourly samples required per pixel",
            "limitations": "Global model cannot resolve narrow inlets or local tidal jets. Not blended with regional currents; archive expt_93.0 ends September 2024.",
            "source_native_grid_degrees": [0.04, 0.08],
            "expected_samples": 8,
            "depth_m": 0,
        }
    key = ("tidal_mesh", manifest["paths"][0])
    if key not in cache:
        mesh = load_tide_mesh(verified(manifest["paths"][0]))
        support = pd.read_parquet(
            doc.resolve_path(cfg.support_dir) / "h3_geometry/H3_MODEL_AREA_SUPPORT_RES_6.parquet"
        )
        support = support.loc[support.HAS_WATER_OVERLAP].copy().reset_index(drop=True)
        coef, tri = interpolate_harmonics(
            *mesh[:3],
            support.REPRESENTATIVE_POINT_LONGITUDE.to_numpy(),
            support.REPRESENTATIVE_POINT_LATITUDE.to_numpy(),
        )
        cache[key] = (mesh, support, coef, tri)
    mesh, support, coef, tri = cache[key]
    times = pd.date_range(manifest["date"], periods=24, freq="h")
    heights = predict_tide(times, support.REPRESENTATIVE_POINT_LATITUDE.to_numpy(), coef, mesh[3])
    valid = np.isfinite(heights).all(axis=1)
    ranges = np.full(len(support), np.nan)
    ranges[valid] = np.ptp(heights[valid], axis=1)
    frame = support[["H3_INDEX", "WATER_AREA_M2"]].copy()
    frame["HARMONIC_TIDE_HOURLY_RANGE_M"] = ranges
    frame["H3_RESOLUTION"] = 6
    frame["NATIVE_TRIANGLE_INDEX"] = tri
    pd.DataFrame(
        {
            "H3_INDEX": np.repeat(support.H3_INDEX.to_numpy(), 24),
            "TIME_UTC": np.tile(times, len(support)),
            "PREDICTED_HEIGHT_RELATIVE_M": heights.ravel(),
        }
    ).to_parquet(out / "LAYER.parquet", index=False)
    return frame, {
        "interpretation": "DFO Northeast Pacific eight-constituent tidal model, reconstructed with UTide astronomical and nodal corrections.",
        "spatial_aggregation": "complex harmonic interpolation inside native mesh triangles at R6 water representative points; no outside-mesh extrapolation",
        "limitations": "Older regional harmonic model; validate against CHS/NOAA predictions. No storm surge or absolute station datum; unresolved coast and outside-mesh locations remain missing.",
        "constituents": mesh[3],
        "prediction_engine": "UTide 0.3.1",
        "date_basis": "24 hourly UTC predictions; hourly sampled range",
    }
