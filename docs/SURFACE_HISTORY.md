# Fast and complete surface scalar history

`oceanography surface-history --mode fast|complete` is the regional scalar history
runner. `fast` reuses the checksum-bound final LiveOcean 2013–2024 surface salinity,
oxygen and nitrate values wherever present, acquiring SSC for the remaining
regional cell/dates. `complete` acquires SSC throughout. This workflow covers the
SSC-supported study envelope, including supported inner waters and any overlapping
outer waters. That envelope is not a geographic inner/outer classification or a
promise of coverage in every inlet. It deliberately expands salinity beyond the
legacy 502-cell GLORYS-gap target to the prepared regional support. Existing
source products and all legacy checkpoints remain unchanged.

The [mode policy](REGIONAL_HYBRID_PLAN.md) remains controlling. Outer-coast GLORYS
salinity/currents are reused by reference as separate native-R5 products. This
runner produces no numeric R5/R6 mosaic, current fields or outer-coast oxygen
extrapolation. Currents retain their source-specific workflow; they are not
silently supplied by LO scalar bundles.

## Calculation and source selection

SSC uses the validated [71-tap Godin operator](REGIONAL_FILTERED.md) on native
hourly means, requiring complete valid windows per native wet point before
area-weighted R6 aggregation. Exact SSC estimates centre at 12:30 UTC. LO retains
its native noon centre and surface-layer semantics. This runner selects the exact
kernel and records the +30-minute SSC phase; it does not interpolate to noon or
claim identical intrahour support. Reference salinity is g/kg; oxygen and nitrate
are mmol/m³. LO's existing explicit SP-to-SR conversion remains in its lineage.
No bias correction or blending is performed.

Selection is per field/date/H3: in `fast`, use a finite, physically valid existing
LO value inside the regional target, otherwise request SSC. In `complete`, use
SSC only. Invalid/missing values remain null, real zeros remain valid. Cells with
no valid native support remain unavailable. Frozen source axes must cover all
required hourly centres, including the previous/following calendar day; the
filtered output end is at most one day before the last complete native source
day. Requested and actual dates are recorded separately.

## Storage, resume and final products

Use a new owned work root and an immutable plan binding mode, requested/actual
dates, study/support/geometry/mask, code/library versions, LO products/lineage,
outer-product references and registered shared caches. Only one runner owns its
work root. Other historical source writers must remain paused while this runner
uses their cache roots in the shared budget.

Each calendar month requests one padded hourly surface subset per required SSC
field, with no hourly thinning or per-day requests. Per-field bounds retain all
native points in each selected fallback cell. At most two requests run at once
under one aggregate 2,000,000,000-byte cache/reservation cap, including registered
prior caches. The existing 450 MB compressed/1.25 GB decoded response bounds and
20 GB free-space floor apply. Monthly source requests allow a 600-second read
timeout: successful historical receipts waited 237.5 seconds before headers, so
the bounded pilot's 180-second default is unsuitable for history. This parameter
is frozen in the historical plan. Decoded fields stream through memory.

Final output is a partitioned H3 dataset under the chosen delivery root:

- `salinity/YYYY-MM.parquet`: date, h3_index, reference_salinity_g_kg.
- `oxygen/YYYY-MM.parquet`: date, h3_index, dissolved_oxygen_mmol_m3.
- `nitrate/YYYY-MM.parquet`: date, h3_index, nitrate_mmol_m3.
- `sources/YYYY-MM.parquet`: date, h3_index and one source code per scalar
  (`liveocean`, `salishseacast`, `unavailable`).
- `provenance/YYYY-MM.json`: required monthly input/filter/selection/checksum
  provenance; `manifest.json`: plan and completed-month index.

Every day retains all approved R6 reporting keys, with nulls outside support.
Monthly Parquets are final daily-grain partitions, not disposable monthly caches.
Each final daily row group is compared exactly with the calculated day before
publication. A prepared publication record enables recovery after partial moves;
accepted checkpoints bind all final Parquets and required provenance. Resume
rejects changed plans/products, verifies accepted checkpoints without network, and
does not redownload completed months. Source eviction verifies those replacements
and the exact registered generated source hashes. External source archives,
geometry, legacy checkpoints and existing final products are never evicted.

Small source receipts, frozen plans, progress and cleanup proofs remain. Raw
payloads and task staging disappear after validated replacements; exact raw replay
then requires reacquisition. A `PAUSE` file in the work root requests a pause at
the next month boundary. No automatic restart or global power setting is changed.

## Checks and execution

