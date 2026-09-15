"""Interactive daily feature maps, source locations, and explicit coverage evidence."""

from __future__ import annotations

import html
import json
from pathlib import Path

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
from shapely.geometry import mapping

from .config import DEFAULT_CONFIG, load
from .download import FAMILIES, digest, write_json

TITLES = {
    "offshore_currents": "Offshore currents · HYCOM",
    "tidal_model": "Gridded tides · DFO",
    "tides": "Tidal range",
    "currents": "Surface currents",
    "river_discharge": "River influence",
    "ocean_temperature": "Ocean temperature",
    "productivity": "Productivity proxy",
}
SOURCES = {
    "offshore_currents": [
        ("HYCOM GOFS 3.1", "https://www.hycom.org/dataserver/gofs-3pt1/analysis")
    ],
    "tidal_model": [
        (
            "DFO Northeast Pacific tidal model",
            "https://www.bio.gc.ca/science/research-recherche/ocean/webtide/nepacific-nepacifique-en.php",
        )
    ],
    "tides": [
        (
            "Canadian Hydrographic Service",
            "https://www.tides.gc.ca/en/web-services-offered-canadian-hydrographic-service",
        ),
        ("NOAA CO-OPS", "https://api.tidesandcurrents.noaa.gov/api/dev"),
    ],
    "currents": [
        (
            "UBC SalishSeaCast",
            "https://salishsea.eos.ubc.ca/erddap/info/ubcSSg3DuGridFields1hV21-11/index.html",
        )
    ],
    "river_discharge": [
        (
            "ECCC HYDAT daily discharge",
            "https://api.weather.gc.ca/collections/hydrometric-daily-mean",
        ),
        ("USGS daily discharge", "https://api.waterdata.usgs.gov/docs/ogcapi/"),
    ],
    "ocean_temperature": [
        (
            "NOAA ACSPO reanalysis",
            "https://polarwatch.noaa.gov/erddap/info/noaacwLEOACSPOSSTL3SCDaily/index.html",
        )
    ],
    "productivity": [
        (
            "NOAA VIIRS science-quality chlorophyll",
            "https://polarwatch.noaa.gov/erddap/info/noaacwNPPVIIRSSQchlaDaily/index.html",
        )
    ],
}
PROBES = [
    ("BC — Strait of Georgia", 49.25, -123.65),
    ("BC — southern Vancouver Island", 48.39, -123.42),
    ("WA — central Puget Sound", 47.75, -122.46),
    ("WA — outer coast", 47.8, -124.75),
    ("Cross-border — Juan de Fuca", 48.25, -123.8),
]

STYLE = """body{margin:0;background:#edf2f5;color:#16303e;font:15px/1.5 system-ui}a{color:#176b86}h1{font-size:29px;line-height:1.15;margin:12px 0}h2{font-size:18px}p{margin:10px 0}.tag{font-size:11px;font-weight:700;letter-spacing:1.8px;color:#587383;text-transform:uppercase}aside{box-sizing:border-box;width:365px;padding:25px;height:100vh;overflow:auto;background:#fff;border-right:1px solid #cfdae0}#map{position:absolute;left:365px;right:0;top:0;bottom:0}select{display:block;width:100%;padding:10px;margin:5px 0 16px;border:1px solid #bacbd4;border-radius:6px;background:#fff;color:#173745}label{font-size:12px;font-weight:700}.notice{background:#fff5de;border-left:3px solid #d39d34;padding:12px;font-size:13px}.stat{font-size:25px;font-weight:650}.small,details{font-size:12px;color:#526c7a}details{margin-top:14px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:11px}.legend{height:12px;background:linear-gradient(90deg,#e0f2ef,#36a999,#174c75);border-radius:4px;margin-top:14px}.range{display:flex;justify-content:space-between;font-size:12px}.card{background:#fff;padding:24px;border:1px solid #d8e2e8;border-radius:12px}table{border-collapse:collapse;font-size:12px;width:100%}td,th{text-align:left;padding:6px;border-bottom:1px solid #e2e8ec}nav a{margin-right:10px}@media(max-width:700px){aside{width:100%;height:44vh;padding:16px}#map{left:0;top:44vh}h1{font-size:23px}}"""

