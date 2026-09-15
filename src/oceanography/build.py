"""Normalize acquired bytes and produce daily H3 research candidates without imputation."""

from __future__ import annotations

import json
from pathlib import Path

import h3
import numpy as np
import pandas as pd
import xarray as xr

from .config import DEFAULT_CONFIG, load
from .download import FAMILIES, digest, write_json
from .normalization import aggregate_pixels, read_json, support_at, validate_times, verified
from .spatial import kernel_features, water_distances


def satellite_frame(doc, cfg, family, manifest, out):
    spec = cfg.satellites[family]
    with xr.open_dataset(verified(manifest["paths"][0])) as ds:
        validate_times(ds, manifest["date"], 1)
        if ds[spec.variable].attrs.get("units") != spec.units:
            raise ValueError("Unexpected netCDF units")
        values = ds[spec.variable].values.squeeze().astype(float)
        if values.ndim != 2 or not np.all(np.diff(ds.latitude.values) < 0):
            raise ValueError("Unexpected satellite grid")
        if spec.quality_variable:
            quality = ds[spec.quality_variable].values.squeeze()
            values = np.where((quality >= spec.quality_min) & (quality <= 5), values, np.nan)
        if family == "productivity":
            values = np.where(values > 0, values, np.nan)
            metrics = {"CHLOROPHYLL_MEAN_MG_M3": values, "CHLOROPHYLL_LOG_MEAN": np.log(values)}
        else:
            values = np.where((values >= -3) & (values <= 45), values, np.nan)
            metrics = {"SST_MEAN_C": values}
        lon, lat = np.meshgrid(ds.longitude.values, ds.latitude.values)
        layer = pd.DataFrame(
            {
                "LATITUDE": lat.ravel(),
                "LONGITUDE": lon.ravel(),
                **{k: v.ravel() for k, v in metrics.items()},
            }
        )
        layer.to_parquet(out / "LAYER.parquet", index=False)
        frame = aggregate_pixels(
            lat, lon, metrics, support_at(doc, cfg, spec.resolution), spec.resolution
        )
    frame["H3_RESOLUTION"] = spec.resolution
    return frame, {
        "interpretation": spec.interpretation,
        "spatial_aggregation": "cos(latitude)-weighted valid native pixel centers; no spatial gap fill",
        "date_basis": "source daily composite UTC label",
        "source_dataset": spec.dataset,
    }


def collocated_speed(u, v, wet):
    """NEMO C-grid: average adjacent faces to T centers, then rotation-invariant speed."""
    u, v = np.asarray(u, dtype=float), np.asarray(v, dtype=float)
    if u.shape != v.shape or u.shape[-2:] != wet.shape:
        raise ValueError("Velocity/geometry shape mismatch")
    uc = np.full_like(u, np.nan)
    vc = np.full_like(v, np.nan)
    uc[..., :, 1:] = 0.5 * (u[..., :, 1:] + u[..., :, :-1])
    vc[..., 1:, :] = 0.5 * (v[..., 1:, :] + v[..., :-1, :])
    return np.where(wet, np.hypot(uc, vc), np.nan)


