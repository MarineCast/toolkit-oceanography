# Research products and interpretation

[Documentation index](README.md)

The following summarizes code currently present, not production acceptance. The inherited
[feature catalog](../config/feature_catalog.yaml) is incomplete for newer families and composites.
The producers and their manifests remain necessary references until catalog reconciliation is done.

## Families

| CLI family | Source and support | Representative output / interpretation |
| --- | --- | --- |
| `tides` | CHS/NOAA station predictions, R8 water routing aggregated to R6 | `TIDE_RANGE_PROXY_M_20KM`, `TIDE_RANGE_PROXY_M_40KM`; normalized station-range influence in metres |
| `currents` | SalishSeaCast staggered surface U/V, R6 | `CURRENT_SPEED_SAMPLE_MEAN_MS`, `CURRENT_SPEED_SAMPLE_MAX_MEAN_MS`; speed in m/s from sampled hourly means |
| `river_discharge` | ECCC/USGS provider-day means and mapped river mouths, R6 | `RIVER_DISCHARGE_INFLUENCE_M3_S_10KM` and 25/50 km alternatives; flow weighted by water distance |
| `ocean_temperature` | Quality-filtered satellite SST, R6 | `SST_MEAN_C`; valid-pixel surface temperature in degrees Celsius |
| `productivity` | Positive satellite chlorophyll retrievals, R5 | Daily chlorophyll in mg/m³ plus trailing means, logs, counts and observation ages |
| `offshore_currents` | HYCOM surface vectors, eight three-hourly samples, R5 | Offshore sampled current-speed summaries in m/s; separate support from SalishSeaCast |
| `tidal_model` | DFO complex harmonics at R6 water representative points | Hourly sampled harmonic tidal range in metres; no absolute station datum or storm surge |

A daily candidate table has `DATE × H3_INDEX` identity within a family and configured resolution.
Do not concatenate families without recording the family, or join R5 and R6 rows without an explicit
support mapping. R5-to-R6 parent assignment does not create finer observations.

## Artifact layout

The separate [Waves pipeline](WAVES.md) delivers R5-keyed hourly instantaneous
significant wave height (m), mean period (s), mean direction (degrees FROM true
north), and derived WMO sea state. Daily statistics require complete per-quantity
UTC support and use circular direction. Every approved key remains present;
cells without a retained native wet centre stay null. Two Parquets and a required
catalog live in `Data/Oceanography/waves/`, independently of the legacy families
and other surface products. No forecast or ecological eligibility is implied.

The separate [regional Waves products](WAVES_REGIONAL.md) retain source-specific
native cadence, period definitions and support counts. SSC half-hourly T02/FROM
fields live in `Data/Oceanography/waves-salishseacast/` after validated full-run
promotion. USGS hourly source-Tm fields are reserved for
`Data/Oceanography/waves-usgs-nearshore/`; effective-coordinate qualification
currently blocks publication, and unresolved direction stays null. Both have
native/daily/support Parquets and a required catalog; all requested dates/R5 keys
remain present. Existing ERA5 values are never replaced or silently mosaicked.

The [LiveOcean surface scalar history](LIVEOCEAN.md) produces separate daily-labelled
R6 reference salinity, dissolved oxygen and nitrate Parquets with a shared lineage
companion. Values are 71-hour Godin-filtered surface model estimates, not 24-hour
UTC means or an implemented SSC/LO numeric mosaic. Native unsupported cells stay
null; generated source and month intermediates are removed after final readback.

The bounded [SSC Godin timing pilot](REGIONAL_FILTERED.md) adds separate R6
surface reference salinity, oxygen and nitrate Parquets, a final H3 phase-comparison
Parquet and required provenance. Its exact 71-tap values centre at 12:30 UTC on
SSC's hourly-mean axis; interpolation to LO's noon centre has 72 effective inputs
and an extra alignment filter. Neither variant is a 24-hour mean. It does not
activate a historical or mixed-model product or replace legacy checkpoints.

