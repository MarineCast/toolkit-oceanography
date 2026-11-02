# Monthly historical SalishSeaCast gap supplements

`oceanography regional-history` implements independent salinity/current history
over the approved study window, intersected with complete source days. It adds
source-specific products for the fixed GLORYS spatial null footprint, preserving
GLORYS and the original full-support SalishSeaCast pilots. Scientific qualifications
in [REGIONAL.md](REGIONAL.md) continue to apply. See the
[feasibility and transport evidence](REGIONAL_FULL_HISTORY_PLAN.md).

**Run status — 2026-10-31:** the historical supervisor resumed with two requests
after implementation, native parity checks and live qualification. All sixteen
pre-upgrade salinity checkpoints were preserved byte-for-byte. Benchmark work
left 21 salinity months and one current month verified, with no full family yet
published. The frozen 502-cell target, 2 GB source cap, 20 GB free-space floor and
final daily H3/lineage retention continue. Salinity precedes currents. The task
work root's `parallel-continuation.json`, `job.json`, `progress.json` and
`transport-state.json` record the active runtime, command, progress and requests.
Earlier pause/resume receipts remain historical. The
[HOTSSea qualification](REGIONAL_FULL_HISTORY_PLAN.md#hotssea-native-file-investigation--2026-10-31)
did not adopt a replacement source.

**Latest status — 2026-11-01:** paused at the user's explicit request, with
49 salinity months through January 2013 and one current month through January
2009 preserved. All 50 completed files matched their receipt checksums. Worker,
supervisor and task-specific awake guard have stopped; automatic resume is off.
The requested four-request trial had not started. Its incomplete edits were
parked in the task work root's `four-request-draft.patch`; source remains at the
validated pinned two-request version. No pause cleanup was performed. See
`pause-20261101.json`, `job.json` and `progress.json` in that work root.

## Products and spatial support

| Product ID | Final daily R6 file | Metrics |
| --- | --- | --- |
| `salishsea-gap-salinity` | `salishsea-gap-salinity-r6-daily.parquet` | `reference_salinity_g_kg` |
| `salishsea-gap-currents` | `salishsea-gap-currents-r6-daily.parquet` | `current_east_m_s`, `current_north_m_s`, `current_speed_m_s` |

Every acquired UTC day retains every approved R6 reporting key, with nulls outside
the target. The present study selects 502 cells. Native T-centres are classified
directly into missing GLORYS R5 cells; R6 parent identity is not a geometric test.
All accepted within-water native points of each selected R6 cell are retained
to preserve its spatial mean. Boundary cells can straddle GLORYS support: consumers
must apply the GLORYS gap mask and retain the supplemental source qualification.

Salinity remains reference salinity g/kg at ~0.5000003 m, not practical salinity
psu. C-grid velocities are collocated and locally rotated to geographic east/north.
Speed is the daily mean magnitude of hourly-mean vectors; native area weights and
complete 24-hour point support are preserved. These products are not a numeric
mosaic or observational/forecast eligibility certification.

## Acquisition, recovery and retention

**Retained-source sizing — 2026-11-01:** retaining every successful surface-hourly
source subset over the frozen 6,512-day window would total approximately 44.45 GB
compressed salinity plus 94.31 GB compressed U/V, or **138.76 GB (~140 GB)**.
Salinity uses 1,464 disjoint sampled days at the exact acquisition footprint;
current compression is extrapolated from January 2009 only and may vary by
season/year. Float32 fields alone would occupy ~587.90 GB decoded, excluding
headers/axes. These are current enclosing-rectangle surface subsets, not complete
3D SSC archives. Existing checkpoint sizes project roughly 0.23 GB for both final
daily H3 tables before companions; final sizes are unverified and the current
projection uses one sampled month. See
[receipts, denominators and size calculations](../../../Reports/oceanography-daily-salinity-speed-2026-11-01/storage-estimate.json).

The cap bounds concurrent temporary storage, rather than total acquisition.
Removing the cap alone does not disable source eviction or establish faster
downloads; two measured monthly fields total roughly 0.4–0.45 GB compressed.
No retention rule, cache cap, checkpoint or paused-state change was made by this
sizing check.

**Download footprint clarified — 2026-11-01:** gap-only selection restricts the
retained H3 metrics, not the downloaded arrays to isolated gap points. The frozen
plan downloads one enclosing native-index rectangle per month/field: T indices
`y=1..897, x=38..386`, plus the adjoining U/V faces. That is 313,053 positions,
87.59% of the full 898 × 398 grid's index positions, to retain 29,379 accepted
native T-centres for 502 selected H3 cells. This percentage includes land/masked
positions and is not water-area coverage. There is no individual request per H3
cell, and the earlier adaptive multi-rectangle proposal is not the active runner.

Each month requests surface salinity, U and V separately, keeping every hourly
record. The 214-month plan therefore has 642 nominal field requests before
retries/reuse; two may overlap under the shared 2 GB cache cap. A small final H3
file does not imply a small native source request. For the latest completed
January 2013 salinity request, the retained receipt records 331.10 s total,
269.50 s before response headers and 209.72 MB compressed (931.66 MB decoded).
Waiting for the response dominated that sample; provider queueing versus read/
subset/compression work was not separately measured. These are historical
request timings, not an updated completion forecast. The run remains paused.

The pipeline freezes complete, matching native hourly time axes and the available
last complete UTC day. Future requested dates remain outside acquired coverage.
Each source checks exact times/indices, time origin/calendar, depth, variable
units/convention, response length, gzip completion and hashes. One coalesced
native-index bounding box contains the target; U/V include their adjoining faces.
Rectangular overfetch is required by this access route. Gap-only describes final
support, not a promise that all transferred native points are GLORYS gaps.

Optional retained sources are reused only when their native extent contains the
required rectangle. Valid narrower archives are preserved and skipped, allowing
a full-support request; covering sources still require every time/depth/unit/grid
check. The January U live trial exposed and corrected the earlier narrower-seed
selection failure.

Requests are monthly, with three bounded attempts before weekly
recovery of failed multiweek acquisitions. No hours are thinned. Initial timeout
is 600 s, response wall cap 1,200 s, compressed cap 450 MB and decoded cap 1.25 GB.
Failures stay pending rather than becoming all-null output. Individual invalid
native points are excluded for their whole day; a wholly unsupported target day
fails checkpoint validation. Salinity and currents have independent checkpoints
and publication. With both selected, one worker finishes salinity then currents.
Three passes retry pending cohorts with five-minute backoff; unresolved work exits
nonzero with resumable state. Contract/checksum/disk errors need attention.

`--requests-in-flight 2` enables a two-thread source scheduler. Salinity overlaps
adjacent months; currents acquire both U/V faces concurrently and can prefetch the
next pair during the current cohort's serial H3 reduction. Families still run
salinity then currents. Default concurrency is one. At most one following monthly
cohort is scheduled; verified following checkpoints are not downloaded again.
All checkpoint, progress and catalog writes stay on the coordinating thread.

Both requests share one 2 GB source budget. Each reserves its full 450 MB response
cap before HTTP starts; unbuffered writes atomically exchange reserved capacity
for actual cached bytes. Completed sources, failed partials and all active
reservations count against that budget. Capacity/disk-floor failures stop growth.
`transport-state.json` records active requests and peak cache/request counts.
Vector partners are drained before weekly fallback, retaining unused successful
face provenance until verified H3 replacement. Shutdown cancels queued requests
and waits for active bounded HTTP reads before releasing the exclusive run lock;
an in-progress response-header wait can therefore delay graceful shutdown.

Use a dedicated work root outside Data. Source cache cap is 2 GB, free-space floor
20 GB and provisional peak work budget 3–5 GB. Readers hold one hourly slice per
variable; decoded monthly arrays are never staged. Each H3 month checkpoint has
daily row groups and complete identity, null-mask, range, paired-vector, vector-
inequality and checksum readback before generated source eviction.

The user's 2026-10-31 instruction authorizes normal bounded-cache eviction for
this new run. Only registered task-created `sources/` payloads with verified H3
replacements are evicted; failed partial transfers are disposable. External seeds,
pilot, benchmark and earlier 2024 archives are never deleted. Ownership receipts
retain exact paths and eviction proofs. `--reuse-cache` verifies retained sources
by reference without copying. Corrupt checkpoints and lost complete-source
receipts stop recovery rather than silently discarding uncertain state.

Final assembly compares every daily partition with its checkpoint. Explicit
`--publish` adds the final Parquet and required `*-lineage.json` companion under
the shared publication lock, then atomically commits the catalog. Conflicting
accepted outputs are refused. Verified final delivery replaces this run's H3
month intermediates, which are then removed. Small plans/progress/receipts remain.
Lineage retains dates, URLs, retrieval times, wire/decoded hashes, availability,
study/geometry/GLORYS bindings and producer/dependency versions. Exact offline
hourly replay needs reacquisition after native payload eviction; providers can revise.

## Run and resume

### Local Mac sleep guard — checked 2026-11-01

The authorized task supervisor starts `caffeinate -ims -w WORKER_PID` for each
download worker and records the guard PID/command. Its idle-system and disk-sleep
assertions last only while that worker is alive; the stronger system-sleep
assertion applies on AC power. Keep the Mac connected to power with the lid open
for continuous acquisition. Overnight deep-idle/lid sleep interrupted the earlier
idle-only guarded run. The process recovered after waking without a restart,
and the live guard was replaced with the stronger scoped command. Completed
checkpoints, the pinned scientific producer, two-request scheduler and shared
2 GB source cap remain unchanged. No permanent power-setting change is needed.

At verification, 35 salinity months (through November 2011) and one current month
were complete. All 36 completed files matched their saved receipt checksums.
See the task work root's `wake-recovery-20261101.json` for the guard and recovery
evidence; later progress is in the usual live state files.

### Invocation

Install the toolkit and provision approved study and geometry inputs. Example
paths in the grouped workspace:

```sh
oceanography regional-history \
  --study config/study.v1.json \
  --pilot Toolkits/toolkit-oceanography/.oceanography/salish-pilot-20261027 \
  --output Data/Oceanography \
  --root .marinecast-work/oceanography/salish-gap-history-2009-2026 \
  --reuse-cache Toolkits/toolkit-oceanography/.oceanography/salish-history-qualification-20261031 \
  --publish
```

Omitting `--publish` stages only. `--prepare-only` freezes availability/target
without field acquisition. `--family salinity` or `--family currents` selects one
family. Optional `--start`/`--end` restrict dates within the study; default is the
whole requested study window. `--limit-months N` supports bounded qualification.
`--offline` requires an existing plan and retained matching inputs/checkpoints.
Use `--requests-in-flight 1` for serial operation or `2` for bounded prefetch;
`execution.json` records the selection independently of scientific support.

Resume with identical requested dates, code/dependency versions, geometry and
GLORYS bindings. Changed inputs are refused. Verified months/final families are
skipped. `progress.json` records status, interval, completed month counts and cache
bytes; `needs_attention` identifies a condition requiring repair. Use a pinned
installed bundle for long runs. A new source-availability extension needs a new
explicit preserving plan; the current run never advances silently into future dates.

A deliberate producer upgrade can use `--upgrade-plan-from SHA256`, where SHA256
is the exact prior `plan.json` file checksum. It refuses geometry, source, dates
or dependency changes and any already-published family. Every retained month is
read back and checksum-verified, and the exact original plan is archived before
the updated code binding is written. Final lineage includes the producer transition
and hashes/code attribution of preserved checkpoints; new receipts identify their
producer. Repeated upgrades retain each checkpoint's original attribution from
its receipt or prior transition ledger. This flag authorizes a code transition, not scientific equivalence:
run the required native parity checks before use. Normal resume still refuses
unapproved code changes.

## Concurrency assessment — 2026-10-31

### Daily salinity acceleration investigation — 2026-11-01

**Recommended next execution scope:** finish daily salinity first with the
validated two-request monthly transport and `--family salinity`, preserving the
49 salinity plus one current checkpoints. The frozen 214-month plan has 165
salinity slices left. The last uninterrupted 12 checkpoint-completion intervals
averaged 152.97 s/month, giving a conditional ~7.01 h remaining; budget 8–12 h as
a planning allowance, not a service guarantee or confidence interval, excluding
currents. New source gaps, server stalls, sleep and final processing can extend
it. Provider daily extracts remain a possible future acceleration rather than
a dependency for completing the demonstrated run. No source/transport switch,
launcher change or resumption occurred. See
[decision, source comparison and exact timing calculation](../../../Reports/oceanography-daily-salinity-speed-2026-11-01/RECOMMENDATION.md).

The user requested daily-preserving acceleration research while the historical
run stayed paused. Two seven-day AB/BA comparisons of gzip NetCDF and gzip DAP2
binary preserved every hourly field and native support. Binary started responses
in 0.87–1.50 s but did not give a reliable total-time advantage: totals across
both periods were 131.93 s binary versus 120.50 s NetCDF, with the second request
faster in both orders. Server/cache effects remain uncontrolled. Exact source
bytes/axes matched; the installed producer reproduced all 14 daily H3 partitions
and 33,978 rows, values and nulls exactly.

Two spatial rectangles saved 10.26% of array positions but only 0.586% of wire
bytes in a later same-week trial. With two concurrent tile requests, cohort wall
time was 48.93 s versus 42.59 s for the earlier full box. This did not establish
a tiling advantage. Geometry-only 32-tile sizing saves 64.05% of positions, not a
verified transfer-time reduction, and multiplies request count. All candidates
preserved the exact frozen 29,379-point support.

The highest-potential remaining route is the provider's configured daily physics
salinity output, externally unverified. A daily surface route has 24 times fewer
input fields than hourly acquisition, not a measured 24-fold speedup; full
inventory/access, complete-hour eligibility and native/H3 parity are required.
No provider contact, runtime/plan upgrade, new H3 delivery or resumption occurred.
The two-request production transport and all 50 completed checkpoints were
preserved. See [bounded trials and provider access question](../../../Reports/oceanography-daily-salinity-speed-2026-11-01/FINDINGS.md).

The initial assessment of twelve completed monthly salinity
receipts found median total time 278.90 s, median time to response headers 255.87 s
and median compressed size 209.1 MB. These separate medians indicate substantial
response-start delay, not a measured breakdown for one representative request.
These motivated the subsequently user-authorized two-request implementation above.
Live serial/parallel benchmarking is required before claiming a speedup; the
provider may serialize source work.

Do not launch a second copy against this work root: the exclusive run lock protects
checkpoints, progress, cache ownership and publication. Enabling concurrency needs
a coordinated scheduler, one aggregate 2 GB cache budget with capacity reserved
before requests, collision-free progress/receipt writes, and bounded failure and
shutdown handling. Keep scientific reductions and final readback unchanged. A
trial should compare verified completed months per wall hour with serial receipts,
and fall back on throttling, increased failures or absent throughput improvement.
On 2026-10-31, 75 toolkit tests passed and the final regular installed wheel reproduced
the three-day pilot, 28 historical salinity days and seven historical current days
exactly. Scientific spatial/reduction/assembly function ASTs match the prior wheel.
The serial worker was stopped with sixteen salinity months preserved for an
explicit producer upgrade and live timing trial. See the workspace
[`Reports/oceanography-parallel-2026-10-31/`](../../../Reports/oceanography-parallel-2026-10-31/benchmark.json)
for phase status, preserved-checkpoint checksums and measured results. Implementation,
local/native validation, live performance and full historical completion remain
separate states.

The completed live test measured normalized salinity throughput **1.864×** serial:
two overlapping months (62 complete day-fields) took 318.96 s; fresh serial June
and September (60 day-fields) totalled 575.39 s. The interrupted May request was
completed but excluded from the final speed baseline because it was likely
warmed. June's baseline excludes small H3 overhead; the other measurements include
readback. Dates, server load and cache effects remain confounders; this is a short
trial, not a full-history ETA. The subsequent final wheel corrects optional narrow
cache selection and repeated-upgrade attribution; measured request scheduling,
budget and checkpoint logic are unchanged.

The corrected monthly U/V trial validated 31 complete days of current components
and mean hourly-vector speed in 259.35 s; one component response was warmed, so no matched current speedup is
claimed. Observed peak request count was two and peak generated cache payload
448,959,023 bytes; each successful cohort returned to zero cached source bytes
after H3 readback. The user-authorized full run resumed at the selected setting
of two, preserving serial fallback. See the
[dated findings](../../../Reports/oceanography-parallel-2026-10-31/FINDINGS.md).

## Surface mask qualification follow-up — 2026-11-01

A bounded oxygen/nutrient assessment found six positive-bathymetry study centres
excluded by the official v21-08 surface T mask, all at native row 897. They fall
in R6 `8628d9297ffffff` (57 candidate centres, 53 surface-wet) and
`8628dba57ffffff` (41 candidate, 39 surface-wet). Both are selected by the frozen
gap plan. All 960 all-study candidate R6 cells retain some wet support; accepted
native centres decrease from 77,097 to 77,091 when that mask is applied.

The existing `regional_history.spatial` support uses positive bathymetry rather
than this source mask. Zero oxygen/nutrients at the excluded points are not valid
wet-water observations. This does not establish the salinity/current error size.
Qualify the two-cell checkpoint impact before reuse/promotion or adoption of new
fields. Preserve the frozen plan and completed checkpoints; a correction needs
the normal producer migration and replay, not silent source-mask substitution or
blanket zero-to-null conversion. The run remains paused and unchanged. See the
[native evidence and assessment](../../../Reports/oceanography-multivariable-2026-11-01/FINDINGS.md).

## Validation

Run `tests/test_regional_gap_history.py`, regional/history/streaming tests, the full
toolkit suite and `git diff --check`. A regular installed wheel outside the
checkout must reproduce the accepted July pilot and retained multiday scalar/
vector cohorts. A first real monthly checkpoint must pass readback and source
eviction before unattended continuation. Full historical acquisition, final
publication and application rendering remain distinct recorded states.