def currents_frame(doc, cfg, manifest, out):
    with (
        xr.open_dataset(verified(manifest["paths"][0])) as ud,
        xr.open_dataset(verified(manifest["paths"][1])) as vd,
        xr.open_dataset(verified(manifest["geometry_path"])) as geo,
    ):
        expected = 24 // cfg.current_interval_hours
        validate_times(ud, manifest["date"], expected)
        validate_times(vd, manifest["date"], expected)
        if not np.array_equal(ud.time.values, vd.time.values):
            raise ValueError("U/V time mismatch")
        for dim in ["gridX", "gridY"]:
            if not np.array_equal(ud[dim], vd[dim]) or not np.array_equal(ud[dim], geo[dim]):
                raise ValueError("U/V/geometry coordinate mismatch")
        u = ud.uVelocity.values[:, 0, :, :]
        v = vd.vVelocity.values[:, 0, :, :]
        u = np.where(np.abs(u) < 100, u, np.nan)
        v = np.where(np.abs(v) < 100, v, np.nan)
        speed = collocated_speed(u, v, geo.bathymetry.values > 0)
        complete = np.isfinite(speed).sum(axis=0) == expected
        mean = np.where(
            complete, np.sum(np.where(np.isfinite(speed), speed, 0), axis=0) / expected, np.nan
        )
        peak = np.where(
            complete, np.max(np.where(np.isfinite(speed), speed, -np.inf), axis=0), np.nan
        )
        # Native curvilinear point means: explicitly not an exact cell-area integral.
        lat, lon = geo.latitude.values, geo.longitude.values
        metrics = {"CURRENT_SPEED_SAMPLE_MEAN_MS": mean, "CURRENT_SPEED_SAMPLE_MAX_MEAN_MS": peak}
        pd.DataFrame(
            {
                "LATITUDE": lat.ravel(),
                "LONGITUDE": lon.ravel(),
                **{k: v.ravel() for k, v in metrics.items()},
            }
        ).to_parquet(out / "LAYER.parquet", index=False)
        frame = aggregate_pixels(lat, lon, metrics, support_at(doc, cfg, 6), 6)
        depth = float(ud.depth.values[0])
    frame["H3_RESOLUTION"] = 6
    frame["EXPECTED_TIME_SAMPLES"] = expected
    return frame, {
        "interpretation": "SalishSeaCast modeled surface speed, not observations. Outer-coast and model-land gaps remain missing.",
        "depth_m": depth,
        "spatial_aggregation": "native T-point weighted sample means after C-grid face collocation; maximum column is spatial mean of native sampled maxima, not true daily peak",
        "date_basis": "UTC; one-hour means sampled every configured interval",
        "interval_hours": cfg.current_interval_hours,
    }


def normalize_tides(manifest, minimum):
    rows = []
    for s in manifest.get("stations", []):
        data = read_json(s["path"])
        vals = data if s["provider"] == "CHS" else data["predictions"]
        samples = []
        for v in vals:
            time = pd.Timestamp(v["eventDate"] if s["provider"] == "CHS" else v["t"])
            if time.strftime("%Y-%m-%d") != manifest["date"]:
                continue
            samples.append((time, float(v["value"] if s["provider"] == "CHS" else v["v"])))
        series = pd.Series([x[1] for x in samples], index=[x[0] for x in samples], dtype=float)
        if series.index.has_duplicates:
            raise ValueError("Duplicate tide timestamps")
        good = series[np.isfinite(series)]
        value = float(good.max() - good.min()) if len(good) >= minimum else np.nan
        rows.append(
            {
                **s,
                "DATE": manifest["date"],
                "TIDE_HOURLY_RANGE_M": value,
                "SAMPLE_COUNT": len(good),
                "MEASUREMENT_KIND": "astronomical_prediction",
            }
        )
    return pd.DataFrame(rows)


def discharge_value(feature, provider, station, day):
    p = feature["properties"]
    if provider == "ECCC":
        if p["STATION_NUMBER"] != station or p["DATE"][:10] != day:
            raise ValueError("Unexpected Canadian station/date")
        value = p.get("DISCHARGE")
        unit = "m3/s"
        qc = p.get("DISCHARGE_SYMBOL_EN")
        basis = "HYDAT provider daily date"
    else:
        if (
            p["monitoring_location_id"] != station
            or p["time"][:10] != day
            or p["parameter_code"] != "00060"
            or p["statistic_id"] != "00003"
        ):
            raise ValueError("Unexpected US station/date/parameter")
        value = p.get("value")
        unit = p.get("unit_of_measure")
        qc = json.dumps({"approval": p.get("approval_status"), "qualifier": p.get("qualifier")})
        basis = "USGS provider daily date"
    value = float(value) if value not in (None, "") else np.nan
    if unit in ("ft^3/s", "ft3/s"):
        value *= 0.028316846592
    elif unit not in ("m3/s", "m^3/s"):
        raise ValueError(f"Unknown discharge unit {unit}")
    if not np.isfinite(value) or value < 0:
        value = np.nan
    return value, qc, basis


