"""Shared validation and H3 aggregation helpers for oceanographic sources."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import h3
import numpy as np
import pandas as pd


def _digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def verified(path: str | Path) -> Path:
    """Return a raw artifact after checking its adjacent acquisition manifest."""
    path = Path(path)
    metadata = path.with_name(path.stem + ".manifest.json")
    manifest = json.loads(metadata.read_text())
    if _digest(path) != manifest["sha256"]:
        raise ValueError(f"Raw checksum mismatch: {path}")
    return path


def read_json(path: str | Path):
    """Read checksum-verified JSON."""
    return json.loads(verified(path).read_text())


def support_at(document, config, resolution: int) -> pd.DataFrame:
    """Load the canonical marine support at R6 or aggregate it to R5."""
    support = pd.read_parquet(
        document.resolve_path(config.support_dir)
        / "h3_geometry/H3_MODEL_AREA_SUPPORT_RES_6.parquet"
    )
    support = support.loc[support.HAS_WATER_OVERLAP.astype(bool)].copy()
    if resolution == 5:
        support["H3_INDEX"] = support.H3_INDEX.map(lambda cell: h3.cell_to_parent(cell, 5))
        support = support.groupby("H3_INDEX", as_index=False).agg(
            WATER_AREA_M2=("WATER_AREA_M2", "sum")
        )
    return support[["H3_INDEX", "WATER_AREA_M2"]].sort_values("H3_INDEX").reset_index(drop=True)


def validate_times(dataset, day: str, expected: int | None = None) -> None:
    """Reject empty, duplicated, off-date, or incomplete source time axes."""
    times = pd.DatetimeIndex(dataset.time.values)
    if len(times) == 0 or not (times.strftime("%Y-%m-%d") == day).all() or times.has_duplicates:
        raise ValueError(f"Unexpected or duplicated source time for {day}: {times}")
    if expected is not None and len(times) != expected:
        raise ValueError(f"Expected {expected} time samples; received {len(times)}")


def aggregate_pixels(lat, lon, metrics, support, resolution: int) -> pd.DataFrame:
    """Area-weighted sample means on a regular lat/lon grid; no nearest-cell filling."""
    lat, lon = np.asarray(lat).ravel(), np.asarray(lon).ravel()
    cells = [h3.latlng_to_cell(float(a), float(b), resolution) for a, b in zip(lat, lon)]
    frame = pd.DataFrame({"H3_INDEX": cells, "weight": np.cos(np.deg2rad(lat))})
    for key, value in metrics.items():
        frame[key] = np.asarray(value).ravel()
    frame = frame.loc[frame.H3_INDEX.isin(support.H3_INDEX)].copy()
    rows = []
    for cell, group in frame.groupby("H3_INDEX"):
        row = {"H3_INDEX": cell, "INPUT_PIXEL_COUNT": len(group)}
        for key in metrics:
            good = np.isfinite(group[key])
            row[key] = (
                float(np.average(group.loc[good, key], weights=group.loc[good, "weight"]))
                if good.any()
                else np.nan
            )
            row[key + "_VALID_PIXELS"] = int(good.sum())
        rows.append(row)
    if not rows:
        result = support.copy()
        result["INPUT_PIXEL_COUNT"] = 0
        for key in metrics:
            result[key] = np.nan
            result[key + "_VALID_PIXELS"] = 0
        return result
    result = support.merge(pd.DataFrame(rows), on="H3_INDEX", how="left", validate="one_to_one")
    for column in ["INPUT_PIXEL_COUNT"] + [key + "_VALID_PIXELS" for key in metrics]:
        result[column] = result[column].fillna(0).astype(int)
    return result