The user-selected [inner-water modes](REGIONAL_HYBRID_PLAN.md) are source
policies: `fast` uses LO where supported and SSC fallback; `complete` uses SSC
throughout inner waters. Outer-coast sources can be reused independently in both
modes, with existing GLORYS12 salinity/currents the low-effort default. These names
do not certify full coverage. The [surface-history runner](SURFACE_HISTORY.md)
implements the scalar choices over explicit regional support, producing final
monthly partitions of daily R6 values and per-cell/date source companions.
Geographic inner/outer mosaicing and currents are separate workflows. Preserve
native resolution, source-specific units/statistics and missingness. The existing
502-cell salinity gap target is not a full inner-water delivery.

The separate [regional LO salinity extension](REGIONAL_SUBSETS.md) retains the
same source noon Godin statistic and SR units over the expanded regional target.
Its monthly final H3 partitions and required manifest/provenance supplement the
old gap-only product; existing values must agree exactly. It does not reprocess
oxygen/nitrate or certify geographic inner-water completeness.

The source-specific [regional gap history](REGIONAL_GAP_HISTORY.md) has separate
daily R6 salinity/current tables and required lineage companions. Its reference
salinity and mean hourly-vector speed retain their native meanings; these are
additive GLORYS spatial-gap supplements, not replacements for the research-family
schemas above or a numeric cross-source mosaic.

Paths below are relative to the configured roots:

| Root | Artifact | Purpose |
| --- | --- | --- |
| `raw_dir` | `requests/` | Request-addressed source files and adjacent retrieval/checksum metadata |
| `raw_dir` | `<family>/<date>/MANIFEST.json` | Acquired inputs, config identity and source errors |
| `processed_dir` | `<family>/<date>/FEATURES.parquet` | Daily H3 research candidates and availability/support fields |
| `processed_dir` | `<family>/<date>/LAYER.parquet` or `STATIONS.parquet` | Source-family-specific normalized evidence where emitted |
| `processed_dir` | `<family>/<date>/MANIFEST.json` | Output/source checksums, code/support lineage, coverage and caveats |
| `report_dir` | `<start>_<end>/` | HTML inspections, source/feature metadata and comparison outputs |

`FEATURE_STATUS` indicates whether any selected metric is present, not whether every metric is
valid. `AVAILABILITY_MODE` remains `retrospective_research`; `AVAILABLE_AT_UTC` is unknown and
manifests mark `forecast_eligible: false`. Retrieval dates do not establish historical availability.

## Trailing chlorophyll

`CHLOROPHYLL_TRAILING_7D_MEAN_MG_M3` is an equal-weight mean of available daily cell means in the
seven days ending on the target date. Native pixels can differ between days. The configured minimum
is currently one valid day; the two-or-more-days companion is
`CHLOROPHYLL_TRAILING_7D_2PLUS_MEAN_MG_M3`.

Keep `COMPOSITE_VALID_DAYS`, `COMPOSITE_NEWEST_AGE_DAYS`, `COMPOSITE_OLDEST_AGE_DAYS` and
`COMPOSITE_WINDOW_DAYS` with the mean. `CHLOROPHYLL_TRAILING_7D_LOG_MEAN` is the natural log of the
trailing arithmetic mean; it should not be confused with the daily mean of native-pixel logs.
Chlorophyll is a biomass proxy, not primary production or prey abundance.

## Missingness and comparability

Clouds, source land masks, failed requests, invalid timestamps and disconnected water can leave
values missing. Zero discharge is a possible measured value; an unavailable gauge is not zero.
Coverage fractions describe water area of cells with candidate values, not full observation of
every square metre. Provider-day discharge windows are not asserted to be identical UTC periods.
Current maxima are sampled summaries, not guaranteed daily peaks. Tidal range removes station
height offsets but does not establish equivalent model/observation timing or coastal support.

Weekly aggregation, influence-scale selection, future-availability rules and ecological acceptance
remain downstream research decisions. See [RESEARCH.md](RESEARCH.md) and [TODO.txt](../TODO.txt).