def normalize_rivers(manifest, cfg):
    rows = []
    for gauge in cfg.rivers:
        s = next(
            (
                s
                for s in manifest.get("stations", [])
                if s["station"] == gauge.station and s["provider"] == gauge.provider
            ),
            None,
        )
        features = [f for p in s["paths"] for f in read_json(p)["features"]] if s else []
        if len(features) > 1:
            raise ValueError(f"Duplicate daily discharge {gauge.station}")
        value, qc, basis = (
            discharge_value(features[0], gauge.provider, gauge.station, manifest["date"])
            if features
            else (np.nan, "unavailable", "provider daily date")
        )
        coords = features[0]["geometry"]["coordinates"] if features else [None, None]
        rows.append(
            {
                **gauge.model_dump(),
                "DATE": manifest["date"],
                "DISCHARGE_M3_S": value,
                "SOURCE_QC": qc,
                "DATE_BASIS": basis,
                "gauge_lon": coords[0],
                "gauge_lat": coords[1],
            }
        )
    return pd.DataFrame(rows)


def influence_frame(doc, cfg, family, manifest, spatial_cache):
    if family == "tides":
        stations = normalize_tides(manifest, cfg.min_tide_samples)
        # Inventory supplies coordinates even if a station's daily request failed.
        seeds = []
        inventories = [read_json(p) for p in manifest.get("metadata_paths", [])]
        for spec in cfg.tides:
            if spec.provider == "CHS":
                match = next(
                    (
                        s
                        for inv in inventories
                        if isinstance(inv, list)
                        for s in inv
                        if s["code"] == spec.station
                    ),
                    None,
                )
                if match:
                    seeds.append(
                        {
                            "station": spec.station,
                            "provider": spec.provider,
                            "lon": match["longitude"],
                            "lat": match["latitude"],
                            "name": match["officialName"],
                        }
                    )
            else:
                match = next(
                    (
                        s
                        for inv in inventories
                        if isinstance(inv, dict)
                        for s in inv.get("stations", [])
                        if s["id"] == spec.station
                    ),
                    None,
                )
                if match:
                    seeds.append(
                        {
                            "station": spec.station,
                            "provider": spec.provider,
                            "lon": match["lng"],
                            "lat": match["lat"],
                            "name": match["name"],
                        }
                    )
        if len(seeds) != len(cfg.tides):
            raise ValueError(
                "Incomplete tide station inventory; influence roster cannot change silently"
            )
        valuecol = "TIDE_HOURLY_RANGE_M"
        scales = cfg.tide_decay_km
        prefix = "TIDE_RANGE_PROXY_M"
    else:
        stations = normalize_rivers(manifest, cfg)
        seeds = [
            {
                "station": g.station,
                "provider": g.provider,
                "name": g.name,
                "lon": g.mouth_lon,
                "lat": g.mouth_lat,
                "kind": "river_mouth",
            }
            for g in cfg.rivers
        ]
        valuecol = "DISCHARGE_M3_S"
        scales = cfg.river_decay_km
        prefix = "RIVER_DISCHARGE_INFLUENCE_M3_S"
    key = json.dumps(seeds, sort_keys=True)
    if key not in spatial_cache:
        spatial_cache[key] = water_distances(doc, cfg, seeds)
    support, distances, audit = spatial_cache[key]
    # An unmapped configured source could affect nearby waters; keep that limitation in the manifest.
    values = []
    for seed in seeds:
        match = (
            stations.loc[
                (stations.station == seed["station"]) & (stations.provider == seed["provider"])
            ]
            if len(stations)
            else pd.DataFrame()
        )
        values.append(match.iloc[0][valuecol] if len(match) else np.nan)
    frame = support[["H3_INDEX", "WATER_AREA_M2"]].copy()
    for scale in scales:
        suffix = f"{scale:g}KM"
        value, expected, observed, fraction, nearest = kernel_features(
            distances, values, scale, cfg.kernel_cutoff_multiples, normalize=family == "tides"
        )
        frame[f"{prefix}_{suffix}"] = value
        frame[f"EXPECTED_SOURCES_{suffix}"] = expected
        frame[f"AVAILABLE_SOURCES_{suffix}"] = observed
        frame[f"SOURCE_COMPLETENESS_{suffix}"] = fraction
        frame[f"NEAREST_SOURCE_WATER_KM_{suffix}"] = nearest
    # Influence is evaluated on the fine water graph, then water-area aggregated.
    # Cells with less than half of their marine area supported remain unavailable.
    frame["PARENT"] = frame.H3_INDEX.map(lambda h: h3.cell_to_parent(h, 6))
    grouped = []
    for parent, group in frame.groupby("PARENT"):
        row = {"H3_INDEX": parent, "WATER_AREA_M2": group.WATER_AREA_M2.sum()}
        for scale in scales:
            suffix = f"{scale:g}KM"
            col = f"{prefix}_{suffix}"
            good = group[col].notna()
            area = group.loc[good, "WATER_AREA_M2"].sum()
            fraction = area / row["WATER_AREA_M2"] if row["WATER_AREA_M2"] > 0 else 0
            missing_source = (
                group[f"AVAILABLE_SOURCES_{suffix}"] < group[f"EXPECTED_SOURCES_{suffix}"]
            ).any()
            row[col] = (
                float(np.average(group.loc[good, col], weights=group.loc[good, "WATER_AREA_M2"]))
                if fraction >= 0.5 and not missing_source
                else np.nan
            )
            row[f"SUPPORTED_WATER_FRACTION_{suffix}"] = fraction
            for name in [
                "EXPECTED_SOURCES",
                "AVAILABLE_SOURCES",
                "SOURCE_COMPLETENESS",
                "NEAREST_SOURCE_WATER_KM",
            ]:
                c = f"{name}_{suffix}"
                valid = group[c].notna() & (group.WATER_AREA_M2 > 0)
                row[f"MEAN_{c}"] = (
                    float(
                        np.average(group.loc[valid, c], weights=group.loc[valid, "WATER_AREA_M2"])
                    )
                    if valid.any()
                    else np.nan
                )
        grouped.append(row)
    frame = pd.DataFrame(grouped)
    canonical = support_at(doc, cfg, 6)
    frame = canonical.merge(
        frame.drop(columns="WATER_AREA_M2"), on="H3_INDEX", how="left", validate="one_to_one"
    )
    frame["H3_RESOLUTION"] = 6
    return (
        frame,
        {
            "fine_graph_resolution": 8,
            "output_resolution": 6,
            "minimum_supported_water_fraction": 0.5,
            "spatial_aggregation": "R8 water-path kernels averaged by child water area to R6; any missing expected gauge invalidates the parent",
            "seed_audit": audit,
            "interpretation": "Uncalibrated water-path influence candidates; distances require sensitivity testing. No across-land KDE.",
            "kernel": "exp(-water_distance_km/scale_km), truncated at configured multiple",
            "normalized_weights": family == "tides",
            "date_basis": (
                "UTC hourly prediction range"
                if family == "tides"
                else "provider daily dates; Canadian and US daily intervals are not asserted identical UTC windows"
            ),
            "limitations": (
                "Tide range is interpolated, not phase/current/absolute height."
                if family == "tides"
                else "Upstream gauge flow is not mouth discharge; no tributary correction, distributary split, travel-time lag, advection, salinity or plume boundary inference."
            ),
        },
        stations,
    )