TEMPLATE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>__TITLE__ | OrcaCast environmental research</title><link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"><style>__STYLE__</style></head><body><aside><a href="index.html">← Environmental data</a><div class="tag" style="margin-top:20px">OrcaCast · Research pilot</div><h1>__TITLE__</h1><p id="description"></p><label for="day">Date</label><select id="day"></select><label for="metric">Marine feature / influence distance</label><select id="metric"></select><label for="colorscale">Color scale</label><select id="colorscale"><option value="linear">Linear</option><option value="log">Logarithmic · log(1 + value)</option></select><p id="scalenote" class="small"></p><div class="stat" id="coverage"></div><div class="small">Marine cells with a value · gray cells are unavailable</div><div class="legend"></div><div class="range"><span id="low"></span><span id="high"></span></div><p id="watercoverage" class="small"></p><div class="notice" id="limitations"></div><p class="small">Click a cell for its value and support details. Source markers show gauges or tide stations; river-mouth seeds are separate purple markers. H3 boundaries are display units, not resolved physical boundaries.</p><h2>Source → model column</h2>__SOURCES__<pre id="lineage"></pre><details><summary>Processing and coverage metadata</summary><pre id="metadata"></pre></details><p class="small">Retrospective research only. Historical forecast-time availability is unverified. Basemap and Leaflet require an internet connection.</p></aside><div id="map"></div><script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script id="payload" type="application/json">__DATA__</script><script>
const data=JSON.parse(document.getElementById('payload').textContent), day=document.getElementById('day'), metric=document.getElementById('metric'), colorscale=document.getElementById('colorscale');colorscale.value=data.family==='river_discharge'?'log':'linear';
const map=L.map('map').setView([48.45,-123.6],7);L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',{attribution:'© OpenStreetMap contributors © CARTO',maxZoom:18}).addTo(map);map.fitBounds([[46.85,-125.8],[50,-121.6]]);
let layer, markers=L.layerGroup().addTo(map);const esc=x=>String(x).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const fmt=x=>x===null||x===undefined?'Unavailable':typeof x==='number'?Number(x.toPrecision(5)).toLocaleString():esc(x);
for(const d of Object.keys(data.days)){day.add(new Option(d,d))}for(const m of data.metrics){metric.add(new Option(m.replaceAll('_',' '),m))}const defaults={productivity:'CHLOROPHYLL_TRAILING_7D_MEAN_MG_M3',tides:'TIDE_RANGE_PROXY_M_40KM',river_discharge:'RIVER_DISCHARGE_INFLUENCE_M3_S_25KM',currents:'CURRENT_SPEED_SAMPLE_MEAN_MS'};if(data.metrics.includes(defaults[data.family]))metric.value=defaults[data.family];
function draw(){const key=metric.value,base=data.days[day.value],variant=data.metric_variant?.[key],d=variant?base.variants[variant]:base; const vals=d.rows.map(r=>r[key]).filter(v=>typeof v==='number'&&Number.isFinite(v)), allvals=Object.values(data.days).flatMap(x=>(variant?x.variants[variant]:x).rows.map(r=>r[key])).filter(v=>typeof v==='number'&&Number.isFinite(v)),lo=allvals.length?Math.min(...allvals):0,hi=allvals.length?Math.max(...allvals):1;
const useLog=colorscale.value==='log'&&lo>=0, transform=v=>useLog?Math.log1p(v):v;document.getElementById('scalenote').textContent=useLog?'Logarithmic colors reveal smaller values. Tooltips and legend endpoints retain original units.':colorscale.value==='log'?'Linear colors used because this metric includes negative values.':'Linear colors; the same range is used across all dates.';const color=v=>{if(v===null||v===undefined)return '#b9c4cc';let t=(transform(v)-transform(lo))/(transform(hi)-transform(lo)||1),a=t<.5?[224,242,239]:[54,169,153],b=t<.5?[54,169,153]:[23,76,117];t=t<.5?t*2:(t-.5)*2;return 'rgb('+a.map((x,i)=>Math.round(x+(b[i]-x)*t)).join(',')+')'};
if(layer)map.removeLayer(layer);const features=d.rows.map(r=>({type:'Feature',geometry:data.geometry[r.H3_INDEX],properties:r}));layer=L.geoJSON(features,{style:f=>({fillColor:color(f.properties[key]),fillOpacity:f.properties[key]==null?.35:.82,color:'#718b9a',weight:.35}),onEachFeature:(f,l)=>{const r=f.properties; l.bindTooltip(r.H3_INDEX+' · '+fmt(r[key]));l.bindPopup('<b>'+esc(key)+'</b><br>'+fmt(r[key])+'<br>'+esc(r.H3_INDEX)+'<hr><table>'+Object.entries(r).filter(([k])=>k!==key).map(([k,v])=>'<tr><td>'+esc(k)+'</td><td>'+fmt(v)+'</td></tr>').join('')+'</table>',{maxWidth:450})}}).addTo(map);
markers.clearLayers();for(const s of d.stations){if(s.lat!=null&&s.lon!=null)L.circleMarker([s.lat,s.lon],{radius:5,color:s.kind==='mouth'?'#854bb2':'#26394d',fillOpacity:1}).bindPopup('<b>'+esc(s.name)+'</b><br>'+esc(s.kind)+'<br>'+esc(s.station)+'<br>'+esc(s.status||'')).addTo(markers)}
document.getElementById('coverage').textContent=vals.length+' / '+d.rows.length+' · H3 R'+d.resolution;document.getElementById('low').textContent=fmt(lo);document.getElementById('high').textContent=fmt(hi);const c=d.info.coverage[key];document.getElementById('watercoverage').textContent=c?'Cells with values contain '+(100*c.valid_water_area_fraction).toFixed(1)+'% of support water area. This is cell support, not pixel-level observation coverage.':'No supported observations for this feature/date.';
document.getElementById('description').textContent=d.info.interpretation||'Source unavailable';document.getElementById('limitations').textContent=(data.family==='productivity'?data.limitations:(d.info.limitations||d.info.error||data.limitations))+' '+(d.info.seed_audit||[]).filter(s=>s.status!=='mapped').map(s=>'Unmapped: '+s.name+'.').join(' ');document.getElementById('metadata').textContent=JSON.stringify(d.info,null,2);document.getElementById('lineage').textContent='collect --family '+d.info.family+' → raw request snapshots\n→ processed daily '+data.family+' layer\n→ '+(d.info.kernel||d.info.spatial_aggregation||'unavailable')+'\n→ '+key;
}day.onchange=draw;metric.onchange=draw;colorscale.onchange=draw;draw();
</script></body></html>"""


def inspect(config=DEFAULT_CONFIG, start=None, end=None, families=FAMILIES):
    if not start or not end or not 0 <= (pd.Timestamp(end) - pd.Timestamp(start)).days < 31:
        raise ValueError(
            "Inspect an ordered window of at most 31 days; collect/build longer archives separately"
        )
    doc, cfg = load(config)
    out = doc.resolve_path(cfg.report_dir) / f"{start}_{end}"
    out.mkdir(parents=True, exist_ok=True)
    catalog = {}
    probes = []
    cards = []
    payloads = {}
    support = pd.read_parquet(
        doc.resolve_path(cfg.support_dir) / "h3_geometry/H3_MODEL_AREA_SUPPORT_RES_6.parquet"
    )
    water6 = gpd.read_parquet(
        doc.resolve_path(cfg.support_dir)
        / "h3_geometry/H3_MARINE_WATER_CLIPPED_GEOMETRY_RES_6.parquet",
        filters=[("H3_INDEX", "in", support.H3_INDEX.tolist())],
    ).to_crs(4326)
    water6 = water6.loc[~water6.geometry.is_empty].copy()
    water5 = water6[["H3_INDEX", "geometry"]].copy()
    water5["H3_INDEX"] = water5.H3_INDEX.map(lambda h: h3.cell_to_parent(h, 5))
    water5 = water5.dissolve(by="H3_INDEX").reset_index()
    map_geometry = {
        res: {
            r.H3_INDEX: mapping(r.geometry.simplify(0.00015, preserve_topology=True))
            for r in water.itertuples()
        }
        for res, water in [(6, water6), (5, water5)]
    }
    limitations = {
        "offshore_currents": "Coarser offshore flow at R5, not a replacement for resolved nearshore or tidal currents. Archive ends September 2024.",
        "tidal_model": "Older eight-constituent harmonic model. No outside-mesh extrapolation or storm surge.",
        "tides": "Smooth tidal range estimates are exploratory. They do not represent tide phase, absolute water level, or tidal current.",
        "river_discharge": "The selected gauges are an incomplete freshwater inventory. Approximate mouth mappings and influence distances need testing; this is not a modeled river plume.",
        "currents": "Regional SalishSeaCast footprint leaves outer-coast gaps. Four-hour sampling misses peaks and tidal reversals.",
        "ocean_temperature": "Satellite skin/surface temperature; cloudy or unresolved coastal pixels remain missing. No subsurface temperature inference.",
        "productivity": "Chlorophyll is a biomass proxy. The trailing seven-day mean uses available daily cell means through the selected date only; a separate 2PLUS metric requires at least two valid days. A one-day estimate is not equivalent to seven observations. Observation ages and counts are in each cell popup; daily observations remain separately selectable.",
    }
    for family in families:
        days = {}
        geometries = {}
        metrics = set()
        for date in pd.date_range(start, end):
            day = date.strftime("%Y-%m-%d")
            root = doc.resolve_path(cfg.processed_dir) / family / day
            info = json.loads((root / "MANIFEST.json").read_text())
            if digest(root / "FEATURES.parquet") != info["feature_sha256"]:
                raise ValueError("Feature checksum mismatch")
            frame = pd.read_parquet(root / "FEATURES.parquet")
            metrics.update(info["model_columns"])
            resolution = int(frame.H3_RESOLUTION.iloc[0])
            for cell in frame.H3_INDEX:
                if cell not in geometries:
                    geometries[cell] = map_geometry[resolution].get(
                        cell, {"type": "GeometryCollection", "geometries": []}
                    )
            markers = []
            if (root / "STATIONS.parquet").exists():
                stations = pd.read_parquet(root / "STATIONS.parquet")
                for s in stations.to_dict("records"):
                    markers.append(
                        {
                            "name": s["name"],
                            "station": s["station"],
                            "lon": s.get("gauge_lon", s.get("lon")),
                            "lat": s.get("gauge_lat", s.get("lat")),
                            "kind": (
                                "upstream discharge gauge"
                                if family == "river_discharge"
                                else "tide prediction station"
                            ),
                            "status": next(
                                (
                                    a["status"]
                                    for a in info.get("seed_audit", [])
                                    if a["station"] == s["station"]
                                ),
                                "",
                            ),
                        }
                    )
            for seed in info.get("seed_audit", []):
                if family == "river_discharge":
                    markers.append(
                        {
                            **seed,
                            "lon": seed.get("marine_seed_lon", seed["lon"]),
                            "lat": seed.get("marine_seed_lat", seed["lat"]),
                            "kind": "mouth",
                        }
                    )
            days[day] = {
                "rows": json.loads(
                    frame.drop(columns=["AVAILABLE_AT_UTC"], errors="ignore").to_json(
                        orient="records"
                    )
                ),
                "info": info,
                "stations": json.loads(pd.DataFrame(markers).to_json(orient="records")),
                "resolution": resolution,
            }
            indexed = frame.set_index("H3_INDEX")
            for label, lat, lon in PROBES:
                cell = h3.latlng_to_cell(lat, lon, resolution)
                probes.append(
                    {
                        "family": family,
                        "date": day,
                        "probe": label,
                        "H3_INDEX": cell,
                        "in_support": cell in indexed.index,
                        "values": {
                            m: (
                                float(indexed.loc[cell, m])
                                if cell in indexed.index and pd.notna(indexed.loc[cell, m])
                                else None
                            )
                            for m in info["model_columns"]
                        },
                    }
                )
        catalog[family] = {
            "sources": SOURCES[family],
            "collection_command": f"python -m oceanography collect --family {family} --start {start} --end {end}",
            "processed_layer": cfg.processed_dir
            + "/"
            + family
            + "/<date>/"
            + ("STATIONS.parquet" if family in ("tides", "river_discharge") else "LAYER.parquet"),
            "feature_transformation": (
                "water-path kernel at R8 then water-area aggregation to R6"
                if family in ("tides", "river_discharge")
                else "aggregate_pixels: valid native pixel weighted means"
            ),
            "model_feature_table": cfg.processed_dir + "/" + family + "/<date>/FEATURES.parquet",
            "model_columns": sorted(metrics),
            "map": family + ".html",
            "limitations": limitations[family],
            "dates": {d: v["info"]["coverage"] for d, v in days.items()},
        }
        payload = {
            "family": family,
            "days": days,
            "geometry": geometries,
            "metrics": sorted(metrics),
            "limitations": limitations[family],
        }
        if not payload["metrics"]:
            payload["metrics"] = ["UNAVAILABLE"]
        payloads[family] = payload
        sources = "<br>".join(
            f'<a href="{html.escape(url)}">{html.escape(name)}</a>' for name, url in SOURCES[family]
        )
        page = (
            TEMPLATE.replace("__TITLE__", TITLES[family])
            .replace("__STYLE__", STYLE)
            .replace("__SOURCES__", sources)
            .replace("__DATA__", json.dumps(payload, allow_nan=False).replace("<", "\\u003c"))
        )
        (out / (family + ".html")).write_text(page)
        cards.append(
            f'<a class="card" href="{family}.html" style="text-decoration:none"><div class="tag">H3 R{next(iter(days.values()))["resolution"]} · {len(days)} days</div><h2>{TITLES[family]}</h2><p>{html.escape(limitations[family])}</p><b>Explore map →</b></a>'
        )
    # Offer broader-source alternatives in the core family maps, retaining each
    # layer's own row set, native H3 resolution, geometry, metadata and coverage.
    for family, alternative in [("currents", "offshore_currents"), ("tides", "tidal_model")]:
        if family not in payloads or alternative not in payloads:
            continue
        payload = payloads[family]
        other = payloads[alternative]
        payload["metrics"] += other["metrics"]
        payload["geometry"].update(other["geometry"])
        payload["metric_variant"] = {m: alternative for m in other["metrics"]}
        for d in payload["days"]:
            payload["days"][d]["variants"] = {alternative: other["days"][d]}
        sources = "<br>".join(
            f'<a href="{html.escape(url)}">{html.escape(name)}</a>'
            for name, url in SOURCES[family] + SOURCES[alternative]
        )
        page = (
            TEMPLATE.replace("__TITLE__", TITLES[family])
            .replace("__STYLE__", STYLE)
            .replace("__SOURCES__", sources)
            .replace("__DATA__", json.dumps(payload, allow_nan=False).replace("<", "\\u003c"))
        )
        (out / (family + ".html")).write_text(page)
    write_json(out / "FEATURE_CATALOG.json", catalog)
    write_json(out / "COVERAGE_PROBES.json", probes)
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Environmental data | OrcaCast</title><style>{STYLE}</style></head><body><main style="max-width:1120px;margin:45px auto;padding:24px"><div class="tag">OrcaCast · Environmental research</div><h1>Environmental conditions in marine water</h1><p>{start} – {end} · Source-backed daily pilot · Prey remains separate</p><p>Tides and river discharge spread from marine seeds through the coastline-respecting water network. Satellite and model grids are aggregated from their native pixels. Gray areas indicate missing support.</p><div class="notice">Research candidates, not a complete historical backfill or a validated forecast input. River influence is a distance-decay proxy, not a hydrodynamic plume model. Coverage at example locations is in the downloadable audit.</div><div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:18px;margin:28px 0">{''.join(cards)}</div><nav><a href="FEATURE_CATALOG.json">Source-to-feature catalog</a><a href="COVERAGE_PROBES.json">BC / Washington coverage probes</a></nav></main></body></html>"""
    (out / "index.html").write_text(page)
    return out
