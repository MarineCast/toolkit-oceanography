import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr
from pydantic import ValidationError

from oceanography.build import (
    aggregate_pixels,
    collocated_speed,
    discharge_value,
    validate_times,
)
from oceanography.config import OceanConfig, load
from oceanography.download import (
    Cache,
    check_date,
    digest,
    write_json,
)
from oceanography.spatial import kernel_features


def test_real_config_strict_and_composed(tmp_path):
    doc, cfg = load()
    assert cfg.satellites["productivity"].resolution == 5
    assert len(cfg.rivers) == 14
    bad = dict(doc.data, accidental_typo=True)
    with pytest.raises(ValidationError):
        OceanConfig.model_validate(bad)
    with pytest.raises(ValidationError):
        OceanConfig.model_validate(dict(doc.data, raw_dir="../elsewhere"))
    child = tmp_path / "child.yaml"
    child.write_text(f"extends: {doc.source}\ncurrent_interval_hours: 6\n")
    assert load(child)[1].current_interval_hours == 6


def test_discharge_units_and_date_identity():
    p = {
        "monitoring_location_id": "USGS-1",
        "time": "2024-07-01",
        "parameter_code": "00060",
        "statistic_id": "00003",
        "value": "100",
        "unit_of_measure": "ft^3/s",
    }
    feature = {"properties": p}
    assert discharge_value(feature, "USGS", "USGS-1", "2024-07-01")[0] == pytest.approx(
        2.8316846592
    )
    with pytest.raises(ValueError):
        discharge_value(feature, "USGS", "USGS-2", "2024-07-01")
    p["unit_of_measure"] = "unknown"
    with pytest.raises(ValueError):
        discharge_value(feature, "USGS", "USGS-1", "2024-07-01")
    p["unit_of_measure"] = "m3/s"
    p["value"] = None
    assert np.isnan(discharge_value(feature, "USGS", "USGS-1", "2024-07-01")[0])
    p["value"] = "0"
    assert discharge_value(feature, "USGS", "USGS-1", "2024-07-01")[0] == 0


def test_kernels_decay_missingness_and_disconnected_water():
    d = np.array([[0.0, 10.0, np.inf], [np.inf, 10.0, np.inf]])
    value, expected, observed, fraction, nearest = kernel_features(d, [100.0, 50.0], 10)
    assert value[0] == 100
    assert value[1] == pytest.approx(150 / np.e)
    assert np.isnan(value[2])
    value, *_ = kernel_features(d, [100.0, np.nan], 10)
    assert value[0] == 100 and np.isnan(value[1])
    value, *_ = kernel_features(d, [2.0, 4.0], 10, normalize=True)
    assert value[1] == 3


def test_current_faces_are_collocated_and_land_stays_missing():
    u = np.full((2, 3, 3), 3.0)
    v = np.full((2, 3, 3), 4.0)
    wet = np.ones((3, 3), dtype=bool)
    wet[2, 2] = False
    speed = collocated_speed(u, v, wet)
    assert speed[0, 1, 1] == 5
    assert np.isnan(speed[:, :, 0]).all() and np.isnan(speed[:, 0, :]).all()
    assert np.isnan(speed[:, 2, 2]).all()
    u[0, 1, 0] = np.nan
    assert np.isnan(collocated_speed(u, v, wet)[0, 1, 1])


def test_grid_missing_is_not_zero_or_nearest_neighbor():
    import h3

    cell = h3.latlng_to_cell(48.5, -123.5, 6)
    other = h3.latlng_to_cell(49.0, -123.5, 6)
    support = pd.DataFrame({"H3_INDEX": [cell, other], "WATER_AREA_M2": [10.0, 20.0]})
    out = aggregate_pixels([48.5], [-123.5], {"SST_MEAN_C": [0.0]}, support, 6).set_index(
        "H3_INDEX"
    )
    assert out.loc[cell, "SST_MEAN_C"] == 0
    assert pd.isna(out.loc[other, "SST_MEAN_C"])
    assert out.loc[other, "SST_MEAN_C_VALID_PIXELS"] == 0


def test_reject_nearest_date_and_duplicate_times():
    attrs = {
        ("NC_GLOBAL", "time_coverage_start"): "2020-01-01T00:00:00Z",
        ("NC_GLOBAL", "time_coverage_end"): "2021-01-01T00:00:00Z",
    }
    with pytest.raises(ValueError):
        check_date(attrs, "2024-07-01")
    ds = xr.Dataset(coords={"time": pd.to_datetime(["2024-07-01", "2024-07-01"])})
    with pytest.raises(ValueError):
        validate_times(ds, "2024-07-01", 2)
    ds = xr.Dataset(coords={"time": pd.to_datetime(["2024-07-02"])})
    with pytest.raises(ValueError):
        validate_times(ds, "2024-07-01", 1)


def test_cache_tampering_rejected(tmp_path):
    import hashlib

    import requests

    url = (
        requests.Request("GET", "https://example.com/data", params={"day": "2024-07-01"})
        .prepare()
        .url
    )
    key = hashlib.sha256(url.encode()).hexdigest()
    p = tmp_path / (key + ".json")
    p.write_text("{}")
    write_json(
        tmp_path / (key + ".manifest.json"),
        {"url": url, "sha256": digest(p), "retrieved_at": "original"},
    )
    cache = Cache(tmp_path, offline=True)
    assert cache.get(url) == p
    p.write_text('{"changed":true}')
    with pytest.raises(ValueError):
        cache.get(url)
    with pytest.raises(FileNotFoundError):
        cache.get("https://example.com/other")


