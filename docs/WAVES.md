# Waves

The separate `oceanography waves` pipeline generates ERA5 wave history in the
configured `Data/Oceanography/waves/` directory. It preserves existing ocean
products and independently owned regional jobs. The implementation and the
2009-01-01–2026-10-26 delivery were checked on **2026-11-01**.

The subsequent [higher-resolution source investigation](WAVE_SOURCES.md) documents
USGS nearshore and SalishSeaCast candidates, native date/geolocation limitations,
and a null-preserving qualification sequence. It does not change this delivery.

## Run and read

```sh
python -m pip install -e '.[waves,test]'
oceanography waves --study /path/to/config/study.v1.json --start 2009-01-01
oceanography waves --study /path/to/config/study.v1.json \
  --check /path/to/Data/Oceanography/waves/catalog.json
python -m pytest -q tests/test_waves.py
python -m pytest -q
```

The study must supply an approved, checksum-bound water mask, validated R5/R6
registries, time bounds and a configured data root. CDS credentials come from
`CDSAPI_KEY`, or `CDSAPI_RC` / `~/.cdsapirc`; the existing credentials are never
printed. Access uses only the official ECMWF origin, without redirects or proxies.
An online call reads fresh metadata and chunks into a new bounded retrieval
snapshot. Omit `--end` to use the latest complete source UTC day within the study.
An explicit end beyond source support fails. `--allow-partial-final-day` is an
explicit exception: unavailable hours and incomplete daily quantities remain null.

```python
from oceanography import get_waves, check_waves
result = get_waves("2009-01-01", study_config="/path/to/config/study.v1.json")
check_waves(result["catalog_path"], study_config="/path/to/config/study.v1.json")
```

`MARINECAST_STUDY_CONFIG` can supply the Python API study path. `output` and
`cache_dir` (CLI `--output`, `--cache`) must be separate dedicated directories.
`shared_caches` / repeated `--shared-cache` registers other source stores for the
aggregate budget. `offline=True` / `--offline` requires a complete receipt-verified
snapshot at the selected cache path. Online snapshot paths are recorded in the
catalog. Explicitly covered end dates return the frozen existing product; default
latest calls check fresh source dates. Appends retain old row groups and source
epochs without rewriting their values. Revisions, a previously partial final day,
changed native support or changed producer code require `--rebuild` to recalculate
covered dates. An interrupted run preserves candidate files and the previous
published product; recovery does not certify those candidates as complete.

## Source, rights and native support

