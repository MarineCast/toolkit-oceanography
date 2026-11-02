# Source-specific regional Waves pipelines

Implementation contract, authorized 2026-11-01. Qualification and full production
are distinct stages; execution evidence is added only after actual checks.
Existing ERA5 Waves and independently owned ocean products remain unchanged.

## SalishSeaCast nowcasts

The producer selects only canonical daily `nowcast/DDmonYY/SoG_ww3_fields_YYYYMMDD_YYYYMMDD.nc`
files from the official ERDDAP wave file inventory. Forecasts, point products and
`.aside`/alternate run directories are excluded explicitly and recorded. The
frozen inventory observed on 2026-11-01 local time spans 2017-04-12–2026-11-01,
with 36 missing daily files and three alternate-directory duplicates. Requested
2009 dates before source support and missing archive dates remain null.

Native inputs are half-hourly instantaneous `hs` (m; wind and swell significant
height), `t02` (s; second-frequency-moment mean period), and `dir` (degrees FROM
true north). The native 500 m grid is independent of NEMO's grid. Numeric CF-day
time decoding may round to the scheduled half-hour only within 1 ms, recording
that precision rule; other offsets, unexpected days or duplicate times fail.
Values use source fill/scale/offset and physical-domain checks. Calm height is
real zero; invalid/undefined direction and nonpositive period stay null.

Native centres must fall strictly inside the checksum-bound approved water mask
and the same approved R5 cell. H3 quantities are cosine-latitude-weighted means of
valid native samples in each cell; direction uses a circular mean. The support
companion records geometric/finite counts per quantity, so a partially sampled
cell is not represented as fully observed. No source point is relocated, and no
source value is copied between cells or across land. Daily summaries require 48
finite half-hourly H3 values per quantity; daily direction is circular. Sea state
is the existing height-derived WMO proxy, with exact positive bounds in the lower
class, derived from the H3 mean height and daily sampled maximum respectively.
T02 remains explicitly named and is never relabeled as ERA5 mwp.

Separate delivery: `Data/Oceanography/waves-salishseacast/`, with native half-hourly
and daily Parquets, native support counts and a required catalog. Every requested
UTC date/R5 key remains present, including wholly unsupported dates/cells. Source
inventory, native grid/metadata, actual time axes, run-path choice, content hashes,
retrieval time, versions and final checksums remain in provenance. Publication
requires a complete verified checkpoint set. Failed acquisition remains failed
or pending, not an invented all-null source day. Genuine inventory gaps are null.

The ERDDAP file service explicitly disallows HTTP ranges; the workflow respects
that restriction. Whole daily NetCDF4 inputs are bounded and read in memory;
only final H3 checkpoints and compact receipts are retained outside the published
product. No second bulk raw archive is made. At most two source requests and bounded
RAM/response size govern this worker. Raw source disk usage is zero, so it adds no
raw files to the existing registered 2 GB source caches. The local launcher waits
for the already active two-request scalar backfill to exit before acquiring waves.
A 20 GB free-disk floor protects checkpoint and publication staging. Full archive volume is about 698 GB before exclusion of
alternate runs; this is a long-running backfill, not a small metadata operation.
Checkpoints allow verified resume without downloading completed dates again.

## USGS CoSMoS nearshore

The producer is separate from ERA5 and SSC and considers only 0 m sea-level
historical `Hs`, `Tm`, `Dm`; projections and raised-sea-level scenarios are excluded.
Native time endpoints are 1941-01-01–2023-10-06 00:00 UTC. The requested history
starts 2009; October 5 is the last candidate complete daily summary. Packed
`-9999` is masked before applying scale 0.0001; low-height suppression of Tm/Dm
below Hs 0.05 m remains null. Tm is explicitly source-specific.

**Publication qualification gate:** the source says values are evaluated at
nearby 10 m-isobath model locations but supplies original reference coordinates.
An evidence-backed effective-coordinate mapping is required before any H3 values
are emitted. Incoming-versus-propagation direction must also be resolved before
populating a FROM direction field; without that evidence the direction stays null.
The last supported instant is October 6 00:00 UTC; that date has a single supported
hour and an incomplete, null daily summary. October 5 is the last candidate
complete day, subject to actual per-quantity source values. A qualification failure is retained outside Data with its
exact cause and source evidence; it is not converted into a successful empty
history or an invented coverage improvement. The implementation must support
an explicit source-qualified mapping rather than relax coastal tolerances.

The existing [source investigation](WAVE_SOURCES.md) retains these unresolved
qualifications. No source owner is contacted without explicit user instructions.
A source-supplied mapping or authoritative public model outputs can satisfy the
geolocation gate; guessed bathymetric relocation cannot.