def test_water_graph_keeps_disconnected_basins_separate(tmp_path):
    import geopandas as gpd
    import h3
    from shapely.geometry import box

    from oceanography.spatial import water_distances

    _, cfg = load()
    geometry_dir = tmp_path / "h3_geometry"
    geometry_dir.mkdir()
    network_dir = tmp_path / "water_network"
    network_dir.mkdir()
    water_dir = tmp_path / "water_geometry"
    water_dir.mkdir()
    lat = [48.5, 48.51, 48.5, 48.51]
    lon = [-123.10, -123.10, -123.05, -123.05]
    cells = [h3.latlng_to_cell(a, b, 8) for a, b in zip(lat, lon)]
    pd.DataFrame(
        {
            "H3_INDEX": cells,
            "REPRESENTATIVE_POINT_LATITUDE": lat,
            "REPRESENTATIVE_POINT_LONGITUDE": lon,
            "GRAPH_NODE_ELIGIBLE": True,
            "GRAPH_DEGREE": 1,
            "GRAPH_CONNECTION_STATUS": "graph_node",
        }
    ).to_parquet(geometry_dir / "H3_MODEL_AREA_SUPPORT_RES_8.parquet")
    pd.DataFrame(
        {
            "SOURCE_H3_INDEX": [cells[0], cells[2]],
            "TARGET_H3_INDEX": [cells[1], cells[3]],
            "EDGE_DISTANCE_M": [1000.0, 1000.0],
            "EDGE_IS_WATER_PASSABLE": True,
        }
    ).to_parquet(network_dir / "H3_WATER_PASSABLE_EDGES_RES_8.parquet")
    gpd.GeoDataFrame(
        geometry=[box(-123.11, 48.49, -123.09, 48.52), box(-123.06, 48.49, -123.04, 48.52)],
        crs=4326,
    ).to_parquet(water_dir / "TERRITORIAL_WATER_POLYGON.parquet")

    class Doc:
        def resolve_path(self, value):
            return tmp_path

    support, distances, audit = water_distances(
        Doc(),
        cfg,
        [
            {"station": "left", "lon": lon[0], "lat": lat[0]},
            {"station": "land", "lon": -123.075, "lat": 48.5},
        ],
    )
    positions = {c: i for i, c in enumerate(support.H3_INDEX)}
    assert distances[0, positions[cells[1]]] == pytest.approx(1.0)
    assert np.isinf(distances[0, positions[cells[2]]])
    assert audit[1]["status"] == "unmapped"
    assert np.isinf(distances[1]).all()


def test_trailing_composite_excludes_future_and_retains_age():
    from oceanography.composite import MEAN, trailing_cell_features

    daily = {
        "2024-06-25": pd.Series({"a": 2.0, "b": np.nan}),
        "2024-06-30": pd.Series({"a": 4.0, "b": 3.0}),
        "2024-07-01": pd.Series({"a": 6.0, "b": np.nan}),
        "2024-07-02": pd.Series({"a": 1000.0, "b": 1000.0}),
    }
    out = trailing_cell_features(daily, "2024-07-01", ["a", "b"], minimum=2).set_index("H3_INDEX")
    assert out.loc["a", MEAN] == 4.0
    assert out.loc["a", "COMPOSITE_VALID_DAYS"] == 3
    assert out.loc["a", "COMPOSITE_NEWEST_AGE_DAYS"] == 0
    assert out.loc["a", "COMPOSITE_OLDEST_AGE_DAYS"] == 6
    assert np.isnan(out.loc["b", MEAN])
    assert out.loc["b", "COMPOSITE_NEWEST_AGE_DAYS"] == 1


def test_tide_complex_interpolation_respects_phase_wrap_and_mesh():
    from oceanography.regional_sources import interpolate_harmonics

    nodes = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
    harmonic = np.exp(1j * np.deg2rad([179.0, -179.0, 179.0]))[:, None]
    values, ids = interpolate_harmonics(
        nodes, np.array([[0, 1, 2]]), harmonic, np.array([0.5, 2.0]), np.array([0.0, 2.0])
    )
    assert values[0, 0].real < -0.99
    assert abs(values[0, 0].imag) < 1e-10
    assert np.isnan(values[1, 0]) and ids[1] == -1


def test_tide_overlapping_disagreeing_mesh_is_rejected():
    from oceanography.regional_sources import interpolate_harmonics

    nodes = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [0.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
    harmonic = np.array([[1], [1], [1], [2], [2], [2]], dtype=complex)
    values, ids = interpolate_harmonics(
        nodes, np.array([[0, 1, 2], [3, 4, 5]]), harmonic, np.array([0.2]), np.array([0.2])
    )
    assert np.isnan(values[0, 0]) and ids[0] == -2


def test_tide_archive_rejects_arbitrary_installer(tmp_path):
    from oceanography.regional_sources import tide_archive

    p = tmp_path / "installer.sh"
    p.write_text("#!/bin/sh\necho not a tidal archive\n")
    with pytest.raises(ValueError):
        tide_archive(p)


def test_tide_dateline_triangle_does_not_cover_washington():
    from oceanography.regional_sources import interpolate_harmonics

    nodes = np.array([[-179.0, 48.0], [179.0, 48.0], [-179.0, 50.0]])
    values, ids = interpolate_harmonics(
        nodes, np.array([[0, 1, 2]]), np.ones((3, 1), complex), np.array([-123.0]), np.array([49.0])
    )
    assert ids[0] == -1 and np.isnan(values[0, 0])