def build(config=DEFAULT_CONFIG, start=None, end=None, families=FAMILIES):
    doc, cfg = load(config)
    spatial_cache = {}
    results = []
    provenance_paths = [
        Path(__file__).parent / n
        for n in [
            "build.py",
            "download.py",
            "spatial.py",
            "config.py",
            "composite.py",
            "regional_sources.py",
        ]
    ]
    root = doc.resolve_path(cfg.support_dir)
    provenance_paths += [
        root / n
        for n in [
            "h3_geometry/H3_MODEL_AREA_SUPPORT_RES_6.parquet",
            "h3_geometry/H3_MODEL_AREA_SUPPORT_RES_8.parquet",
            "water_network/H3_WATER_PASSABLE_EDGES_RES_8.parquet",
            "water_geometry/TERRITORIAL_WATER_POLYGON.parquet",
        ]
    ]
    lineage_checksums = {str(p): digest(p) for p in provenance_paths}
    if not start or not end or pd.Timestamp(end) < pd.Timestamp(start):
        raise ValueError("Provide an ordered date interval")
    history_start = pd.Timestamp(start) - pd.Timedelta(
        days=cfg.productivity_window_days - 1 if "productivity" in families else 0
    )
    for date in pd.date_range(history_start, end):
        day = date.strftime("%Y-%m-%d")
        for family in families:
            if date < pd.Timestamp(start) and family != "productivity":
                continue
            print("BUILD", family, day, flush=True)
            raw = doc.resolve_path(cfg.raw_dir) / family / day / "MANIFEST.json"
            manifest = json.loads(raw.read_text())
            if manifest.get("resolved_bbox") != cfg.bbox:
                raise ValueError("Collection area changed; recollect before building")
            if manifest["config_hash"] != doc.config_hash:
                raise ValueError(
                    "Collection configuration changed; recollect (verified byte caches remain reusable)"
                )
            out = doc.resolve_path(cfg.processed_dir) / family / day
            out.mkdir(parents=True, exist_ok=True)
            for old in ["STATIONS.parquet", "LAYER.parquet"]:
                if (out / old).exists():
                    (out / old).unlink()
            try:
                if manifest["status"] == "unavailable":
                    raise ValueError(manifest["error"])
                stations = None
                if family in cfg.satellites:
                    frame, info = satellite_frame(doc, cfg, family, manifest, out)
                elif family == "currents":
                    frame, info = currents_frame(doc, cfg, manifest, out)
                elif family in ("offshore_currents", "tidal_model"):
                    from .regional_sources import regional_frame

                    frame, info = regional_frame(doc, cfg, family, manifest, out, spatial_cache)
                else:
                    frame, info, stations = influence_frame(
                        doc, cfg, family, manifest, spatial_cache
                    )
                if stations is not None:
                    stations.to_parquet(out / "STATIONS.parquet", index=False)
                status = "built"
            except (ValueError, KeyError, OSError) as exc:
                resolution = (
                    cfg.satellites[family].resolution
                    if family in cfg.satellites
                    else (5 if family == "offshore_currents" else 6)
                )
                frame = support_at(doc, cfg, resolution)
                frame["H3_RESOLUTION"] = resolution
                info = {"error": str(exc)}
                status = "unavailable"
            frame["DATE"] = day
            frame["AVAILABILITY_MODE"] = "retrospective_research"
            frame["AVAILABLE_AT_UTC"] = pd.NaT
            metrics = [
                c
                for c in frame
                if c.startswith(
                    (
                        "SST_",
                        "CHLOROPHYLL_",
                        "CURRENT_SPEED_",
                        "TIDE_RANGE_",
                        "RIVER_DISCHARGE_",
                        "OFFSHORE_CURRENT_",
                        "HARMONIC_TIDE_",
                    )
                )
                and not c.endswith("_VALID_PIXELS")
            ]
            frame["FEATURE_STATUS"] = (
                np.where(frame[metrics].notna().any(axis=1), "available", "unavailable")
                if metrics
                else "unavailable"
            )
            path = out / "FEATURES.parquet"
            tmp = out / "FEATURES.tmp.parquet"
            frame.to_parquet(tmp, index=False)
            tmp.replace(path)
            coverage = {
                col: {
                    "valid_cells": int(frame[col].notna().sum()),
                    "total_cells": len(frame),
                    "valid_water_area_fraction": float(
                        frame.loc[frame[col].notna(), "WATER_AREA_M2"].sum()
                        / frame.WATER_AREA_M2.sum()
                    ),
                }
                for col in metrics
            }
            result = {
                "family": family,
                "date": day,
                "status": status,
                "config_hash": doc.config_hash,
                "lineage_checksums": lineage_checksums,
                "source_manifest": str(raw),
                "source_manifest_sha256": digest(raw),
                "feature_path": str(path),
                "feature_sha256": digest(path),
                "model_columns": metrics,
                "coverage": coverage,
                "source_errors": manifest.get("errors", []),
                "forecast_eligible": False,
                "availability_note": "Source retrieval timestamps retained; historical issue-time availability has not been established.",
                **info,
            }
            result["processed_layers"] = {
                str(out / n): digest(out / n)
                for n in ["LAYER.parquet", "STATIONS.parquet"]
                if (out / n).exists()
            }
            write_json(out / "MANIFEST.json", result)
            results.append(result)
    if "productivity" in families:
        from .composite import append_composites

        updated = {m["date"]: m for m in append_composites(doc, cfg, start, end)}
        results = [
            updated.get(m["date"], m) if m["family"] == "productivity" else m for m in results
        ]
    return results