Run `tests/test_surface_history.py`, `tests/test_regional_filtered.py`, the full
suite, regular-wheel native mixed-source acquisition and zero-network raw replay,
then a checkpoint-only resume after source cleanup. Source acquisition completion
is distinct from observational accuracy, cross-model transition qualification and
application integration. Independent seasonal/model validation remains open.

```sh
oceanography surface-history --mode fast \
  --study /workspace/config/study.v1.json --pilot /workspace/ssc-geometry \
  --mask /workspace/ssc-surface-tmask.nc --support /workspace/regional-support.json \
  --existing /workspace/Data/Oceanography \
  --output /workspace/Data/Oceanography/surface-fast \
  --root /workspace/.marinecast-work/oceanography/surface-fast \
  --start 2009-01-01 --end 2026-10-30 \
  --shared-cache /workspace/other-owned-source-cache
```

## Launch qualification — 2026-11-01

All 107 owner tests passed (one existing NumPy/netCDF binary-size warning). The
regular-wheel native fast pilot covered 2013-01-01/02, with exact zero-network
replay of all three final scalar tables and per-cell source codes. Each date has
960 finite regional cells: salinity 465 LO + 495 SSC; oxygen/nitrate 915 LO + 45
SSC. Independent reference versus streaming error was at most 1.14e-13. A final
checkpoint-only resume made no requests or manifest changes after generated raw
payloads were removed. The corrected final build's pilot transferred 77.63 MB,
peaked at 1.252 GB of conservative shared reservations and completed in 139.31 s,
including time-axis checks. Identical requests had been made during earlier
qualification; this is not a cold-provider speed benchmark or a full-history
timing forecast.

The user-authorized fast scalar job was launched for 2009-01-01–2026-10-30. Fresh
axes contain every required hour through 2026-10-31 23:30 UTC, so the requested
last filtered date has complete padding. This is source-axis availability, not
finished historical value validation. Final products go to the separate configured
`Data/Oceanography/surface-fast/` root. All prior source-specific products and
50 SSC checkpoints are preserved. The legacy current job stays paused; it is not
silently sharing acquisition slots with this runner. The Mac sleep guard is
scoped to the detached scalar worker and ends with it; no global settings change.

See [native evidence](../../../Reports/oceanography-surface-fast-2026-11-01/native-pilot-validation.json),
[job state](../../../Reports/oceanography-surface-fast-2026-11-01/job.json) and
[staging/retention manifest](../../../Reports/oceanography-surface-fast-2026-11-01/staging-manifest.json).
Acquisition remains incomplete until the worker and final validation establish
completion. A clean dependency install, hosted CI and independent model accuracy
validation were not run.

The first launch was stopped before any source payload or monthly checkpoint
completed: its inherited 180-second pilot read timeout was shorter than successful
monthly header waits. The corrected build uses 600 seconds and passed the full
suite and installed-wheel native/offline checks again. Original attempt plans,
runtime/wheel and existing products are retained; the restart uses a separate
`surface-fast-2009-2026-v2` work root and the unchanged new delivery root.

## Smaller subsets and salinity support extension — 2026-11-01

The v2 attempt subsequently failed its combined response bound before completing
a month. Its two completed input fields remain preserved for reuse. The
[subset investigation](REGIONAL_SUBSETS.md) found that four rectangles reduce
monthly oxygen wire bytes by 34.4% but took 444.73 s versus 239.31 s for one
rectangle in an ordered native test. Every H3 value matched. Provider warming
limits that timing comparison; smaller files alone do not establish acceleration.

`--max-tiles N` optionally partitions whole fallback cells into up to N compact
groups, keeping every native point of each cell; default remains 1. The new
`--lo-salinity-extension PATH` input accepts only a complete, checksum-bound
2013–2024 regional salt-only extension with matching study/source/statistic.
Existing finite salinity values must agree exactly. This reduces expected SSC
salinity fallback from 495 to 45 cells in LO years rather than treating unretained
LO output as missing model coverage. Full extension acquisition is a separate
phase and remains incomplete until its manifest is complete.

`--reuse-source PATH` can reuse exact request-addressed generated fields from an
owned earlier surface-history cache already registered with `--shared-cache`.
No archive copy is made. Source eviction verifies the new month products and
required provenance, source hash and prior history ownership before removal.
Unique external sources and legacy regional checkpoints are not eligible.

The new [optimized worker](../../../Reports/oceanography-surface-subsets-2026-11-01/job.json)
finishes the salt-only extension first, then resumes the scalar history in a new
v3 work root. The two phases share the 2 GB budget and never acquire concurrently.
Per-attempt response timing now permits a subsequent prepared response after an
earlier timeout; unchanged byte bounds and a maximum three attempts still apply.
The original v2 job record remains a failed historical attempt, not live status.
