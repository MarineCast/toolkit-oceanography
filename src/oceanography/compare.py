"""Cross-source checks for the broader-coverage research candidates."""

import json
from pathlib import Path

import h3
import numpy as np
import pandas as pd

from .config import DEFAULT_CONFIG, load
from .download import digest, write_json
from .normalization import read_json, verified
from .regional_sources import interpolate_harmonics, load_tide_mesh, predict_tide


def compare(config=DEFAULT_CONFIG, start=None, end=None):
    doc, cfg = load(config)
    root = doc.resolve_path(cfg.processed_dir)
    raw = doc.resolve_path(cfg.raw_dir)
    out = doc.resolve_path(cfg.report_dir) / f"{start}_{end}"
    out.mkdir(parents=True, exist_ok=True)
    first = json.loads((raw / "tidal_model" / str(start) / "MANIFEST.json").read_text())
    mesh = load_tide_mesh(verified(first["paths"][0]))
    tides = []
    currents = []
    coverage = []
    for date in pd.date_range(start, end):
        day = date.strftime("%Y-%m-%d")
        manifest = json.loads((raw / "tides" / day / "MANIFEST.json").read_text())
        stations = manifest["stations"]
        coeff, tri = interpolate_harmonics(
            *mesh[:3],
            np.array([s["lon"] for s in stations]),
            np.array([s["lat"] for s in stations]),
        )
        times = pd.date_range(day, periods=24, freq="h", tz="UTC")
        predictions = predict_tide(
            times.tz_localize(None), [s["lat"] for s in stations], coeff, mesh[3]
        )
        for i, s in enumerate(stations):
            row = {
                "date": day,
                "station": s["station"],
                "name": s["name"],
                "provider": s["provider"],
                "triangle_index": int(tri[i]),
                "reference": "agency astronomical prediction, not observed water level",
            }
            if tri[i] < 0:
                row["status"] = "outside_or_ambiguous_native_mesh"
                tides.append(row)
                continue
            records = read_json(s["path"])
            records = records if s["provider"] == "CHS" else records["predictions"]
            ts = pd.to_datetime(
                [r["eventDate"] if s["provider"] == "CHS" else r["t"] for r in records], utc=True
            )
            values = [float(r["value"] if s["provider"] == "CHS" else r["v"]) for r in records]
            observed = pd.Series(values, index=ts).reindex(times).to_numpy()
            predicted = predictions[i]
            if not np.isfinite(observed).all():
                row["status"] = "reference_incomplete"
                tides.append(row)
                continue
            residual = (observed - observed.mean()) - (predicted - predicted.mean())
            row.update(
                status="compared",
                correlation=float(np.corrcoef(observed, predicted)[0, 1]),
                demeaned_rmse_m=float(np.sqrt(np.mean(residual**2))),
                range_error_m=float(np.ptp(predicted) - np.ptp(observed)),
            )
            tides.append(row)

        def frame(family):
            m = json.loads((root / family / day / "MANIFEST.json").read_text())
            p = root / family / day / "FEATURES.parquet"
            if digest(p) != m["feature_sha256"]:
                raise ValueError("Comparison input checksum mismatch")
            coverage.append({"family": family, "date": day, "coverage": m["coverage"]})
            return pd.read_parquet(p)

        region = frame("currents")
        offshore = frame("offshore_currents")
        frame("tidal_model")
        frame("productivity")
        frame("tides")
        region["PARENT"] = region.H3_INDEX.map(lambda c: h3.cell_to_parent(c, 5))
        means = []
        for parent, g in region.groupby("PARENT"):
            valid = g.CURRENT_SPEED_SAMPLE_MEAN_MS.notna()
            fraction = g.loc[valid, "WATER_AREA_M2"].sum() / g.WATER_AREA_M2.sum()
            means.append(
                {
                    "H3_INDEX": parent,
                    "REGIONAL_MS": (
                        float(
                            np.average(
                                g.loc[valid, "CURRENT_SPEED_SAMPLE_MEAN_MS"],
                                weights=g.loc[valid, "WATER_AREA_M2"],
                            )
                        )
                        if fraction >= 0.5
                        else np.nan
                    ),
                }
            )
        joined = (
            pd.DataFrame(means)
            .merge(offshore[["H3_INDEX", "OFFSHORE_CURRENT_SPEED_SAMPLE_MEAN_MS"]], on="H3_INDEX")
            .dropna()
        )
        residual = joined.OFFSHORE_CURRENT_SPEED_SAMPLE_MEAN_MS - joined.REGIONAL_MS
        currents.append(
            {
                "date": day,
                "overlap_r5_cells": len(joined),
                "regional_mean_ms": float(joined.REGIONAL_MS.mean()) if len(joined) else None,
                "offshore_mean_ms": (
                    float(joined.OFFSHORE_CURRENT_SPEED_SAMPLE_MEAN_MS.mean())
                    if len(joined)
                    else None
                ),
                "mean_absolute_difference_ms": float(abs(residual).mean()) if len(joined) else None,
                "interpretation": "Descriptive overlap only: different models, native scales and hourly-mean versus instantaneous sampling. No automatic blending.",
            }
        )
    # Report complementary footprints without manufacturing a merged velocity field.
    complementary = []
    for date in pd.date_range(start, end):
        day = date.strftime("%Y-%m-%d")
        for fine, coarse, fcol, ccol in [
            (
                "currents",
                "offshore_currents",
                "CURRENT_SPEED_SAMPLE_MEAN_MS",
                "OFFSHORE_CURRENT_SPEED_SAMPLE_MEAN_MS",
            ),
            ("tides", "tidal_model", "TIDE_RANGE_PROXY_M_40KM", "HARMONIC_TIDE_HOURLY_RANGE_M"),
        ]:
            a = pd.read_parquet(root / fine / day / "FEATURES.parquet")
            b = pd.read_parquet(root / coarse / day / "FEATURES.parquet").set_index("H3_INDEX")
            keys = (
                a.H3_INDEX.map(lambda h: h3.cell_to_parent(h, 5))
                if coarse == "offshore_currents"
                else a.H3_INDEX
            )
            broader = keys.map(b[ccol]).notna()
            original = a[fcol].notna()
            total = a.WATER_AREA_M2.sum()
            complementary.append(
                {
                    "family": fine,
                    "date": day,
                    "original_water_fraction": float(
                        a.loc[original, "WATER_AREA_M2"].sum() / total
                    ),
                    "broader_water_fraction_on_r6_support": float(
                        a.loc[broader, "WATER_AREA_M2"].sum() / total
                    ),
                    "either_source_water_fraction": float(
                        a.loc[original | broader, "WATER_AREA_M2"].sum() / total
                    ),
                    "meaning": "Cell support under either source; not a merged feature or proof of fine-scale observation.",
                }
            )
    data = {
        "complementary_coverage": complementary,
        "config_hash": doc.config_hash,
        "comparison_code_sha256": digest(Path(__file__)),
        "tide_checks": tides,
        "current_overlap": currents,
        "coverage": coverage,
        "automatic_blending": False,
        "limitations": [
            "Seven-day pilot, not independent long-term skill validation.",
            "Agency tide predictions may share historical harmonic information with the regional model.",
            "Only stations inside native model triangles are compared; no station snapping used for validation.",
        ],
    }
    write_json(out / "SOURCE_COMPARISON.json", data)
    return data
