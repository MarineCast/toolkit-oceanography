# Oceanographic environmental research

[Documentation index](README.md)

This guide retains the original five-family methods. The current package also contains HYCOM
offshore-current and DFO tidal-model research adapters and trailing chlorophyll composites; see
[PRODUCTS.md](PRODUCTS.md) for all seven families and [WORKFLOWS.md](WORKFLOWS.md) for current commands.
Historical coverage observations below are not a new standalone toolkit run.

This package collects and builds **tides, currents, river discharge, ocean temperature, and productivity proxies**. Prey is outside its scope. The workspace configuration is `config/data/environment_oceanographic.yaml`. This is an incomplete research implementation; see [TODO.txt](../TODO.txt).

## Run

After installation and workspace initialization:

```sh
python -m oceanography run --start 2024-07-01 --end 2024-07-03
python -m oceanography run --start 2024-07-01 --end 2024-07-03 --offline
python -m oceanography collect --family river_discharge --start 2024-01-01 --end 2024-01-31
python -m oceanography build --family river_discharge --start 2024-01-01 --end 2024-01-31
python -m oceanography inspect --family river_discharge --start 2024-01-01 --end 2024-01-31
```

`collect` makes real HTTP requests. `build` and `inspect` run offline. Dates are explicit; no automatic multiyear download. HTML inspection is limited to 31 days per report to bound browser memory; collect/build longer archives separately. Work is partitioned by day, and current downloads retain only the surface and six hourly-mean snapshots per day by default. Set `current_interval_hours: 1` for all 24 hourly means when testing temporal sensitivity.

Raw requests are keyed by their complete URL and checked against their recorded SHA-256 before reuse. Changed coordinates, dates, variables, or providers create different requests. `--refresh` collects into a new immutable request directory, including fresh metadata and revised gauge observations; it preserves old snapshots. Without it, the cache is a reproducible frozen source snapshot, including its archive-end metadata. Refresh and offline mode are mutually exclusive.

## Source → collection command → processed layer → feature transformation → model column

All commands use the module above with `collect --family FAMILY` and an explicit date interval.

| Family | Source | Processed daily layer | Transformation | Numeric model candidates |
|---|---|---|---|---|
| Tides | CHS and NOAA CO-OPS hourly astronomical predictions | `tides/<date>/STATIONS.parquet` | Within-station hourly sampled range; normalized exponential water-path blending at R8; water-area aggregation to R6 | `TIDE_RANGE_PROXY_M_20KM`, `TIDE_RANGE_PROXY_M_40KM` |
| Currents | UBC SalishSeaCast historical surface U/V | `currents/<date>/LAYER.parquet` | Adjacent C-grid faces averaged to T centers, rotation-invariant speed, six hourly-mean samples/day, valid native-point aggregation to R6 | `CURRENT_SPEED_SAMPLE_MEAN_MS`, `CURRENT_SPEED_SAMPLE_MAX_MEAN_MS` |
| River discharge | ECCC HYDAT and USGS daily means | `river_discharge/<date>/STATIONS.parquet` | ft³/s → m³/s where needed; explicit gauge-to-mouth mapping; sum of flow × exponential water-distance decay at R8; water-area aggregation to R6 | `RIVER_DISCHARGE_INFLUENCE_M3_S_10KM`, `..._25KM`, `..._50KM` |
| Ocean temperature | NOAA ACSPO satellite SST reanalysis | `ocean_temperature/<date>/LAYER.parquet` | Quality levels 4–5, finite native-pixel area-weighted mean to R6 | `SST_MEAN_C` |
| Productivity proxy | NOAA science-quality VIIRS chlorophyll | `productivity/<date>/LAYER.parquet` | Positive finite chlorophyll; native-pixel weighted means and mean of natural log to R5 | `CHLOROPHYLL_MEAN_MG_M3`, `CHLOROPHYLL_LOG_MEAN` |

Processed layer paths are relative to `data/processed/domain/environmental_layer/oceanographic`. Final daily tables are `<family>/<date>/FEATURES.parquet`. The map run's `FEATURE_CATALOG.json` records exact source links, commands, transformations, columns, and paths. `MANIFEST.json` retains raw-request lineage, code and spatial-support checksums, coverage, processing assumptions, and errors. No model training or production feature list is changed.

