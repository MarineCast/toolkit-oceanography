# GLORYS history layout benchmark — 2026-10-29

The earlier 3.63-hour/35.52-GB estimate used only the short-time Geo Series layout. It is not the appropriate history acquisition plan. The same official GLORYS12 dataset/version also exposes Time Series (`geoChunked.zarr`), preserving native resolution, daily definitions and coverage. No coarser source is required to obtain this speedup.

## Measured evidence

Anonymous reads of 60 previously uncached local source chunks transferred 26,438,888 bytes in 22.667 seconds using four workers. This is first-fetch from this machine, not a claim that provider/CDN caches were cold. Summed request time was 89.365 seconds. Fifty-one chunks cover one time block for all 17 required spatial tiles and three variables; nine additional chunks sample the other three historical time blocks at one representative wet tile. No complete-history acquisition was performed.

5,625 native pilot values (625 wet native centres × three variables × three dates) matched the accepted July 1–3, 2024 source arrays exactly, including missingness. Both published pilot tables, including all 463 reporting cells/date and daily-vector-speed aggregation, matched exactly. Cached checksum validation took 0.031 seconds; cached decode, aggregation and published-table comparisons took 0.052 seconds, with zero network requests. No public output changed.

New benchmark payload: 26.44 MB plus 17,376-byte metadata, below the 250 MB limit. Receipts contain object keys, byte counts, timing and SHA256. Files: `/tmp/copernicus-public-20261029/layout-benchmark/result.json`, per-object chunks/receipts; scripts `/tmp/glorys-layout-bench.py`, `/tmp/glorys-layout-finish.py`; plan `/tmp/copernicus-public-20261029/geo-plan.json`. The finish script created correctly named full-key receipts; earlier suffix-shortened receipt files are superseded by the result manifest and full-key receipts and were retained rather than deleted.

## Full-range metadata dry-run (not a Toolbox invocation)

Source daily availability: 1993-01-01–2026-09-22. Requested history: 2009-01-01–2026-09-22, 6,474 days. Both layouts are present in the actual official STAC assets. Shape is [12318,50,2041,4320]; surface elevation index 49 is -0.494025 m.

| Layout | Native chunk | Unique required source objects | Transfer |
|---|---|---:|---:|
| Geo Series/timeChunked | 1 day × 1 depth × 512 × 2048 | 38,844 | prior sample extrapolation 35.52 GB |
| Time Series/geoChunked, approved-water tiles | 2,081 days × 1 depth × 16 × 16 | 204 | current sample estimate 101.26 MB |
| Time Series, complete study rectangle | same | 420 | not benchmarked across all tiles |

The 204-object count is exact for the frozen 625 approved native wet centres, 17 tiles, four temporal blocks and three variables. Estimated transfer extrapolates three representative historical-tile samples plus the measured full latest block; compression can vary elsewhere. Enforcing 1.1 MB per object gives a 224.4 MB acquisition ceiling, failing/checkpointing rather than silently expanding if exceeded. Each decoded chunk is 1,065,472 bytes. This is actual chunk transfer accounting, not the smaller output-file size. No server-side crop is assumed.

At measured request throughput, 204 objects project to about 76 seconds at four workers, before validation and publication. Recommend a 2–5 minute acquisition budget with a bounded deadline, not a promised end-to-end SLA. Daily mapping and output validation have not been benchmarked across all 6,474 days; allow several additional minutes and measure during implementation. Retain source chunks (under 225 MB guard), provenance, streaming daily outputs and staging within a 1 GB initial disk budget and a 20 GB free-space floor. Avoid repeated requests per date: retrieve each unique object once, verify checksum and reuse. Existing 60 objects can be reused only after inventory checks.

## Why Meteorology appeared fast

Read-only inspection of `toolkit-meteorology/src/meteorology/regional_source.py` found geographic tiles with [67584,4,4] chunks: years of hourly records in small spatial tiles, four workers and retained source/decoded caches. Evidence `docs/evidence/coastal-era5-20261016.json` records acquisition 282.44 s and publication 368.58 s with history reused. `ecmwf-regional-live-20261015.json` records a cached export with zero provider requests, 771.67 s, and a retained 3.33 GB source archive. Those timings do not establish a fresh full-history download in a few minutes. GLORYS's Time Series layout now applies the same efficient long-time access principle.

## Remaining gates

No authentication required for these official public asset reads; no passwords/cookies/tokens accessed. No changes to salinity/current definitions: practical salinity, geographic daily mean components, and spatial mean of native daily-mean-vector magnitudes. No hourly-mean-speed equivalence. Coverage remains 245/463 supported R5 cells in the pilot, including substantial inland gaps; changing layout cannot improve it. No tides in GLORYS.

