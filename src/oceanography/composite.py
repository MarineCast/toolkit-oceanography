"""Trailing daily-cell chlorophyll composites with explicit age and sample support."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .download import digest, write_json

MEAN = "CHLOROPHYLL_TRAILING_7D_MEAN_MG_M3"
LOG = "CHLOROPHYLL_TRAILING_7D_LOG_MEAN"
SUPPORTED = "CHLOROPHYLL_TRAILING_7D_2PLUS_MEAN_MG_M3"


def trailing_cell_features(daily, target, cells, minimum=2, window=7):
    """Equal-weight mean of daily cell means; ignore future rows and preserve gaps.

    Daily valid pixels may differ. This is a temporal composite of daily H3
    summaries, not a fixed-pixel reconstruction or an instantaneous observation.
    """
    target = pd.Timestamp(target).normalize()
    dates = pd.date_range(target - pd.Timedelta(days=window - 1), target)
    panel = np.full((window, len(cells)), np.nan)
    for i, date in enumerate(dates):
        values = daily.get(date.strftime("%Y-%m-%d"))
        if values is not None:
            panel[i] = values.reindex(cells).to_numpy(dtype=float)
    good = np.isfinite(panel) & (panel > 0)
    counts = good.sum(axis=0)
    means = np.divide(
        np.where(good, panel, 0).sum(axis=0),
        counts,
        out=np.full(len(cells), np.nan),
        where=counts > 0,
    )
    supported = np.where(counts >= 2, means, np.nan)
    means = np.where(counts >= minimum, means, np.nan)
    age = np.arange(window - 1, -1, -1)[:, None]
    newest = np.min(np.where(good, age, np.inf), axis=0)
    oldest = np.max(np.where(good, age, -np.inf), axis=0)
    newest[~np.isfinite(newest)] = np.nan
    oldest[~np.isfinite(oldest)] = np.nan
    return pd.DataFrame(
        {
            "H3_INDEX": cells,
            MEAN: means,
            LOG: np.log(means),
            SUPPORTED: supported,
            "COMPOSITE_VALID_DAYS": counts,
            "COMPOSITE_NEWEST_AGE_DAYS": newest,
            "COMPOSITE_OLDEST_AGE_DAYS": oldest,
            "COMPOSITE_WINDOW_DAYS": window,
        }
    )


def append_composites(doc, cfg, start, end):
    root = doc.resolve_path(cfg.processed_dir) / "productivity"
    updated = []
    for target in pd.date_range(start, end):
        day = target.strftime("%Y-%m-%d")
        out = root / day
        manifest = json.loads((out / "MANIFEST.json").read_text())
        frame = pd.read_parquet(out / "FEATURES.parquet")
        daily, lineage, missing = {}, {}, []
        for date in pd.date_range(
            target - pd.Timedelta(days=cfg.productivity_window_days - 1), target
        ):
            datekey = date.strftime("%Y-%m-%d")
            path = root / datekey / "FEATURES.parquet"
            mp = root / datekey / "MANIFEST.json"
            if not path.exists() or not mp.exists():
                missing.append(datekey)
                continue
            meta = json.loads(mp.read_text())
            if meta["config_hash"] != doc.config_hash:
                raise ValueError("Composite history configuration mismatch")
            if digest(path) != meta["feature_sha256"]:
                raise ValueError("Composite input checksum mismatch")
            data = pd.read_parquet(path).set_index("H3_INDEX")
            if "CHLOROPHYLL_MEAN_MG_M3" not in data:
                missing.append(datekey)
                continue
            daily[datekey] = data.CHLOROPHYLL_MEAN_MG_M3
            # Immutable normalized input lineage remains valid after derived columns are added.
            lineage[datekey] = {
                "source_manifest_sha256": meta["source_manifest_sha256"],
                "processed_layers": meta["processed_layers"],
            }
        composite = trailing_cell_features(
            daily,
            day,
            frame.H3_INDEX.tolist(),
            cfg.productivity_min_valid_days,
            cfg.productivity_window_days,
        )
        frame = frame.drop(
            columns=[c for c in composite if c != "H3_INDEX"], errors="ignore"
        ).merge(composite, on="H3_INDEX", validate="one_to_one")
        frame["FEATURE_STATUS"] = (
            np.where(
                frame[["CHLOROPHYLL_MEAN_MG_M3", MEAN]].notna().any(axis=1),
                "available",
                "unavailable",
            )
            if "CHLOROPHYLL_MEAN_MG_M3" in frame
            else np.where(frame[MEAN].notna(), "available", "unavailable")
        )
        path = out / "FEATURES.parquet"
        temp = out / "FEATURES.tmp.parquet"
        frame.to_parquet(temp, index=False)
        temp.replace(path)
        for col in [MEAN, LOG, SUPPORTED]:
            if col not in manifest["model_columns"]:
                manifest["model_columns"].append(col)
            valid = frame[col].notna()
            manifest["coverage"][col] = {
                "valid_cells": int(valid.sum()),
                "total_cells": len(frame),
                "valid_water_area_fraction": float(
                    frame.loc[valid, "WATER_AREA_M2"].sum() / frame.WATER_AREA_M2.sum()
                ),
            }
        manifest["daily_status"] = manifest.get("daily_status", manifest["status"])
        if manifest["daily_status"] == "unavailable" and frame[MEAN].notna().any():
            manifest["status"] = "partial"
            manifest["interpretation"] = (
                "Trailing chlorophyll summary is available, but the selected-day satellite observation is unavailable. Inspect observation ages and counts."
            )
        manifest["feature_sha256"] = digest(path)
        manifest["trailing_composite"] = {
            "window_days": cfg.productivity_window_days,
            "minimum_valid_days": cfg.productivity_min_valid_days,
            "start_date": (target - pd.Timedelta(days=6)).strftime("%Y-%m-%d"),
            "end_date": day,
            "aggregation": "equal-weight mean of valid daily H3 cell means; log column is natural log of that mean",
            "missing_daily_partitions": missing,
            "input_lineage": lineage,
            "code_sha256": digest(Path(__file__)),
            "lookahead": False,
            "availability": "retrospective daily labels; historical publication timestamps remain unknown",
        }
        write_json(out / "MANIFEST.json", manifest)
        updated.append(manifest)
    return updated