These are **daily** model candidates. Joining to the weekly baseline requires an explicit temporal aggregation policy and coverage threshold. R5 chlorophyll can join to R6 by logical parent, but doing so must preserve its R5 source resolution; it does not create finer ocean detail.

## Marine influence, not station-only effects

The spatial builder reuses canonical **R8 water-passable edges**, filters to model-area support, and routes through the water network. Target-only terminal connectors cannot become shortcuts through land. The output remains R6. Distances include the local seed connector.

River gauges are never snapped directly from upstream land into marine water. Each configured gauge has an explicit river-mouth coordinate and mapping rationale. Existing seascape mouth IDs are recorded where available; BC approximations are labeled `research_approximate`. Mouth seeds can project to the nearest mapped coast by at most 1 km to reconcile estuary/shoreline mismatch; tide stations permit at most 200 m. The original coordinate, marine seed, coast-snap distance, graph node, and connector distance are retained. A 100 m shoreline tolerance applies to the short seed connector only. Longer paths use the canonical water-passable graph. These are research tolerances, not validation of gauge-to-estuary transport.

The exponential kernel is `exp(-water_distance_km / scale_km)` and stops at three scales. The scale is an e-folding distance, **not** the hard radius. River contributions sum without normalization, so influence decays away from river mouths. Tide weights normalize, estimating neighboring tidal range rather than making tides vanish offshore. At least half of a parent's marine water area must have fine-grid support. Missing an expected contributing gauge invalidates that parent; zero flow remains a valid measured zero. Fine-grid support fractions and mean source counts/distances accompany the features.

The 10/25/50 km river and 20/40 km tide scales are alternative explanatory hypotheses. Select them inside training folds. They are not calibrated plume lengths, transport times, salinity, causality, tide phase, or current predictions. No runoff is inferred for unrepresented catchments. Station datum differences are removed by taking within-station range; absolute water heights are not blended.

## Coverage and availability

- The configured river roster contains 6 Canadian and 8 US gauges, including Washington outer-coast rivers. It is still incomplete. Upstream stations omit some downstream tributaries; Skagit uses one outlet without distributary allocation, Puntledge omits the Tsolum, and Quinault uses a lake-outlet gauge.
- CHS and NOAA tide predictions are separate provider contracts. The maps expose stations that cannot connect to the marine support rather than extending influence across land.
- SalishSeaCast covers the regional Salish Sea system, not the entire outer Washington/BC coast. Native model land and unsupported ocean cells remain missing. The current maximum feature is the spatial mean of sampled native-point maxima, **not** a true daily peak or east/north vector.
- Satellite products cross the international border, but clouds, coastal retrieval quality, source land masks, and pixel-center support create gaps. Chlorophyll estimates biomass, not primary-production rate. There is no gap filling or anomaly/heatwave climatology in this first implementation.
- Canadian HYDAT daily records and USGS daily records retain provider daily dates. Their daily windows are not asserted to be identical UTC intervals. QC flags and US approval status remain in the station layer. Recent Canadian approved history can lag real time; a missing historical daily record stays missing rather than being silently replaced by a realtime measurement.
- Every row is `retrospective_research`, with unknown `AVAILABLE_AT_UTC`; manifests set `forecast_eligible: false`. Retrospective reanalysis and later hydrometric revisions are not asserted to have been available at historical forecast issue time.
- Requested dates outside satellite/current metadata ranges fail explicitly, and returned timestamps are checked to prevent ERDDAP's nearest-date substitution.

HTML maps use water-clipped geometry, daily/metric selectors, source markers, gray missing areas, support popups, and visible caveats. Coverage fractions measure water area in cells with values, not a claim that every square metre was observed. `COVERAGE_PROBES.json` checks named BC, WA, and shared-water locations without approximating the international border as latitude 49°.

## Next experiments

1. Backfill selected summer and winter windows, then the model date range in bounded batches. Audit provider/gauge gaps before training.
2. Review approximate estuary mappings and unresolved station/shoreline mismatches; add remaining catchments with defensible gauge-to-mouth associations.
3. Compare full-hour current sampling with the six-snapshot default. Validate tide estimates against withheld stations.
4. Compare influence scales, temporal aggregation, and lag assumptions inside the existing blocked evaluation. Add anomalies only from training-period climatology.
5. Complete validation of the implemented HYCOM offshore-current and DFO tidal-model alternatives. Preserve provider boundaries and validate overlapping regions before blending.