Before history publication, verify coordinate alignment for both layouts beyond pilot anchors, implement resumable unique-object retrieval and daily row groups, validate representative historical values and metadata stability, and document the 2019 forcing change plus unresolved exact multi-year/interim boundary. Preserve accepted products until complete readback. At the benchmark checkpoint full history was paused; the later authorization and completed run below supersede that checkpoint. No source alternative benchmark was necessary after this exact-resolution speedup.

Official service explanation: https://help.marine.copernicus.eu/en/articles/7969584-copernicus-marine-toolbox-data-access-services . Toolbox is not installed; no authenticated/default credential-discovering command was invoked. The dry-run above is computed directly from actual public metadata and measured compressed objects, not reported as Toolbox `data_transfer_size` output.

## Authorized execution and qualified production boundary

Full history was authorized after the pause: 2009-01-01 through 2026-09-22, 6,474 days. QUID Issue 1.6 (23 November 2023), section V, printed page 50, explicitly identifies July 2021 onward as interim production assimilating NRT in situ, altimetry, SST and ice observations. Accordingly preserve 2009-01-01–2021-06-30 as documented reanalysis, and 2021-07-01–2026-09-22 as documented interim lineage. The current PUM's merged-dataset change does not establish subsequent final reprocessing. Native 2023–2026 filename listings show contemporary run dates, consistent with that production history but not independently proving every day's processing state. No authoritative later consolidation boundary was found. These are documented production regimes, not a claim that every historical value is immutable. QUID: https://documentation.marine.copernicus.eu/QUID/CMEMS-GLO-QUID-001-030.pdf . Keep the independent ERA-Interim to ERA5 forcing boundary at 2019-01-01.

Execution caps: 2 GB total new retained source/staging/output artifacts, 20 GB free-space reserve, four workers, verified unique-object cache reuse. Exact metadata/date/membership and pilot parity gates precede transactional promotion of only the two GLORYS products. Store receipts and source metadata outside public tables. All public schemas remain unchanged.

Lesson: a short-period layout is not a valid full-history cost model when time-optimized storage exists. Inspect both actual layouts and count unique chunks before extrapolating a short pilot.

## Completed authorized run

Published locally 2026-10-29, only the two GLORYS products extended. Full supported range 2009-01-01–2026-09-22: 6,474 days × 463 approved R5 cells = 2,997,462 rows/product. Each metric has 1,586,130 nonnull and 1,411,332 null rows (245 supported cells/day). Public schemas unchanged, 6,474 daily row groups each. All eight other product checksums unchanged.

Measured first run: acquisition 54.605 s; processing 80.984 s; full readback 56.408 s; complete run 197.042 s. New acquisition/coordinate/metadata traffic 66,120,362 bytes; 60 benchmark chunks/26,438,888 bytes reused. This is not a fresh-cache timing: total unique history chunks and coordinates are about 92.54 MB. Eight alternate-layout dates (including 2019 and July 2021 boundaries) added 43,568,062 bytes/82.463 s and matched all 15,000 native values exactly. The complete installed-wheel offline replay took 126.245 s, zero requests, byte-identical products. Peak memory footprint 270,353,320 bytes. Download/processing timings exclude initial research/setup, independent anchors and replay. Final metadata recheck, quality document and anchors bring new transfer to 116,404,913 bytes.

The run retained approximately 0.31 GB including sources, two validated stages, evidence and the quality document, below 2 GB; more than 70 GB disk remained free (20 GB floor). Final publication/checks took 0.334 s. July 2024 pilot values are exact. Source masks/nulls remain unchanged. Current speed range 0–1.407401 m/s; valid zero is retained from source, never used to fill missing cells. Salinity range 10.901212–33.816034 psu.

59 source regression tests pass. Complete wheel replay and independent source comparisons passed. An attempted entire suite from /tmp had two pre-existing checkout-relative config tests fail; the source suite from its required owner directory passes. The final publication gates additionally require anchor evidence and wheel parity. The replayed producer snapshot and explicit publication-only code migration are retained with the run.

Canonical evidence: `.oceanography/glorys-history-20261029/completed.json`, `inventory.json`, `anchor-validation.json`, `wheel-replay-verification.json`, `QUID.pdf` and receipt. The source cache is checksum-bound and resumable; no source deletion or credential access. Previous delivery preserved by the publication journal. No app changes, commits or pushes.
