# Inner-water history: fast and complete modes

## User-selected modes — 2026-11-01

The user named two acquisition/source-selection modes for inner waters. These
names describe source policy, not measured runtime or completeness certification.
They control source selection in the implemented regional scalar runner,
[`surface-history --mode fast|complete`](SURFACE_HISTORY.md). A mixed-source native
pilot and exact offline replay passed before the user-authorized fast history
launch on 2026-11-01. Full historical completion and a geographic inner/outer
mosaic remain separate from that implementation/launch.

| Area / field | `fast` | `complete` |
| --- | --- | --- |
| Inner-water surface salinity, oxygen and nitrate | LiveOcean on supported cell/dates in 2013–2024; SalishSeaCast elsewhere, including spatial gaps within those years | SalishSeaCast throughout the available study history |
| Inner-water currents | SalishSeaCast; the acquired LiveOcean scalar bundles contain no current components or mean hourly speed | SalishSeaCast |
| Outer-coast salinity and currents | Reuse suitable existing coverage; existing GLORYS12 is the default low-effort source where supported | Same outer-coast policy; this mode does not require SSC-only outer waters |
| Outer-coast oxygen/nutrients | Reuse eligible SSC/LO values if actually retained and supported; otherwise source/coverage qualification remains separate | Same outer-coast policy |

For `fast`, attempt LO first only for the fields, dates and inner-water cells it
supports, then SSC for remaining eligible cell/dates. For `complete`, do not use LO
to fill an inner-water SSC gap; retain unavailable values explicitly. Complete
means the SSC-only inner-water source route, not a promise that every requested
cell/date/variable exists. Temporal availability, missing support and model bias
remain visible in both modes.

Apply the agreed common Godin smoothing to the scalar SSC leg of both modes so
switching source modes does not silently switch between filtered and 24-hour
statistics. Exact SSC 71-tap values remain centred at 12:30 UTC versus LO noon;
the timing provenance and outstanding phase decision below remain applicable.
Currents retain their separately documented component/speed contract until a
filtered-current variant is explicitly defined and validated.

Outer waters may reuse regional values that already exist for the required
field/cell/date; do not enlarge a regional acquisition merely to enforce one
source offshore. Prefer the already-delivered [GLORYS12](GLORYS.md) salinity/current
products when that avoids new work. This is a convenience policy with explicit
source precedence per field, not permission to call daily GLORYS statistics
71-hour estimates, practical salinity reference salinity, or R5 output native R6.
GLORYS physics does not supply the oxygen/nitrate products in this plan. Preserve
source, units, method, native resolution, availability and valid time in required
provenance; a common view needs explicit compatible mappings before numeric joins.

Any geographic inner/outer partition must be explicit and frozen before claiming
that classification. Model footprints and GLORYS gaps are not such boundaries.
The started scalar run instead freezes all 960 SSC-supported study cells as an
inclusive acquisition/reporting envelope: supported inner waters plus any
overlapping outer waters, which the user permits using regional models for. It
does not classify these cells as inner waters or create an offshore numeric
mosaic. The new inner-water intent is not
limited to the old 502-cell GLORYS salinity gap mask. Existing salinity products
retain that narrower target and must not be relabelled as all-inner-water delivery.
The existing oxygen/nitrate target is all 960 SSC-supported study cells, which is
also a source footprint rather than a geographic inner-water classification.
Map the inner/outer partition to approved study water, reuse existing values where
eligible, and plan only the additional required acquisition. Current LO final
products deliberately excluded native values outside their frozen targets;
whole-domain source planes do not mean those outer-coast values were retained.

Both modes preserve existing source-specific checkpoints and final products,
use the shared 2 GB source cache, and retain final H3 Parquets plus required
provenance after verified intermediate cleanup. The new scalar run uses its own
owned work/output roots. It does not resume the legacy SSC salinity/current job,
modify that frozen gap plan, or extend source availability dates.

## Common-filter implementation and evidence

