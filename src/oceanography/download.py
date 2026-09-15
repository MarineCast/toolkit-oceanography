"""Bounded daily public-source collection with content-verified, request-addressed caches."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import DEFAULT_CONFIG, load

FAMILIES = (
    "tides",
    "currents",
    "river_discharge",
    "ocean_temperature",
    "productivity",
    "offshore_currents",
    "tidal_model",
)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, default=str, allow_nan=False))
    tmp.replace(path)


class Cache:
    def __init__(self, root, offline=False):
        self.root = Path(root)
        self.offline = offline
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "MarineCast-oceanography-research/0.1"
        self.session.mount(
            "https://",
            HTTPAdapter(
                max_retries=Retry(
                    total=2, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504]
                )
            ),
        )

    def get(self, url, params=None, suffix=".json"):
        url = requests.Request("GET", url, params=params).prepare().url
        key = hashlib.sha256(url.encode()).hexdigest()
        path = self.root / (key + suffix)
        meta = self.root / (key + ".manifest.json")
        if path.exists() or meta.exists():
            if not path.exists() or not meta.exists():
                raise ValueError(f"Incomplete cache: {path}")
            m = json.loads(meta.read_text())
            if m["url"] != url or digest(path) != m["sha256"]:
                raise ValueError(f"Cache identity/checksum mismatch: {path}")
            return path
        if self.offline:
            raise FileNotFoundError(f"Not cached: {url}")
        print("GET", url[:160], flush=True)
        response = self.session.get(url, timeout=(15, 90))
        response.raise_for_status()
        if suffix == ".json":
            response.json()  # reject HTML error pages before publication
        elif suffix == ".nc" and not response.content.startswith((b"CDF", b"\x89HDF")):
            raise ValueError(f"Expected NetCDF: {response.text[:200]}")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".partial")
        tmp.write_bytes(response.content)
        tmp.replace(path)
        write_json(
            meta,
            {
                "url": url,
                "sha256": digest(path),
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "bytes": path.stat().st_size,
            },
        )
        return path

    def json(self, url, params=None):
        path = self.get(url, params)
        return json.loads(path.read_text()), str(path)

    def pages(self, url, params):
        features, paths = [], []
        seen = set()
        while url:
            if url in seen:
                raise ValueError("Pagination loop")
            seen.add(url)
            result, path = self.json(url, params)
            if "features" not in result:
                raise ValueError("Expected OGC FeatureCollection")
            features.extend(result["features"])
            paths.append(path)
            url = next((x["href"] for x in result.get("links", []) if x["rel"] == "next"), None)
            params = None
        return features, paths


def metadata(cache, base, dataset):
    data, path = cache.json(f"{base}/info/{dataset}/index.json")
    rows = data["table"]["rows"]
    attrs = {(r[1], r[2]): r[4] for r in rows if r[0] == "attribute"}
    return attrs, path


def check_date(attrs, day):
    lo = pd.Timestamp(attrs["NC_GLOBAL", "time_coverage_start"]).date()
    hi = pd.Timestamp(attrs["NC_GLOBAL", "time_coverage_end"]).date()
    if not lo <= pd.Timestamp(day).date() <= hi:
        raise ValueError(
            f"Requested {day} outside archive {lo}..{hi}; no nearest-date substitution"
        )


def collect_satellite(cache, cfg, family, day):
    s = cfg.satellites[family]
    attrs, meta = metadata(cache, cfg.satellite_base, s.dataset)
    check_date(attrs, day)
    if attrs[s.variable, "units"] != s.units:
        raise ValueError("Unexpected satellite units")
    bbox = cfg.bbox
    # These pinned datasets use north-to-south latitude and -180..180 longitude.
    # Coordinate direction and returned timestamps are verified again in the builder.
    t = f"[({day}T12:00:00Z)]" + ("[0]" if s.altitude else "")
    t += f"[({bbox['max_lat']}):1:({bbox['min_lat']})][({bbox['min_lon']}):1:({bbox['max_lon']})]"
    variables = [s.variable] + ([s.quality_variable] if s.quality_variable else [])
    path = cache.get(
        f"{cfg.satellite_base}/griddap/{s.dataset}.nc?" + ",".join(v + t for v in variables),
        suffix=".nc",
    )
    return {"paths": [str(path)], "metadata_paths": [meta], "dataset": s.dataset}


def collect_currents(cache, cfg, day):
    paths, metas = [], []
    for dataset, variable in [
        (cfg.current_u_dataset, "uVelocity"),
        (cfg.current_v_dataset, "vVelocity"),
    ]:
        attrs, meta = metadata(cache, cfg.salish_base, dataset)
        check_date(attrs, day)
        if attrs[variable, "units"] != "m s-1":
            raise ValueError("Unexpected velocity units")
        query = f"{variable}[({day}T00:30:00Z):{cfg.current_interval_hours}:({day}T23:30:00Z)][0][0:1:897][0:1:397]"
        paths.append(
            str(cache.get(f"{cfg.salish_base}/griddap/{dataset}.nc?{query}", suffix=".nc"))
        )
        metas.append(meta)
    geometry = cache.get(
        f"{cfg.salish_base}/griddap/{cfg.current_geometry_dataset}.nc?latitude[0:1:897][0:1:397],longitude[0:1:897][0:1:397],bathymetry[0:1:897][0:1:397]",
        suffix=".nc",
    )
    return {"paths": paths, "metadata_paths": metas, "geometry_path": str(geometry)}


def collect_tides(cache, cfg, day):
    records, errors, inventory_paths = [], [], []
    chs, p = cache.json("https://api-sine.dfo-mpo.gc.ca/api/v1/stations")
    inventory_paths.append(p)
    noaa, p = cache.json(
        "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json",
        {"type": "tidepredictions"},
    )
    inventory_paths.append(p)
    end = (pd.Timestamp(day) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    for station in cfg.tides:
        try:
            if station.provider == "CHS":
                s = next(s for s in chs if s["code"] == station.station)
                data, path = cache.json(
                    f"https://api-sine.dfo-mpo.gc.ca/api/v1/stations/{s['id']}/data",
                    {
                        "time-series-code": "wlp",
                        "from": day + "T00:00:00Z",
                        "to": end + "T00:00:00Z",
                        "resolution": "SIXTY_MINUTES",
                    },
                )
                if not isinstance(data, list):
                    raise ValueError(str(data)[:300])
                info = {
                    "lat": s["latitude"],
                    "lon": s["longitude"],
                    "name": s["officialName"],
                    "datum": "CHS chart datum (station-specific)",
                }
            else:
                s = next(s for s in noaa["stations"] if s["id"] == station.station)
                data, path = cache.json(
                    "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter",
                    {
                        "product": "predictions",
                        "station": station.station,
                        "begin_date": day.replace("-", ""),
                        "end_date": day.replace("-", ""),
                        "datum": "MLLW",
                        "time_zone": "gmt",
                        "interval": "h",
                        "units": "metric",
                        "format": "json",
                        "application": "OrcaCast",
                    },
                )
                if "predictions" not in data:
                    raise ValueError(str(data)[:300])
                info = {"lat": s["lat"], "lon": s["lng"], "name": s["name"], "datum": "MLLW"}
            records.append({**station.model_dump(), **info, "path": path})
        except (requests.RequestException, ValueError, StopIteration, FileNotFoundError) as exc:
            errors.append(
                {
                    "station": station.station,
                    "provider": station.provider,
                    "error": str(exc) or "Station not in inventory",
                }
            )
    return {"stations": records, "errors": errors, "metadata_paths": inventory_paths}


def collect_rivers(cache, cfg, day):
    records, errors = [], []
    for gauge in cfg.rivers:
        try:
            if gauge.provider == "ECCC":
                url = "https://api.weather.gc.ca/collections/hydrometric-daily-mean/items"
                params = {
                    "f": "json",
                    "STATION_NUMBER": gauge.station,
                    "datetime": day + "/" + day,
                    "limit": 1000,
                }
            else:
                url = "https://api.waterdata.usgs.gov/ogcapi/v0/collections/daily/items"
                params = {
                    "f": "json",
                    "monitoring_location_id": gauge.station,
                    "parameter_code": "00060",
                    "statistic_id": "00003",
                    "datetime": day + "/" + day,
                    "limit": 1000,
                }
            data, paths = cache.pages(url, params)
            records.append({**gauge.model_dump(), "paths": paths, "record_count": len(data)})
        except (requests.RequestException, ValueError, FileNotFoundError) as exc:
            errors.append({"station": gauge.station, "provider": gauge.provider, "error": str(exc)})
    return {"stations": records, "errors": errors}


def collect(
    config=DEFAULT_CONFIG, start=None, end=None, families=FAMILIES, offline=False, refresh=False
):
    doc, cfg = load(config)
    if not start or not end or pd.Timestamp(end) < pd.Timestamp(start):
        raise ValueError("Provide an explicit ordered --start and --end date")
    if refresh and offline:
        raise ValueError("--refresh and --offline are incompatible")
    cache_root = doc.resolve_path(cfg.raw_dir) / "requests"
    if refresh:
        cache_root = cache_root / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    cache = Cache(cache_root, offline)
    manifests = []
    history_start = pd.Timestamp(start) - pd.Timedelta(
        days=cfg.productivity_window_days - 1 if "productivity" in families else 0
    )
    for date in pd.date_range(history_start, end):
        day = date.strftime("%Y-%m-%d")
        for family in families:
            if date < pd.Timestamp(start) and family != "productivity":
                continue
            print("COLLECT", family, day, flush=True)
            try:
                if family in cfg.satellites:
                    result = collect_satellite(cache, cfg, family, day)
                elif family == "currents":
                    result = collect_currents(cache, cfg, day)
                elif family == "tides":
                    result = collect_tides(cache, cfg, day)
                elif family == "river_discharge":
                    result = collect_rivers(cache, cfg, day)
                elif family in ("offshore_currents", "tidal_model"):
                    from .regional_sources import collect_regional

                    result = collect_regional(cache, cfg, family, day)
                else:
                    raise ValueError(f"Unknown family {family}")
                status = "partial" if result.get("errors") else "collected"
            except (requests.RequestException, ValueError, FileNotFoundError, KeyError) as exc:
                result = {"error": str(exc)}
                status = "unavailable"
            manifest = {
                "family": family,
                "date": day,
                "config_hash": doc.config_hash,
                "resolved_bbox": cfg.bbox,
                "status": status,
                **result,
            }
            path = doc.resolve_path(cfg.raw_dir) / family / day / "MANIFEST.json"
            write_json(path, manifest)
            manifests.append(manifest)
    return manifests
