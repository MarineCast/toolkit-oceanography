# Resolution versus acquisition cost — 2026-10-28

Year-scale acquisition is paused by user direction. No full-year job was started,
queued or scheduled. The July 1–7 benchmark completed with 155,218,121 bytes total
cache (154,863,893 compressed source bytes); July 1–3 sources were reused and
published pilot values matched exactly. Four fresh days required 12 requests and
163.46 seconds combined acquisition/compression: 40.86 seconds/day, extrapolating
4.15 hours for 2024 rather than the earlier one-day 3.4-hour estimate. This is not
an SLA; queueing/cache state/seasonal data size may vary. Offline checkpoint resume
passed without downloads. Published outputs remain unchanged.

## Measured spatial-sampling experiment

Same day (2024-07-04), same full approved R6 registry, same native wet mask, same
24 hourly intervals and surface depth/reference-salinity definition. Candidates
sample every second/fourth T grid point. U and V retain the adjacent native faces
needed for correct collocation; we do not average widely separated faces. U is
strided only in y and V only in x, so current requests are not reduced by stride
squared. Geographic rotation and speed-before-temporal-mean remain unchanged.
Selected-point values were bit-exact with native values before H3 aggregation.

| Source sampling | Decoded bytes/day | Retained gzip/day | First acquisition | Supported R6 cells |
| --- | ---: | ---: | ---: | ---: |
| Native | 102,962,296 | 22,122,638 | 39.17 s | 960 |
| Every second point | 42,915,840 | 9,541,927 | 25.46 s (0.650×) | 929 |
| Every fourth point | 19,403,664 | 4,441,901 | 26.34 s (0.673×) | 874 |

All 2,427 approved cells remain in candidate frames; other values are null. These
are internal benchmark artifacts, not adopted public products. Sampling reduces
retained size by 56.9% / 79.9%, but time by only 35.0% / 32.7%. One-day measurements
cannot establish an exact long-run speed ratio. At these rates a year is still
about 2.6–2.7 acquisition hours, plus processing, retries and validation.

| Metric | Stride 2 MAE / RMSE / maximum absolute | Stride 4 MAE / RMSE / maximum absolute |
| --- | --- | --- |
| Reference salinity (g/kg) | 0.05787 / 0.17390 / 2.74258 | 0.14471 / 0.48205 / 8.41794 |
| East current (m/s) | 0.00707 / 0.01199 / 0.10394 | 0.01676 / 0.02936 / 0.19512 |
| North current (m/s) | 0.00669 / 0.01184 / 0.09024 | 0.01628 / 0.02774 / 0.17131 |
| Mean hourly speed (m/s) | 0.00968 / 0.01887 / 0.18268 | 0.02442 / 0.04795 / 0.46354 |

Errors compare only mutually supported cells; separately, 31 / 86 native-supported
cells are lost. Lost stride-2 cells had 1–4 valid native water centres (median 2),
so losses preferentially affect narrow/partial coastal water support. Stride-4
losses include cells with up to 24 native centres (median 4). Do not report these
lost cells as zero or fill them across land. Full per-cell evidence and explicit
Vancouver/Seattle/Fraser/Discovery Passage/Juan de Fuca probes are retained in
`coastal-comparison.json`; broad-channel agreement does not establish narrow-inlet
accuracy. Largest stride-4 salinity difference: 8.42 g/kg at H3 8628dba57ffffff,
centre approximately 50.6949 N, 125.4827 W. This is not a uniform coast-safe shortcut.

## What consumes time and space

- H3 coarsening changes output cardinality/aggregation, not the underlying hourly
  source requests. It provides little acquisition savings by itself.
- Fresh sampled requests spent about 5.9–6.9 seconds before response headers,
  around three quarters of their total combined time. Client measurements cannot
  separate server calculation, queueing, network setup and intermediate caching.
  Fixed pre-payload delay makes smaller spatial requests yield diminishing speedups.
- Correct raw-stream byte counting on a repeated salinity request measured
  7,126,390 gzip wire bytes native versus 505,208 at stride 4; decoded sizes were
  34,321,104 and 2,168,380. Exact decoded hashes matched retained sources.
  An initial `HTTPResponse.tell()` probe returned invalid zero counts for chunked
  delivery and must not be used; the corrected `wire-comparison-raw.json` is the
  authoritative measurement.
- Those repeated requests returned in 1.19 / 0.28 seconds, much faster than first
  requests, consistent with provider/intermediate caching. Warm single-day timings
  cannot be extrapolated to a fresh historical backfill.
- Streaming local temporal calculations took 0.22 seconds from NetCDF or about
  1.05 seconds directly from compressed source, at 170 / 320 MB peak footprint.
  Computation and H3 output size are not the main measured cost. No service charge
  is involved in these public-source requests; the costs are time/storage/network.

## Recommendation and versioning

Keep native SalishSeaCast for inland detail over a bounded date range. Prioritize
an actually coarser broad source for broad historical coverage rather than silently
degrading the inland source. GLORYS12 daily reanalysis remains a candidate pending
Copernicus access and source qualification; daily-mean-vector magnitude is not the
same metric as mean hourly speed. Public HYCOM is spatially coarse but its previously
measured request/runtime and experiment-transition limits remain unresolved; coarse
source size alone does not guarantee a fast service.

If spatial sampling is explicitly selected, use a distinct source/method version
such as `salishsea-v21-11-surface-spatial-stride2-hourly-v1`, source-separated public
files and external manifest semantics: native-point sampled spatial aggregate,
24-hour mean magnitude, same reference salinity and depth, no interpolation or
cross-land fill, reduced support. Do not replace accepted native products under the
same identity. Stride 4 is not recommended: no observed speed gain over stride 2,
more support loss and much larger coastal errors. No temporal thinning was performed;
any such option requires an explicitly changed metric definition and qualification.

NOAA tide history remains independent and small; previous bounded 2009 source probes
are retained. No full tide-history replacement was promoted during this comparison.
CHS 2009 remains an unqualified empty source response, not historical observation.
No app/source-access/credential changes, permanent deletion or year-scale run occurred.