**Current requested approach — 2026-11-01:** the user proposed applying the same
71-hour filter to SSC to obtain consistent smoothing. This is a new common-filter
route following the earlier 24-hour-only requirement and pseudo-adjustment question.
Use the existing native LO products and apply the actual Godin 24–24–25 operator
to SSC hourly inputs, rather than trying to recover daily variability from LO.
The independently constructed convolution matches LO's published 71-weight
polynomial to 3.47e-18. A subsequent user-authorized bounded implementation,
`regional-filtered-pilot`, now performs native padded acquisition, streaming
reduction and explicit phase comparisons; its contract and actual qualification
status are in [REGIONAL_FILTERED.md](REGIONAL_FILTERED.md). Monthly scalar
scheduling, LO-first/SSC-fallback selection and final-partition recovery are now
implemented in [SURFACE_HISTORY.md](SURFACE_HISTORY.md). The earlier timing tests
did not resume history; the later user request to start authorized the separate
fast-mode scalar launch.

SSC hourly averages are labelled HH:30. A symmetric 71-sample window on that axis
centres at HH:30, whereas LO outputs are labelled at noon. Qualify input time
support/phase and the evaluation convention; do not silently shift timestamps
or claim exactly identical temporal support from matching weights alone. Require
all 71 valid source hours per native point, source-wet support, and padded requests
across day/month/year boundaries. Existing 24-hour SSC H3 checkpoints cannot
exactly reproduce the Godin statistic and remain distinct, preserved products.
See the [kernel and timing checks](../../../Reports/oceanography-common-filter-2026-11-01/reference-check.json).

**Status checked 2026-11-01: the regional scalar runner is implemented and the
fast-mode history has been launched; completion is not yet established.** The user
subsequently authorized standalone native LiveOcean acquisition/processing and
intermediate removal; its implementation is documented in [LIVEOCEAN.md](LIVEOCEAN.md).
That source leg completed locally for 2013–2024 on 2026-11-01, with verified
final Parquets and intermediate cleanup. The new scalar runner reuses those
checksum-bound values; the separate legacy SSC current history remains paused.
The user requested LiveOcean for 2013–2024 if acquisition is faster,
with SSC in the remaining years. The averaging methods remain scientifically
distinct: LiveOcean daily low-pass estimates use 71 hourly inputs centered on noon,
whereas legacy SSC products use 24 complete UTC-hour intervals. The proposed new
SSC product applies Godin weights to native hourly inputs; preserve all three
source/method identities rather than repurposing the old daily checkpoints.

## Existing acquisition scope and reuse

The `fast` chronology is SSC in 2009–2012, LiveOcean where supported in 2013–2024,
and SSC in 2025–2026-10-30, retaining SSC spatial fallback during the LO years.
These end dates reflect the last qualified SSC availability, not an assumed
complete 2026. The already-acquired salinity leg covers the existing 502-cell
GLORYS gap target; oxygen and nitrate cover all 960 SSC-supported study cells.
These frozen targets remain unchanged by the new modes and do not establish full
inner-water or outer-coast coverage. Currents, ammonium and silicon are not
in these LO daily bundles. Do not silently expand those families or substitute
daily mean-vector speed for the existing current metric.

The source selector must preserve unique date/H3/metric identity, source/version,
native support, units, depth, temporal window and transition provenance. Maintain
source-specific products and the frozen SSC checkpoints. No unqualified bias
correction, nearest-water fill, numeric point blending or UTC-day relabeling is
proposed. Ordinary daily public-table conventions do not make a 71-hour value a
24-hour daily mean. A source/method companion and explicitly qualified new product
variant are needed for the common-filter product. Matching smoothing does not
remove differences in models, depth, spatial support or bias.

## Qualification evidence

Both official S3 objects expose exact bounded HTTP ranges; complete daily axes
cover 2013-01-01–2024-12-31 (4,383 noon labels). Static geometry, wet masks and
horizontal metrics match across archives. Each requested scalar is stored as one
compressed whole-domain plane per day. Logical monthly checkpoints can read
selected chunks without staging the complete 30.94 GB archive. A continuous
January byte span is ~210 MB, versus ~99.63 MB for the three selected field chunks;
larger transfer spans have not been shown faster than exact chunk reads.

