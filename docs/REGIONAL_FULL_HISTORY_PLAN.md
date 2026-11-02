# SalishSeaCast full study history qualification — 2026-10-31

**Implementation update:** the user subsequently authorized the full historical
gap-only run, independent monthly hourly salinity/current acquisition and normal
bounded source eviction with final daily H3 retention. The implemented
[`regional-history` pipeline](REGIONAL_GAP_HISTORY.md) supersedes the proposed-runner
and assessment-only cleanup statements below for newly generated inputs in this
run. Earlier pilot/benchmark/2024 archives remain excluded from cleanup. Local
checks passed 68 tests and an outside-checkout regular-wheel replay of three pilot
days, 28 historical salinity days and seven current days, with exact selected-cell
parity. The frozen live plan covers 2009-01-01–2026-10-30, 214 month slices and
502 R6 gap cells. The user paused acquisition to investigate HOTSSea, then
explicitly resumed the same SSC workflow on 2026-10-31. Twelve 2009 salinity
months passed pre-resume checksum verification; the restarted worker continues
salinity followed by currents. Full acquisition and publication are not completed.
The later user-authorized two-request implementation passed 75 tests and native
parity, then measured 1.864× normalized salinity throughput in a short live trial.
The supervisor resumed with two requests sharing the same 2 GB source cap; sixteen
original salinity checkpoints were preserved, and benchmark work added needed
H3 months. Current U/V monthly functionality passed, without a matched current
speedup claim. See the [current workflow and timing qualifications](REGIONAL_GAP_HISTORY.md#concurrency-assessment--2026-10-31).
The following sections retain the earlier feasibility/benchmark evidence.

Requested scope: surface currents and reference salinity for the full approved
study window, 2009-01-01 through available complete UTC days (configured end
exclusive 2027-01-01). The user prefers larger acquisition batches where faster,
and selected final daily H3 products with a bounded temporary source cache rather
than a retained full native hourly archive. This is a measured implementation
plan, not a completed backfill or an authorized cleanup batch.

## Current scope: separate, gap-only acquisition — 2026-10-31

The user clarified that salinity and currents can proceed separately and the
pull only needs to fill GLORYS gaps. Use the fixed spatial null footprint from
the checked GLORYS history, not the entire SalishSeaCast domain or every coarse
GLORYS cell in a narrow passage. Retain the full study time window within that
footprint, 2009-01-01 through available complete SalishSeaCast days. Do not expand
the footprint to the whole region just because GLORYS delivery currently ends
2026-09-22. Future dates remain pending availability.

- **Salinity:** qualify and use precomputed daily salinity if provider access and
  date completeness are established; it need not wait for current-speed work.
  At the same footprint this has 24 times fewer time samples than hourly input,
  not a measured 24-fold transfer speed-up. Daily provider access remains
  unverified. Qualification also requires units/depth/masks and complete-hour
  missingness parity: a daily mean alone does not prove 24 valid hourly inputs.
  The available fallback is hourly salinity only over the gap target.
- **Currents:** independently acquire native hourly U/V for the same targets,
  with the adjoining staggered faces needed for collocation. Retain all 24 hourly
  intervals for daily components and mean hourly-vector magnitude.
- **Delivery:** retain separate source identity, dates, units and metric meanings.
  The source-specific R6 product contract is preserved. A consumer gap mask can
  prefer existing GLORYS support and use the supplemental source only where
  qualified; no practical/reference-salinity or current-speed numeric mosaic was
  created by this planning change.

An offline native-centre plan selects 502 of the 960 pilot-supported R6 cells.
There are 22,104 accepted native T-centres directly in 104 of the 218 missing
GLORYS R5 cells. Preserve all 29,379 accepted native centres of those selected
R6 cells, including 7,275 boundary-support points, so selecting gap cells does
not silently change their existing within-cell means. Classify native coordinates
directly into R5; an R6 parent-key test is not a geometric gap test. This is
potential support based on geometry/pilot checks, not historical value validation
or complete coverage of the 104 coarse cells. Unreachable gaps remain null.

ERDDAP requests rectangles, so source transfer includes rectangular overfetch in
addition to required points. Two sized candidates illustrate the tradeoff:

| Spatial plan | Hourly values versus the previous full native grid | Current U/V requests for 18 yearly slices | Largest yearly single-field data payload |
| --- | --- | ---: | ---: |
| 8 horizontal strips | ~65% (about 35% fewer) | 288 | 1.49 GB |
| 32 adaptively split rectangles | ~32% (about 68% fewer) | 1,152 | 0.775 GB |

These float32 data payloads fit below the observed 2 GB NetCDF limit with header/
axis headroom. This establishes size feasibility only. Subsequent limited live
checks below measured one monthly tile and did not qualify yearly or coalesced
bounding-box acquisition. Keep requests serial and select month/year batching by complete
transfer measurements, not point-count scaling. The earlier 144 GB / 47–52 hour
estimates below are a **full-grid baseline**, not the revised gap-only forecast.
The 3–5 GB work budget and 2 GB source-cache cap remain conservative provisional
limits; output row identity stays unchanged and no smaller final-file estimate
is asserted merely from selecting fewer nonnull cells.

[Offline plan, exact rectangles and input hashes](../../../Reports/oceanography-history-2026-10-31/gap-only-plan.json)
and [replay script](../../../Reports/oceanography-history-2026-10-31/plan_gap_only.py)
record complete point/face coverage and non-overlapping core-rectangle checks.
The existing runner still requires subset-index readers, independent salinity/
current checkpoints, per-day validation, recovery and acceptance before a full
run. No source download, deletion, historical extension or publication occurred
in this scope revision.

## Subsequent live gap-subset checks — 2026-10-31

Fresh public catalog/search responses confirmed 53 datasets, with no listed
daily historical salinity product or direct-file route for the current v21-11
physics/current entries. The keyword `daily` can mean updated daily, including
rolling forecasts; it does not establish daily averages. Provider-side daily
physics remains an unverified external-access route. Its extraction configuration
includes other variables and does not select only the surface, so whole native
daily physics downloads must not be presumed faster than a surface-only extract.

Three serial U transport attempts used all native hourly intervals and the
accepted surface depth:

| Request | Result | Elapsed | Actual compressed payload |
| --- | --- | ---: | ---: |
| 2009, largest adaptive gap core plus U faces; estimated 772.0 MB field data | Read timeout before headers | 600.22 s | None |
| January 2009, same 22,032 native points / 744 hours | Complete, checked against source | 206.12 s | 24,946,705 bytes |
| January 2009, one gap bounding box / 313,950 points; estimated 934.3 MB field data | Connection reset before response; cause unknown | 28.92 s | None |

The completed month waited 194.65 s for headers, decoded to 65,580,808 bytes and
passed exact UTC/grid-index axes, depth, units/convention and length checks.
Its first complete day matched the retained full-grid source bit for bit.
Yearly size feasibility did not translate into a completed request within the
ten-minute initial-response budget. The bounding-box failure does not establish
that layout is inherently unavailable or slower. No revised whole-history
runtime/wire estimate or globally fastest spatial plan is supported. Source
load/cache effects are unknown; a 68% point-count reduction is not a measured
68% runtime reduction. Yearly V was skipped after U failed; no full live paired
monthly U/V cohort was acquired in these checks.

Separately, a retained seven-day April 2009 offline replay exercised every
adaptive rectangle and staggered U/V face margin. Hourly geographic vectors and
daily H3 east/north/mean-hourly-speed values were bit-exact to the full-grid
calculation for all 502 selected R6 cells, with all other candidate rows null.
This qualifies the scoped calculation on that week, not full historical values
or live monthly paired acquisition.

Monthly hourly subsets are the demonstrated access fallback for independent
salinity/current qualification. Measure/coalesce requests before a full gap-only
run rather than launching the many-rectangle layout on assumed proportional
savings. Final-daily retention and bounded caching remain selected; daily source
access, a production subset runner and preserving acceptance remain outstanding.
No full backfill, provider contact, source deletion or delivery promotion occurred.
See [live findings and replay](../../../Reports/oceanography-history-2026-10-31/GAP_LIVE_CHECK.md)
and [hashed receipts/limits](../../../Reports/oceanography-history-2026-10-31/gap-live-check.json).

## Live date availability

All three official v21-11 datasets advertise and return complete, identical hourly
axes from 2007-01-01 00:30 UTC through 2026-10-30 23:30 UTC, checked 2026-10-31.
The study intersection has 156,288 hourly intervals / 6,512 complete UTC days.
There are no duplicate, missing or irregular axis timestamps in this census.
The last 62 dates in the configured 2026 window are not yet available; they must
not be inferred, relabelled or represented as successfully downloaded null days.
Time-axis availability is not full native value acquisition/validation.

Official datasets:

- [Hourly physics / reference salinity](https://salishsea.eos.ubc.ca/erddap/info/ubcSSg3DPhysicsFields1hV21-11/index.html)
- [Hourly model-grid U](https://salishsea.eos.ubc.ca/erddap/info/ubcSSg3DuGridFields1hV21-11/index.html)
- [Hourly model-grid V](https://salishsea.eos.ubc.ca/erddap/info/ubcSSg3DvGridFields1hV21-11/index.html)

## Acquisition batches and current evidence

Batching means downloading all hourly samples for a month, not substituting
monthly-mean physics. Preserve the ~0.5000003 m surface selection, native grid,
staggered-face halo, collocation/rotation, reference salinity g/kg, complete
24 hourly-mean intervals and speed-before-daily-averaging definitions in REGIONAL.md.
Do not spatially thin the source or substitute magnitude of a monthly/daily mean.

Live salinity NetCDF requests for 2009 and the full available study period both
returned HTTP 413 with explicit `.nc 2 GB limit` errors, in approximately 2.4 s.
One calendar month fits this limit (~0.96–1.06 GB decoded per variable). A January
2009 31-day request timed out before headers at 90 s; a separate February 2009
28-day request completed in 266.58 s, including 244.11 s before response headers.
It returned 196,173,753 actual gzip wire bytes / 960,717,456 decoded NetCDF bytes,
672 complete hourly surface fields. The failure is not a null source month.

Official OPeNDAP/DAP2 is also being qualified to test whether a streamed response
reduces the initial delay observed with NetCDF; its server-side cause is unknown.
A one-hour full-grid response
matched the retained 2009-01-01 salinity field bit-for-bit, with exact time, grid
and depth validation. A complete March 2009 DAP2 salinity transfer subsequently
took 352.26 s / 216,215,986 compressed bytes for 31 days: 11.36 s/source day,
versus 9.52 s/day for February NetCDF. It began transferring promptly but did
not show a throughput advantage. These different-date samples are not a
controlled benchmark or proof of a uniform format speed ratio.

A sequential gzip/NetCDF reader also checked all 672 February hourly salinity
fields and their exact UTC axis, surface depth and units, without loading a
monthly array. Its per-day spatial summaries remain analysis evidence only;
the paired-current monthly reader and production runner still need implementation.

A complete April 1–7, 2009 NetCDF cohort (salinity, U and V) took 180.29 s total
(67.43 / 59.25 / 53.60 s) and 153,990,895 compressed wire bytes. Its salinity rate
was 9.63 s/source day, close to the monthly sample. An hourly streaming prototype
verified all three exact time axes, depth/grid/units, geographic rotation, complete
daily intervals, native support and producer identity/range/vector checks. All
seven days had 960 supported R6 cells for each metric. Processing took 2.68 s,
with 550,010,880-byte whole-process peak RSS on this Mac. This is not a general
runner, native monthly-current acceptance or installed-wheel replay.

Recommendation: calendar-month NetCDF requests, three serial requests per month,
preserving every native hourly sample. There are 214 available month slices /
642 field requests, versus 19,536 daily requests. Use a longer initial-response
timeout (e.g. 600 s) and a bounded total deadline; a 90 s header timeout rejects
viable monthly requests. Weekly chunks can be an explicit recovery fallback,
not an assumed default. Full-month U/V throughput has not been separately measured.
The measured all-field week extrapolates to 46.6 acquisition hours; monthly salinity
times three fields extrapolates to 51.7 hours. Plan roughly 2–3 days plus service
variation, retries and final acceptance, not a guaranteed completion deadline.

The provider's [griddap guidance](https://salishsea.eos.ubc.ca/erddap/griddap/documentation.html)
asks users to run one script or curl command at a time. Qualification and the
proposed backfill use one active request. Direct `/files/` access for the salinity
dataset returned 404; no efficient public cloud/time-series archive was established.
Do not infer that every alternative access method is unavailable.

## Storage and replay policy selected for assessment

The available study requires about 670.3 GB of decoded native float32 fields
(surface salinity, U and V only). Retained gzip observations from winter 2009 and
seven summer 2024 dates extrapolate to ~143.6–144.2 GB before safety headroom.
Hourly lossless Blosc/Zstd byte/bit-shuffle trials did not reduce this to a safely
fitting local archive. Approximately 84 GiB was free during qualification.

The two final daily H3 products have 15,804,624 rows each at approved R6 membership.
Pilot-scaled Parquet size is ~0.34 GB combined; budget 0.5–1 GB until measured on
longer output. Allow about 3–5 GB total working disk including bounded sources,
checkpoints, final assembly and metadata; this fits the observed local free space.
Approximately 144 GB still crosses the network with bounded caching; it changes
retention, not the number of native hourly values acquired. These are estimates,
not historical delivered artifacts.

Proposed configuration (not yet implemented or executed):

- One explicit temporary work root, e.g.
  `.marinecast-work/oceanography/salishsea-history-2009-2026/`, outside Data.
- `sources/`: at most one completed source cohort, normally three compressed
  monthly salinity/U/V requests, plus one capped partial response; target 2 GB cap.
  Check cache size and retain a 20 GB free-disk floor before/throughout transfer.
- `days/`: validated daily checkpoints with all 2,427 registry keys, metric nulls,
  values, source cohort hashes and request/time/units/grid provenance. Process one
  hourly slice at a time; do not load three monthly arrays into RAM.
- `receipts/` and `plan.json`: retain source URLs, metadata snapshots, both wire and
  decoded hashes, dates, dataset versions, code/config/geometry fingerprints,
  availability census, failures and completion state. Daily files are small enough
  to retain while final Parquets are assembled/read back.
- Release only complete, checksum-verified output after full date/member/value/null
  readback, accepted July pilot parity, source support checks and consumer acceptance.
  Keep existing public pilots unchanged until explicit promotion.

Sources become disposable only after their validated replacements and replay
metadata are checked. The workspace AGENTS requires specific approval of exact
task-owned cleanup paths and estimated bytes before permanent deletion; the user's
bounded-cache preference requests this assessment and does not execute a cleanup
batch. Existing raw sources, seven-day checkpoints and source references remain.
Without the hourly archive, offline reproduction of all hourly calculations is
unavailable; reprocessing requires reacquiring the exact source requests, whose
provider values or accessibility may later change. Receipts do not replace data.

## Required implementation before a full run

The existing `regional_history` runner is frozen to 2024, one-day acquisition,
40 MB decoded responses and permanent retention up to 10 GB. It cannot be pointed
at 2009–2026 or monthly inputs unchanged. `regional_streaming.temporal_means` also
expects exactly one day's native time axis.

A new general history workflow needs a frozen availability/chunk plan, streaming
month readers, source-cohort completion and recovery, bounded eviction with its
explicit cleanup authorization, historical support/range checks, day checkpoints,
and history-preserving catalog promotion. Transport/parse/hash failures stay
pending; they do not become successful null months. Test multi-day/month boundary
handling, leap years, partial latest months, interrupted cohorts, disk/cache caps,
pilot parity, units, vector rotation and source preservation. Run affected tests,
full toolkit suite and outside-checkout installed-wheel replay before acquisition.
Native monthly/seasonal value validation and full application acceptance remain
separate from the current date-axis and transport benchmarks.

Local workspace evidence (outside a standalone clone):
[qualification receipts, scripts, availability and estimates](../../../Reports/oceanography-history-2026-10-31/).

## Alternative-product screening — 2026-10-31

**2026-11-01 follow-up:** the user requested verification of pasted bulk-archive
advice while the SSC run remained paused. UW intermediate SSM direct objects for
the first days of 2013, 2014 and 2025 were accessible and honored byte ranges.
Each sampled daily file is ~306.46 MB, with 24 hourly records, 16,012 tracer nodes,
25,019 current elements and 10 sigma layers. A top-layer salinity trial fetched
1.537 MB in 13.09 s wall time (24 fresh serial ranges). Surface U/V totals
4.804 MB/day; 46 fresh ranges took 24.93 s, excluding two reused samples. This
does not demonstrate a speed advantage over the existing monthly SSC pipeline.
Year calendars contain daily objects, not verified annual/monthly bundles;
2009–2012 and 2026 remain unestablished. Actual availability across all dates was
not censused because bucket listing returned 403.

SSM adoption also requires distinct qualification: local/Pacific daily file
boundaries cross UTC days; top sigma depth varies with bathymetry and sea level
(~0.02–9.92 m at zero sea level across the sampled mesh); salinity is labelled
`1e-3`, not SSC reference g/kg; current vectors use elements rather than tracer
nodes. Narrow-passage/gap support and hourly averaging semantics are unverified.
The actual NOAA SSCOFS NCEI catalog lists 2024–2026, not a 2009 hindcast. Ecology's
annual profile files are validation candidates, not daily gridded substitutes.
Most pasted surface/monthly/H3/cache recommendations are already implemented.
No replacement, run resumption or Data product change occurred. See
[bounded native evidence and qualifications](../../../Reports/oceanography-bulk-archives-2026-11-01/FINDINGS.md).

The user subsequently identified NOAA's SSCOFS S3 link specifically. Unsigned
bucket listings under `sscofs/netcdf/` verified 2024–2026 layouts, with sampled
3D nowcast fields of 210,525,170 bytes each. This is a distinct operational model,
not a UBC SalishSeaCast cache. Legacy station dates and latest forecast dates do
not establish complete hourly historical field availability. Direct object
access can avoid ERDDAP subset preparation, but no surface/gap-only transfer-time
benchmark or equivalent scientific product was established. See the linked
report's NOAA S3 subsection and receipts; no field payload was downloaded.

A further SSC-specific bulk/S3 check on 2026-11-01 found a configured monthly
tarball/SSH-rsync workflow to Alliance nearline storage, not a verified public S3
mirror. S3 URLs in the provider's configuration are LiveOcean boundary inputs,
not exported regional SSC history. Authorization, complete retained inventories
and surface-only daily extraction remain provider questions. Separate LiveOcean
daily tidally averaged surface bundles for 2013–2024 were HEAD/range verified:
30.94 GB together, including multiple variables. They exceed the 2 GB cache cap
as whole objects and do not cover the full study window; range-efficient salinity
access and scientific equivalence were not established. No source switch or
bulk download occurred. See [source-level bulk access findings](../../../Reports/oceanography-daily-salinity-speed-2026-11-01/BULK_ACCESS.md).

No faster public replacement was verified that supplies the complete 2009–2026
study period, both daily salinity and the existing current metrics, and comparable
inland/narrow-passage support. This is bounded source screening, not proof that
no other archive exists. Alternative wet masks and actual download rates were
not benchmarked; no replacement or source mosaic was adopted.

| Candidate | Public evidence | Limitation for this delivery |
| --- | --- | --- |
| [LiveOcean](https://faculty.washington.edu/pmacc/LO/data_access.html) | Two ready-made daily, tidally averaged surface files for 2013–2024, listed as 17 GB + 13 GB; salinity and four other scalar fields. The documented hindcast is 2012-10-07–2025-06-20. | Advertised daily extract does not list currents; neither that extract nor the documented hindcast covers the full study period. No identical wet footprint or transfer-time advantage established. |
| [HOTSSea monthly outputs](https://zenodo.org/records/13942109) | 1980–2018 temperature/salinity monthly statistics; surface mean salinity file listed at 75.6 MB. | Monthly salinity context, not the required daily salinity/current products or coverage through 2026. |
| [MULTIOBS surface salinity](https://data.marine.copernicus.eu/product/MULTIOBS_GLO_PHY_S_SURFACE_MYNRT_015_013/description) — checked 2026-11-01 | Daily/monthly 0.125° practical surface salinity; MY 1993–2024-12-15 and NRT 2024–2026-10-25 axes verified. Three bounded native daily samples inspected. | All 22 native centres inside the Puget-water diagnostic rectangle were missing on all three dates; only 3–6 of 502 current gap-target R6 cells had finite native centres directly in GLORYS gaps. Candidate broad background layer, not qualified as the inland SSC substitute; counts are not water-area coverage. |
| [SSM intermediate-grid hindcasts](https://ssmc-uw.org/data-portal/) — checked 2026-11-01 | Portal advertises 2013 onward hourly U/V/salinity. Three daily-object headers and bounded surface ranges verified; 2014 calendar contains 365 unique daily links. Native trial and timing qualifications above. | Neither 2009–2012 nor 2026 was established; no full date census, qualified gap/passage support or speed advantage. UTC boundaries, sigma depth, salinity convention and current support require reconciliation. |
| [NOAA SSCOFS](https://tidesandcurrents.noaa.gov/ofs/sscofs/sscofs.html) | Regional currents/salinity nowcasts and forecasts; cloud, THREDDS and archive links. NOAA [announced operational implementation for September 2024](https://www.weather.gov/media/notification/pdf_2023_24/scn24-77_nos_sscofs_aaa.pdf). | A complete 2009–2026 hindcast was not established; operational output needs issue/lead/valid-time qualification. |
| [ECCC CIOPS](https://eccc-msc.github.io/open-data/msc-data/nwp_ciops/readme_ciops-datamart_en/) | Public hourly forecasts, including a 500 m Salish Sea enhancement. | Documentation describes forecast delivery; a complete public 2009–2026 hindcast and faster access were not verified. |

[LiveOcean's model description](https://faculty.washington.edu/pmacc/LO/how_it_works.html)
documents ~500 m spacing in the Salish Sea; it is the strongest regional-coverage
candidate if the period or required fields are changed. That spacing alone does
not establish support in the specific study passages.

Coarser-product follow-up on 2026-10-31 distinguishes lower spatial resolution
from reducing output H3 resolution. Reaggregating the existing H3 output does not
reduce its source acquisition. Native source strides could reduce transferred
values but may skip the few wet points in narrow passages; a new mask/value
qualification would be required. No stride, sampling change, alternate source or
new metric was adopted during that screening. The user subsequently paused the
authorized monthly hourly run for the detailed HOTSSea investigation below. A
coarser global grid cannot be presumed to restore the inland wet-mask support
missing from GLORYS; that remains a source-mask question.

[PNNL's SSM model description](https://www.pnnl.gov/projects/salish-sea-model/hydrodynamics)
documents the intermediate mesh at 100–350 m in estuaries/bays and 800–3,000 m
in main basins, coarsening farther offshore. It is smaller overall rather than
uniformly coarser than SalishSeaCast, and is a plausible partial-period candidate
that may retain channel detail. This is model-description evidence, not a
verified match to the specific 502-cell gap target or a measured speed advantage.

The [HOTSSea paper](https://gmd.copernicus.org/articles/18/211/2025/index.html)
documents a coarser ~1.5 km grid and unresolved Sechelt, Salmon and Burrard inlets
and Indian Arm. It states raw outputs require contacting the authors; the public
processed product is monthly. It therefore does not preserve the narrow-water
coverage objective merely by sharing a Salish Sea domain label.

## MULTIOBS daily salinity investigation — 2026-11-01

Subsequent 2026-11-01 MULTIOBS assessment used three small native daily salinity
samples while the SSC run remained paused. The sampled water mask leaves central
Puget Sound missing despite global gap-free wording. Practical PSU at nominal
0 m is not SSC reference g/kg at ~0.5 m. The product requires separate MY/NRT
qualification, and its latest verified axis stops five days before the frozen
SSC end. No source was adopted or Data table changed. See the workspace
[MULTIOBS findings and coastal map](../../../Reports/oceanography-multiobs-2026-11-01/FINDINGS.md).

## HOTSSea native-file investigation — 2026-10-31

With the SSC worker stopped, the whole-period public surface salinity file was
downloaded and checksum-verified: 75,643,720 bytes in 144.84 s. It has 468 monthly
fields on the native 299 × 132 grid, January 1980–December 2018; the study overlap
is only January 2009–December 2018. Public v1.02.4 has temperature/salinity
statistics, with no current components or speed file. This monthly timing is not
a daily/hourly acquisition benchmark. No public 2019–2026 extension was verified.

The native salinity mask is stable across all months. Accepted native centres
directly inside GLORYS gaps occur in 427 of the existing 502 R6 target cells;
75 lack direct support. These are source-centre membership counts, not resolved
channel area or evidence of current support. The file labels surface as 0–4 m
and salinity units as `0.001`; equivalence to SSC's ~0.5 m reference g/kg product
is not established. No numerical blend, interpolation or daily reconstruction
was performed.

The author's pinned RUN203 configuration enables daily and hourly T/U/V, but
hourly vectors are instantaneous and no speed field is declared. Raw historical
file retention/access and any correctly precomputed daily speed need verification
with the authors; daily component means cannot recover mean hourly speed. The
public monthly archive could serve a separately qualified 2009–2018 salinity
context layer, but does not replace the full-period daily products. The SSC run
remained paused during this investigation; the user subsequently explicitly
resumed it with final daily H3 retention and the same bounded source cache.
Detailed map, source links, receipts and
reproduction are in the workspace
[`Reports/oceanography-hotssea-2026-10-31/FINDINGS.md`](../../../Reports/oceanography-hotssea-2026-10-31/FINDINGS.md).

## Added surface variables and larger-cache assessment — 2026-11-01

**Conditional hybrid follow-up:** the user requested faster LiveOcean daily
surface scalars in 2013–2024 plus SSC elsewhere. Bounded actual field reads are
promising (January salt 9.44 s / 30.68 MB), but LO lacks accepted native centres
in 37/502 gap salinity cells and 45/960 SSC-supported oxygen/nitrate cells. SSC is
still needed there in the LO years. Complete hybrid speed and temporal-support
acceptance are unresolved; no source switch/resume occurred. See the
[hybrid qualification and remaining work](REGIONAL_HYBRID_PLAN.md).

The subsequent user-authorized standalone LO leg completed on 2026-11-01:
2013–2024 source-specific salinity/O2/nitrate final H3 Parquets were verified,
and owned raw/month/qualification intermediates removed. The mixed-model
selector/SSC fallback remains separate; the SSC history stays paused with all
50 checkpoints preserved. See the [implemented LO workflow and dated completion](LIVEOCEAN.md).

The user selected daily surface oxygen/nutrients across **all supported study
waters**, separately from the existing salinity/current gap supplement. SSC hourly
physics, chemistry and biology metadata each advertise 2007-01-01–2026-10-31;
this is endpoint availability, not proof of every historical record. Oxygen can
share a chemistry query with DIC/alkalinity; nitrate/ammonium/silicon share biology;
temperature/density share salinity's physics dataset. Cross-dataset fields and
U/V require separate requests. No new H3 producer or full acquisition is implemented.

One full day of grouped nitrate/ammonium/silicon matched separate native queries
bit for bit. Grouped time 24.91 s versus 26.58 s summed singles was not a matched
performance trial. Oxygen separately took 12.75 s. Provider configs also define
daily chemistry/biology means, but public access and full retention are unverified.

A proposed 10 GB local aggregate cap does not change the ~2 GB provider NetCDF
limit, 1.25 GB local decoded-response limit, or two-request concurrency. Existing
measured peak generated sources were ~0.45 GB, so increasing the cap alone has no
demonstrated speed benefit. For the new all-study rectangle, one year of one
hourly float32 field is 12.13 GB decoded; three fields for 31 days are 3.09 GB.
Use month-organized subrequests, initially 7–10-day nutrient bundles, rather than
annual HTTP queries. Larger multi-day bundles still require qualification.

The surface-mask assessment found six unsupported candidate points in two northern
R6 cells, also selected by the frozen gap plan. Qualify that impact before adopting
new fields or promoting the affected historical values; do not rewrite checkpoints
silently. Copernicus daily BGC ARCO is easier offshore but coarse (0.25°), and
LiveOcean's ready daily surface extracts cover only 2013–2024. No alternative
establishes matching full-period inland support. The run stays paused at 2 GB,
with all completed checkpoints preserved. See the
[measurements, mask evidence and alternatives](../../../Reports/oceanography-multivariable-2026-11-01/FINDINGS.md)
and [gap-product qualification](REGIONAL_GAP_HISTORY.md#surface-mask-qualification-follow-up--2026-11-01).

## Precomputed daily extract check — 2026-10-31

**Daily/monthly comparison — 2026-11-01:** the user requested a comparison, not
a cadence change. The existing source request already selects surface salinity
only. A fresh monthly-field request at the same enclosing rectangle returned
13 monthly fields (Jan 2009–Jan 2010, due nearest endpoint selection) in 8.364 s,
16.30 MB decoded. Depth and reference-salinity units matched the expected source
metadata. A fresh monthly time-axis read has 237 labels, Jan 2007–Sep 2026.
Monthly input has 12 rather than 8,760 native fields/non-leap year: 730-fold fewer
field bytes, not a measured speedup. It retains grid spacing but loses within-
month temporal variability and cannot substitute for daily or weekly conditions.
Historical 2009 hourly-source receipts sum 3,315.71 s before concurrency effects;
these were not a paired fresh benchmark. Exact month bounds, gap/H3 support,
units, missingness and monthly eligibility require a separate producer contract.
No monthly H3 product was implemented and the historical run stays paused. See
[comparison and reproducible example](../../../Reports/oceanography-bulk-archives-2026-11-01/SALINITY_CADENCE.md).

No publicly downloadable daily bundle was verified for all required fields over
the available study intersection, 2009-01-01–2026-10-30. The configured study ends
2026-12-31; those future dates are not historical availability. The
[public catalog](https://salishsea.eos.ubc.ca/erddap/info/index.html)
lists hourly physics/U/V and monthly physics, with no matching daily historical
products. This is a public-source/configuration check, not a census of the
provider's filesystem; no provider contact or new bulk download occurred.

| Required field | Provider-side evidence | Public/full-period status |
| --- | --- | --- |
| Daily reference salinity | Confirmed daily post-processing configuration: `vosaline`, hourly inputs, `1D` arithmetic mean. | Daily archive profile starts in 2007; every retained daily file and external access remain unverified. No daily catalog entry found. |
| Daily east/north current components | Current archive profile exposes U/V under hourly groups only; configured daily averaging groups are biology, chemistry and physics tracers. | No current v21-11 daily U/V extract or complete archive verified. Earlier-version notebook references to daily U/V do not establish this archive. |
| Daily mean hourly speed | No corresponding speed field or daily speed extraction found in the inspected current output/averaging configurations and archive profile. | No downloadable full-period extract verified. Daily components cannot recover this metric. |

The provider's
[daily physics extraction configuration](https://github.com/SalishSeaCast/SalishSeaNowcast/blob/66020b91dc9df91a7fd0f1a477eddfe172dee68b/config/reshapr/day-average_202111_physics.yaml)
writes day-averaged salinity to its internal `/results2/SalishSea/nowcast-green.202111/`
archive. The
[Reshapr archive profile](https://github.com/UBC-MOAD/Reshapr/blob/3ed056ba77fd2f1a202d23745cb89dfa8e67d2c7/model_profiles/SalishSeaCast-202111-salish.yaml)
describes 2007-01-01 onward and a daily physics filename pattern
`{ddmmmyy}/SalishSea_1d_{yyyymmdd}_{yyyymmdd}_grid_T.nc`. A start date and pattern
are not proof of complete retention. The public
[monthly physics metadata](https://salishsea.eos.ubc.ca/erddap/info/ubcSSg3DPhysicsFields1moV21-11/index.html)
corroborates historical daily processing: it describes monthly values as resampled
from v21-11 daily `grid_T` files, with 237 monthly records spanning January 2007
through September 2026 in the browsed metadata. Monthly values cannot recover the
individual daily values or establish every daily file's completeness.

The native
[hindcast daily-split configuration](https://github.com/SalishSeaCast/SS-run-sets/blob/3127426bc9e2e17774abe99b758dff34b326c182/v202111/file_def_dailysplit.xml)
still outputs salinity/U/V hourly: `split_freq="1d"` partitions files, while
`output_freq="1h"` determines averaging. Its native daily groups contain biology
growth/grazing fields. The separate post-processing step above supplies daily
salinity; it must not be inferred from daily filenames alone.

For parity, speed must remain the daily mean magnitude of collocated hourly-mean
vectors: `mean(hypot(u_hour, v_hour))`, using complete paired wet support and all
24 UTC intervals at the accepted surface depth. `hypot(mean(u), mean(v))` loses
reversing flow. A native daily average of instantaneous model speed also need
not match the magnitude of hourly-mean vectors. Geographic rotation, salinity
units, support and sample parity require validation before adoption.

The remaining provider question is concrete: can they expose the retained daily
surface salinity and either existing or provider-computed daily geographic U/V
plus this exact speed metric, packaged monthly/yearly, for 2009-01-01 through the
latest complete day? Need a dated file inventory, access route, sizes and method/
sample validation before calling that route available or faster. Until then the
bounded monthly hourly-source workflow remains the demonstrated access path.
See [source/configuration evidence](../../../Reports/oceanography-history-2026-10-31/daily-extract-check.json).