Source: official [ERA5 single-level data](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels)
and [ECMWF ARCO guide](https://confluence.ecmwf.int/pages/viewpage.action?pageId=505390919).
The `wav/geoChunked.zarr` store supplies these instantaneous analysis parameters:

| Source | Parameter ID | Meaning | Unit |
| --- | --- | --- | --- |
| `swh` | 140229 | Significant height of combined wind waves and swell | m |
| `mwp` | 140232 | Mean wave period; not peak period | s |
| `mwd` | 140230 | Mean wave direction, coming FROM | degree true |

The actual coordinate arrays are hourly, latitude ascending from −90° to 90°,
longitude −180° to 179.5°, both at **0.5°** spacing. Source chunks have
135,168 times × 2 latitudes × 4 longitudes; coordinates are decoded and verified,
not inferred from a legacy decreasing-latitude attribute. The inspected frontier
is **2026-10-26 23:00 UTC**. These fields are instantaneous, so that date contains
24 samples and supports a complete daily summary without a following midnight.
Source values are reanalysis/model estimates. ERA5 versus ERA5T revision identity
and historical operational availability are unknown; appends freeze each acquired
epoch rather than asserting a seamless historical vintage.

The source is CC BY 4.0, attributed to Copernicus Climate Change Service / ECMWF,
DOI `10.24381/cds.adbb2d47`. Contains modified Copernicus Climate Change Service
information 2026. Neither the European Commission nor ECMWF is responsible for
uses made of these data. The package does not bundle the source data or credentials.

The [ECMWF archived-wave convention FAQ](https://confluence.ecmwf.int/spaces/FCST/pages/111155338/What%2Bis%2Bthe%2Bdirection%2Bconvention%2Bfor%2Bwave%2Bfields)
and [wave-parameter manual](https://confluence.ecmwf.int/download/attachments/59774192/wave_parameters.pdf?version=1)
define bulk parameter 230 as FROM: north 0°, east 90°. The generic forecast-display
wave guide describes propagation TOWARDS; that conflicts with this archived bulk
parameter convention. This pipeline follows the parameter-specific FAQ/manual,
preserves the source angle, and applies no 180° rotation. Wave spectra are separate.

Spatial support is conservative: a native grid centre must be strictly inside the
approved study water mask and in the same approved R5 cell. Each reporting cell
has at most one retained native point; ambiguous multiple points fail. Source
missing values, invalid physical values and unassigned cells stay null. There is
no nearest-wet relocation, offshore-to-inlet filling, interpolation, or assumed
model footprint around a point. R5 keys do not create R5-scale observations from
this coarse grid. The absence of a retained point is specific to this mapping
policy and is not a claim that every other possible source lacks coverage.

## Products, units and reductions

| File | Key | Metrics |
| --- | --- | --- |
| `waves-hourly.parquet` | `datetime` (UTC microseconds), `h3_index` | `significant_wave_height_m`, `mean_wave_period_s`, `mean_wave_direction_from_deg`, `sea_state_code` |
| `waves-daily.parquet` | `date` (date32), `h3_index` | `significant_wave_height_mean_m`, `significant_wave_height_max_m`, `mean_wave_period_mean_s`, `mean_wave_direction_from_circular_mean_deg`, `sea_state_code_max` |
| `catalog.json` | Separate Waves product | Method, units, native grid/point mapping, study/source/code hashes, per-epoch receipts, versions, coverage and null counts |

Each file has one row group per UTC date, ordered by time then sorted approved R5
cell. Every key is retained, including wholly unsupported cells. Scalar units are
metres and seconds; directions are degrees clockwise from true north. Height must
be finite and nonnegative; period must be finite and positive. Source 360° is
canonicalized to 0°; invalid directions stay null. A real zero height is calm;
direction is undefined and becomes null at zero height. The three source quantities
otherwise retain independent missingness. Nullable sea-state columns are int8;
physical metrics are float64 preserving decoded source values.

Daily means/maxima use the 24 instantaneous samples at 00:00–23:00 UTC and require
24 finite samples **for each quantity independently**. Height maximum is a sampled
maximum, not a continuous daily extreme. Daily direction is an equal-time circular
mean, not an arithmetic angle mean or energy-weighted direction; a cancelled
resultant (≤1e-12) stays null. There is no rolling window or local-time aggregation.

Sea state is a **height-derived WMO code 3700 proxy**, not an observed categorical
report, Beaufort wind force, vessel-safety assessment or detectability score.
Following the [WMO guidance](https://community.wmo.int/site/knowledge-hub/programmes-and-initiatives/marine-services/frequently-asked-questions)
and [NOAA code table with boundary notes](https://www.nodc.noaa.gov/gtspp/document/codetbls/wmocodes/table3700.html),
exact bounds belong to the lower code:

| Code | Description | Significant height (m) |
| --- | --- | --- |
| 0 | Calm, glassy | exactly 0 |
| 1 | Calm, rippled | (0, 0.1] |
| 2 | Smooth, wavelets | (0.1, 0.5] |
| 3 | Slight | (0.5, 1.25] |
| 4 | Moderate | (1.25, 2.5] |
| 5 | Rough | (2.5, 4] |
| 6 | Very rough | (4, 6] |
| 7 | High | (6, 9] |
| 8 | Very high | (9, 14] |
| 9 | Phenomenal | >14 |

These descriptive height bands are guidance for open-sea wind waves; applying
them to combined significant wave height is an explicitly derived approximation.
Daily `sea_state_code_max` uses the maximum hourly height, requiring all 24 height
samples. Missing height produces null code, never code 0.

## Storage and validation

Only the two final Parquets and their required catalog are delivered under the
separate Waves directory. Source payloads/receipts and staging stay outside Data.
Each response and decoded chunk is bounded to 8 MiB; at most two requests overlap.
One decoded source time block is held in RAM. All retained Waves retrievals count
towards a 300 MB source-cache limit. Registered other caches plus a 900 MB regional
request reservation count towards the shared 2 GB cap; the free-space floor is
20 GB. Register any concurrently used stores rather than assuming they are empty.
Requests stop before growth exceeds the budget. Bounded sources, failed candidates
and any previous delivery are retained for review/replay; there is no automatic
source/backup deletion or alteration of another workflow's checkpoint.

The read-only checker verifies product hashes, schema, exact keys and source-epoch
partitioning; recomputes point support from the approved mask/grid; rejects values
in unsupported cells; and checks every hourly sea-state code and daily reduction.
Producer checks compare first/leap/final sample days to native points. A regular
installed-wheel replay also independently decodes those raw native chunks. These
are source/software checks; independent buoy accuracy, coastal wave transformation,
application integration, ecological effects and forecast readiness remain untested.
`model_eligible` and `forecast_eligible` remain false.

The 2026-11-01 run retained **463 reporting cells**, of which **23** contain a
native centre and **21** have finite source height throughout the delivered hours.
The other **442** cells are always null (440 without a retained centre, two native
source gaps). Height/period/state have 3,280,032 finite hourly rows and 136,668
finite daily rows. Direction has three additional null hourly values at zero height
and three additional incomplete daily summaries. The complete files contain
72,316,896 hourly and 3,013,204 daily rows, occupying 118,678,795 bytes including the
catalog. All 13 pre-existing top-level Oceanography Parquets and the other three
regular files were unchanged. See the workspace production/validation record in
`Reports/oceanography-waves-2026-11-01/`; this evidence is local and is not bundled
with an independent clone.