First-pass January 2013 salt field acquisition/H3 aggregation took 9.44 s / 30.68
MB, versus a historical SSC receipt of 331.10 s / 209.72 MB for that month. LO's
local metadata was mostly warmed and the runs were not simultaneous; no controlled
speedup or complete-hybrid ETA is established. Seven-day oxygen and nitrate reads
took 2.12 s / 7.31 MB and 2.08 s / 8.10 MB respectively. The pilot retained 30,450
native low-pass date/H3/variable rows; no final combined H3 product was published.

LO provides accepted native centres in 465/502 target salinity cells and 915/960
SSC-supported oxygen/nitrate cells. Remaining 37/45 cells require SSC fallback
under current mapping. Their one enclosing SSC rectangle still has 247,641
positions (~79.1% of the old gap rectangle), so fallback transport must be timed
before asserting net hybrid acceleration. Geometry-only tiling is not performance
validation or an implemented producer.

LO salt lacks a units attribute; provider model-analysis code treats it as
practical salinity SP. An explicit TEOS-10 conversion to reference salinity is
available, distinct from absolute salinity and bias correction. In a January 2013
comparison excluding the two previously unqualified SSC boundary cells, the
median absolute difference was ~0.99 g/kg across 14,353 paired cell-days. Different
models, native support, surface layers and filters contribute; this is not a
validated transition correction or physical attribution. The provider also warns
of high Salish Sea nitrate bias in this hindcast.

## Current execution and remaining qualification

The earlier v2 fast scalar worker failed its response bound before completing
a monthly checkpoint. The [subset/extension workflow](REGIONAL_SUBSETS.md) now
owns the running optimization: a salt-only regional LO extension followed by a
new frozen fast-history plan, reusing the two completed fields from v2. Four
whole-cell tiles were native-verified but slower in the ordered monthly test, so
one rectangle remains the default. The expected regional salinity fallback falls
from 495 to 45 cells after the extension; until then the older gap-only LO
salinity output still has its original narrower support. Current execution is
recorded in the [optimized job state](../../../Reports/oceanography-surface-subsets-2026-11-01/job.json).

The new runner freezes mode, all-regional support, source references and phase
before monthly acquisition. Its separate support expands salinity to all 960
SSC-supported study cells; existing gap-target products/lineage stay unchanged.
The native two-day fast pilot yields 960 finite regional cells per scalar/date:
salinity uses 465 LO plus 495 SSC; oxygen/nitrate use 915 LO plus 45 SSC. This is
regional model support, not complete geographic inlet coverage. The salinity SSC
fallback includes cells omitted by the old LO gap-only retention, not just native
LO model holes. No additional full-regional LO salinity reprocessing has occurred.

The bounded [SSC timing qualification](REGIONAL_FILTERED.md#executed-qualification--2026-11-01)
passed native year/month boundary tests and exact offline H3 replay. It preserves
exact 71-tap output at 12:30 UTC; noon interpolation is explicitly effective72.
The scalar run selects exact SSC71 at 12:30 UTC, recording the half-hour offset
from LO rather than applying noon interpolation. Multi-season overlap and model
transition accuracy remain unqualified; four winter dates are not a general error
bound. Existing 24-hour SSC checkpoints cannot supply the new statistic and are
preserved rather than migrated. Geographic inner/outer mapping, currents in the
new mode runner, global outer-coast compositing and observational/model validation
remain separate work. Source eligibility flags remain false. Run owner behavior
checks, full suite and installed-wheel native replay for runtime/plan changes.

The legacy SSC run remains paused, automatic resume off, with its 2 GB cap
and all 50 completed checkpoints unchanged. The user subsequently authorized the
standalone LO leg; [LIVEOCEAN.md](LIVEOCEAN.md) owns its implementation/status.
The new scalar launch is controlled by [the execution report](../../../Reports/oceanography-surface-fast-2026-11-01/job.json)
and does not restart that legacy job. See the
[dated native access, coverage and overlap evidence](../../../Reports/oceanography-liveocean-hybrid-2026-11-01/FINDINGS.md)
and [source-mask qualification](REGIONAL_GAP_HISTORY.md#surface-mask-qualification-follow-up--2026-11-01).