## Commands and public API

Install from the owner checkout, independently of sibling toolkits:

```sh
python -m pip install -e '.[waves-regional,test]'
oceanography waves-salishseacast --study /path/to/config/study.v1.json --start 2009-01-01
oceanography waves-usgs-nearshore --study /path/to/config/study.v1.json --qualify-only
oceanography waves-usgs-nearshore --study /path/to/config/study.v1.json --start 2009-01-01 --mapping-path /path/to/qualified-effective-grid.json
```

Both commands accept `--start`, `--end`, `--output`, `--work`, and a read-only
`--check /path/to/catalog.json`. SSC additionally accepts
`--requests-in-flight 1|2` (default 2). USGS uses serial exact HTTP ranges with
source-identity checks, a 256 MB RAM range cache per county and 2 GB transfer cap
per monthly/county read; it never downloads entire 10–30 GB county files.
Retrieval/time/identity failures stop acquisition, rather than create null gaps.
Source interiors are verified while read, not inferred from header endpoints.

Python: `oceanography.get_salishseacast_waves(..., study_config=...)`,
`get_usgs_nearshore_waves(..., study_config=...)`, and
`check_regional_waves(catalog_path, study_config=...)`. ERA5 `get_waves` and
`check_waves` remain independent. Optional `h5py` imports occur only on regional
wave routes, so existing installations do not require this new extra.

USGS effective-grid JSON must have `release_doi` equal to
`https://doi.org/10.5066/P14VOPEY`, an authoritative
`effective_coordinate_evidence_url`, and a `files` entry for each selected county
basename. Each entry contains the qualification report's `source_header_sha256`,
explicit zero-based `station_index` in native order, and equal-length `latitude`
and `longitude` arrays for actual effective model locations. Guessed reference
points are not qualification evidence. Optional
`direction_from_true_north_evidence_url` authorizes FROM values; without it Dm
remains null. Duplicate effective locations require source-qualified station
deduplication before averaging and are rejected. This work has no such mapping.
Tm remains `mean_wave_period_source_tm_s`, not T02 or ERA5 mean period.

The three delivered files are `waves-native.parquet`, `waves-daily.parquet`, and
`waves-support.parquet`, plus required `catalog.json`. Native/support keys are
UTC `datetime × h3_index`; daily keys are `date × h3_index`. SSC native metrics
are `significant_wave_height_m`, `mean_wave_period_t02_s`,
`mean_wave_direction_from_deg`, `sea_state_code`. Daily metrics are height
mean/max, T02 mean, circular FROM mean, and maximum height-derived sea-state code.
Support fields are geometric native centres and finite height/period/direction
centre counts. USGS uses the same schema with `source_tm` in place of `t02`.
All numeric missing values are Arrow nulls. Cosine weights approximate native
latitude/longitude pixel area; they do not estimate whole-cell water coverage.
Neither source establishes ecological or forecast eligibility.

Plans freeze source inventory, selection, study hashes, native grid, mapping and
runtime code hashes. Resume verifies completed checkpoint hashes, keys, metadata,
nulls, physical domains and reductions without fetching them again. A complete
published run is a verified no-op. Revised scope/code needs a new owned work root
and output; it cannot silently alter the frozen attempt. Publication is staged
and checked before atomic promotion, preserving existing delivery on failure.

## Qualification and execution evidence — 2026-11-01

The canonical nowcast inventory contains **3,455 distinct available dates** from
**2017-04-12 through 2026-11-01**, 36 missing daily files and three explicitly
excluded alternate runs. Whole canonical files total **697,526,840,600 bytes**;
HTTP gzip saves little for these internally compressed NetCDF4 files. A first
historical file took about 33 seconds and transferred about 204 MB. Full history
is a substantial network job; that one-file timing is not a full-run ETA.

A complete first source file was downloaded for layout qualification. Retained
first/last half-hour frames verify 80,432 selected native wet-mask centres in
226 geometric R5 cells; both frames have finite height in **172 cells**. These
are sampled support counts, not whole-history coverage or accuracy claims. The
source and regular installed-wheel replay independently checked 38 cell/frame
anchors. All twelve retained USGS native headers replay through the qualification
gate; effective coordinates remain absent, so **no USGS H3 history is published**.
Header endpoints do not prove interior completeness.

