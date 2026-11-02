# HYCOM history qualification — 2026-10-27

**Decision: do not start full history yet.** Published HYCOM/SalishSeaCast pilots
and SST/chlorophyll history are unchanged. A bounded five-response OPeNDAP
benchmark, native-axis audit and public S3 header check did not establish a
practical faster full run. This is an acquisition/lineage decision point, not an
access denial. No new credentials or accounts were used.

## Provider limits and diagnosis

The [official FAQ](https://www.hycom.org/faqs) requires NCSS requests of at most
one day and one concurrent NCSS connection per IP. The general HYCOM-service
limit is ten connections/IP. The original seven-day timeout used an unsupported
request size; it does not justify repeating larger chunks or increasing NCSS
concurrency. A newly queued benchmark was stopped during its first one-day
request, before any queued multiday/concurrent NCSS requests ran. Its partial
response is not a successful cached source. `coarse.py` now rejects multiday
network calls and splits new acquisition into sequential daily requests. Existing
three-day pilot receipts remain replayable offline only.

The precise server-side reason for the old timeout is unknown without provider
logs. Metadata is usually quick, while native payloads vary widely. DAP response
first chunks arrived in ~0.3–0.4 seconds; completion took 2–106 seconds, indicating
that handshake latency alone does not explain the slow paths. Avoid THREDDS
maintenance at 02:00–03:00 and 12:00–13:00 America/New_York local time.

## Measured bounded benchmark

All DAP requests selected three variables, one 0 m depth, eight samples and only
the study planning rectangle. At most two DAP connections ran concurrently.
Total successful DAP payload was approximately 7.0 MB; none was a global grid.

| Day / experiment | Method | Seconds | Response bytes |
| --- | --- | ---: | ---: |
| 2009-07-01 / 53.X | NCSS NetCDF4, prior preflight | 21.06 | 251,120 |
| 2009-07-01 / 53.X | DAP2 | 39.28 | 1,391,274 |
| 2009-01-03 / 53.X | DAP2 | 28.26 | 1,401,186 |
| 2016-01-03 / 56.3 | DAP2 | 2.12 | 1,401,176 |
| 2019-01-03 / GLBy 93.0 | DAP2 | 105.75 | 1,401,176 |
| 2024-07-01 / GLBy 93.0 | DAP2 | 41.78 | 1,401,176 |

Packed values and coordinates match the overlapping accepted NCSS subsets
exactly. All five DAP payloads passed shape, eight-sample cadence, surface-depth,
finite/range and complete-binary-read checks. DAP uses an uncompressed XDR payload;
its larger transfer is not a change in scientific values. The first comparison
excluded one outer latitude row; parity was checked only on common native cells.

Naive extrapolation remains ~38 hours serial NCSS or ~39 hours with two DAP workers
at the observed mean, before retries and recent per-file overhead. These are not
promised ETAs. Approximate retained payload is 1.63 GB NCSS versus 9.12 GB DAP for
6,507 dates. No request benchmark supports using ten workers as a shortcut.

The official no-account [S3 mirror](https://registry.opendata.aws/hycom-gofs-3pt1-reanalysis/)
covers only 1994–2015. A 64 KiB range read identified a 4,827,801,944-byte NetCDF3
64-bit-offset object. This is not a chunked Zarr/HDF5 regional store. Reading
contiguous latitude strips would transfer many unwanted longitudes; narrowly
reading each row would multiply requests. No complete object was downloaded and
no efficient regional S3 reader has been validated.

## Historical source and gap plan

Serial metadata checks cover all seven reanalysis years, six GLBv analysis
experiments, and GLBy 93.0. They agree on 0 m positive-down surface selection,
psu salinity, geographic east/north m/s and Gregorian time. Those agreements do
not make assimilation/forcing/model versions scientifically homogeneous.

Proposed whole-UTC-day segments, **not final validated fusion**:

| Dates | Source |
| --- | --- |
| 2009-01-01–2015-12-30 | 53.X reanalysis, year-specific receipts |
| 2015-12-31–2016-05-01 | GLBv 56.3 |
| 2016-05-02–2017-01-31 | GLBv 57.2 |
| 2017-02-01–2017-05-31 | GLBv 92.8 |
| 2017-06-01–2017-09-30 | GLBv 57.7 |
| 2017-10-01–2018-01-01 | GLBv 92.9 |
| 2018-01-02–2018-12-04 | GLBv 93.0 |
| 2018-12-05–2024-09-04 | GLBy 93.0 |

Each date must have all eight unique expected timestamps from one experiment.
No hourly splice, silent duplicate removal, cross-source gap fallback or bias
correction is proposed. Noon-start seams can therefore leave null dates.
The proposed 5,726-day plan has 5,399 complete native days and 327 incomplete or
anomalous days. These counts qualify the time axis only, not spatial valid data.
Across 2009–2015, reanalysis has 2,272 complete days out of 2,556 calendar days.
GLBv 93.0 has a duplicate/out-of-order 2018-06-21 06:00 timestamp in both separate
salinity and vector aggregations; the affected day is excluded, not deduplicated.
Actual experiment endpoints differ from some catalog descriptions, so selection
must bind exact native axes rather than infer archive coverage from titles.

## Recent operational lineage still incomplete

ESPC-D-V02 changes model/tidal physics and may substitute older forecast runs;
its detided daily means are not replacements for sampled current speed. The
2024 archive catalog request timed out after 40 seconds and was not retried in
this bounded benchmark. Full 2024–2026 file lineage remains unqualified.

The cached 2026 catalog yields 294 complete eight-sample days, partial March 4
and 6, and no samples on March 5. January 1 needs previous-year files; October 26
is trailing partial coverage. These are filename-derived availability checks,
not full source-value certification. Exact October 25 12:00 metadata samples for
all three groups confirmed 0 m, psu/east/north units and matching valid time.
Their calendar is `standard` (equivalent to Gregorian for these modern dates).
No recent native arrays or seam-overlap values were acquired for this audit.

## Resume requirements

A future run should freeze per-date experiment/file/issue/lead selection and exact
metadata hashes. Use one day per request, one NCSS connection or at most two
measured DAP workers; retain checksummed responses/checkpoints, process one day at
a time, and write monthly checkpoints with date-clustered final Parquet groups.
Proposed caps: 20 MB/response, 120-second wall deadline, two retries with 60/180s
backoff, 12 GB cache budget and 10 GB disk floor. Transport errors, partial streams,
checksums and timestamp mismatches stay failed/pending, never valid null days.
Native incomplete days are explicitly null in the internal plan. Preserve public
pilots until complete readback and exact overlapping-row checks pass.

Before bulk work, resolve recent archive access/lineage, test numerical overlap
at selected experiment seams, and establish an acceptable multi-day runtime or
separately qualify another source. Copernicus GLORYS would require existing user
login and a distinct daily-vector/speed definition; no credentials are configured
and no account/access changes were attempted.

Validation: 41 toolkit tests and six outside-checkout installed-wheel coarse tests
passed after the provider guard change; `git diff --check` passed. This audit does
not validate a complete historical producer or authorize claiming full coverage.