The 2026-11-01 task adds eleven offline regional-wave checks; the complete source and
regular installed-wheel suites pass **140 tests**, with one pre-existing netCDF/
NumPy ABI warning. The installed replay uses packaged configuration initialized
outside the checkout and a small resource-only fixture for the checkout-template
comparison. No sibling Python imports are needed. Tests cover canonical run
selection, packed fill, time/grid/quantity identity, per-quantity support,
circular means, complete/partial days, true gaps, failure versus missingness,
checkpoint tampering, resume, publication preservation, USGS spatial gating and
unknown-direction nulls.

The installed-wheel local backfill launcher is **queued behind the existing
Oceanography source worker**, then qualifies the latest full native day and
independently checks all 48 samples of the first native day before continuing.
Its requested scope is 6,514 dates, starting 2009-01-01; 3,023 pre-archive dates and
36 inventory gaps are null. Expected keys per native/support file are 144,767,136;
expected daily keys are 3,015,982. These are planned counts, not completed rows.
No SSC canonical final product is promoted before all checks pass. Full native-day
parity, complete history, final publication and independent buoy/coastal accuracy
are not claimed by the completed sample/software checks. Existing ERA5 products
retain their original checksums.

Local evidence is under `Reports/oceanography-waves-regional-2026-11-01/`:
`backfill-scope.json`, `native-replay-source.json`, `native-replay-wheel.json`,
`usgs-library-qualification.json`, `job.json`, and `validation.json`. The launcher
`run_backfill.py` is a task-owned executable wrapper, not a package dependency;
canonical acquisition/reduction/checking lives in this toolkit. The worker is
not automatically restarted on failure. Inspect `job.json` and the work root's
`progress.json` before an explicit resume. A detached process requires this
machine to remain available; no recurring app automation is installed.

```sh
python -m pytest -q tests/test_waves_regional.py
python -m pytest -q
python -m pip wheel --no-deps --no-build-isolation . --wheel-dir dist
```

Repeat the tests and retained native replay against that regular wheel outside
the checkout; `oceanography init --workspace .` provisions its packaged config.
Live full-day qualification and publication checks are part of the queued worker,
not substitutes for independent scientific accuracy assessment.

Primary sources: [USGS release](https://doi.org/10.5066/P14VOPEY),
[SSC wave-file inventory metadata](https://salishsea.eos.ubc.ca/erddap/info/ubcSSWaveWatch3-SoGFilesV17-02/index.html).
USGS is CC0 with attribution; SSC results use Apache 2.0 with SalishSeaCast/UBC/
DFO IOS attribution. These are model outputs, not buoy observations.


## Bathymetry follow-up — 2026-11-02

The user suggested checking retained bathymetry for the missing USGS mapping.
The current `Data/Seascape/bathymetry-r6-static.parquet` and R8 companion are H3
cell summaries, with no USGS wave-station identity or effective-coordinate table.
Their embedded source context identifies GEBCO 2026 at 15 arc seconds. The retained
native raster is a single-band WGS84 elevation grid (positive up, meters relative
to sea level); the derived product declares positive-down depth. Its constituent
vertical datums have the source's documented limitations. A 10 m depth level is
not a 10 m horizontal-location tolerance.

The underlying [wave-model method, section 3.2.2](https://eartharxiv.org/repository/object/5141/download/10171/)
merges finer USGS/NOAA/BC DEMs with GEBCO, then averages/interpolates onto model
grids; the [2026 method](https://egusphere.copernicus.org/preprints/2026/egusphere-2026-3369/egusphere-2026-3369.pdf)
builds on that hybrid framework. The inspected public method does not identify
our retained GEBCO raster as the release-specific wave output grid. Consequently,
a nearest 10 m contour extracted from this raster would be an inferred location,
not a verified reconstruction of the station-to-model-grid lookup. The inspected
products, bathymetry cache and retained USGS qualification contain no qualifying
mapping; this is not an exhaustive absence claim about all public archives.

The current raw GeoTIFF checksum matches the retained October 29 reproduction
candidate, but differs from the source checksum embedded in the canonical H3
product. This byte-vintage difference was recorded, without inferring corruption
or asserting current numerical parity. Sources, canonical bathymetry and wave
values were preserved; no source migration or new mapping was produced.

USGS publication therefore remains gated. An authoritative effective-coordinate
table can satisfy the gate; a validated reconstruction would instead require the
exact release-specific model grid/bathymetry, datum, wet mask and station selection
rule or lookup. Unsupported support remains null. The SSC worker remains queued
behind the existing acquisition owner. Evidence and the bounded read-only replay
are retained locally at `Reports/oceanography-waves-bathymetry-2026-11-02/`.
This was source/document qualification; pipeline code and datasets were unchanged.
