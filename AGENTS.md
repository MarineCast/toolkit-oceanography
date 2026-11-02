# toolkit-oceanography agent guidance

## Scope and current state

Ocean properties, currents, tides, waves, and related data products.

This contains an incomplete research package extracted from OrcaCast on 2026-09-15.
Read `docs/ARCHITECTURE.md` for ownership/import changes; `docs/PRODUCTS.md` for scientific
or product changes; README.md and docs/SETUP.md before setup/execution; TODO.txt for readiness.
Do not describe the extraction as production completion.
Preserve unrelated changes and read deeper instructions before editing a subdirectory.

## Shared MarineCast context

For boundary, dependency, shared schema/provenance, or application-integration changes, read
[INFRASTRUCTURE.md](https://github.com/MarineCast/.github/blob/HEAD/INFRASTRUCTURE.md).
In the grouped workspace use `../../.github/INFRASTRUCTURE.md`; in a flat clone layout use
`../.github/INFRASTRUCTURE.md`, resolving from this checkout. Otherwise use the linked copy;
if unavailable, report the limitation without inventing a shared standard. Sibling instructions
are not inherited. Local implementation contracts remain authoritative; surface conflicts.

## Domain contracts

Preserve timestamps, depth and vertical reference, units, grid/CRS, and wet/dry coverage. Document
current-vector conventions and tide datums. Validate interpolation support and trailing-window
coverage; do not snap unsupported observations or relabel source dates. Missing ocean coverage
is not zero, and environmental conditions are not species preference.

## Implementation boundaries

- Keep this toolkit species-neutral and independently installable; do not require an OrcaCast
  checkout or import through sibling filesystem paths.
- Before adding a pipeline, define source rights, input/output grain, units, spatial and temporal
  support, missingness, provenance, and validation in the repository documentation.
- Add dependency declarations and runnable setup/validation commands with the implementation;
  do not copy viewshed's GDAL stack or commands unless this toolkit actually needs them.
- Prefer deterministic calculations and small synthetic/offline fixtures. Keep credentials,
  downloads, and large generated products out of tracked source.
- Keep unknown and unavailable values distinct from observed zero. Validate uniqueness and join
  cardinality rather than silently dropping conflicting records.

## Validation and completion

Use isolated Python 3.11+: `python -m pip install -e '.[test]'`.
Start behavior validation with `python -m pytest -q tests/<relevant_test>.py`, then the required
suite below. Documentation-only edits need reference checks and `git diff --check`, not Python tests.
No local skills are needed yet; load only the task-specific documents routed above.


For documentation-only work, inspect `git status --short` and the diff, verify references, and run
`git diff --check` from this repository. Run `python -m pytest -q` after installing `.[test]`; check a regular wheel outside
the checkout. Keep config/ and packaged resources synchronized. Live research runs require
externally provisioned seascape support and separate validation.
When adding executable behavior, add appropriate checks and document their exact commands here.
Report tests actually run, unverified source acquisition, and any unrun integration paths.

## Codebase navigation

For the separate Waves product, read `docs/WAVES.md`; run
`python -m pytest -q tests/test_waves.py`, the full suite and a regular installed-wheel
readback/native-chunk replay. Install `.[waves,test]` (and `.[liveocean]` for the
optional LiveOcean fixtures). Preserve exact native times, FROM direction,
complete-day/circular reductions, derived sea-state boundaries and unsupported
nulls. Keep the separate output root, existing products and source epochs intact.

Use the existing local `graphify-out/graph.json` for structural questions; skip graph work for
obvious targeted edits. Prefer the smallest useful retrieval:

1. Known symbol: `explain` first, then follow only relevant callers/callees/imports/dependencies.
2. Use direct relationships before deeper traversal; broad `query` is for unknown ownership.
3. If results are large or truncated, narrow the symbol or relationship before increasing budget.
   `--budget` is not a guaranteed cap. Avoid unnecessary depth-2 neighborhoods.
4. Read the identified source/tests. They outrank schemas/contracts, architecture docs, then the
   graph. Use targeted `rg` when graph coverage or freshness is insufficient.

```bash
graphify explain "normalize_tides"
graphify affected "normalize_tides" --relation calls --depth 1
graphify query "<topic>" --context call --budget 1500
```

`affected` follows reverse edges (callers); `explain` shows immediate connections. Use ast-grep
for syntax patterns and `rg` for literal/config/prose/filename searches. Read architecture for
ownership/import changes, not every typo. Optional shared setup/examples:
[code navigation](https://github.com/MarineCast/.github/blob/HEAD/docs/code-navigation.md)
(local grouped workspace: `../../.github/docs/code-navigation.md`). No sibling checkout is required.

Graphify is optional developer tooling (`graphifyy==0.9.62`, isolated Python 3.10+), not a runtime
dependency. Create a missing graph or refresh after structural edits, from this checkout only:

```bash
graphify extract . --code-only --no-cluster
```

Do not rebuild merely for a question. Check intentional deletions before using `--force` to bypass
shrink protection. `.gitignore` and `.graphifyignore` apply; AST-only extraction does not index
prose semantically. Graphs/caches are disposable local-only files: never commit or publish them.
Any future sharing requires an explicit policy covering destination, revision, freshness and review.
Global skill defaults do not override repository scope or code-only extraction. Do not run
`graphify codex install` over maintained instructions or enable hooks/merge drivers implicitly.

For simple full-study satellite delivery changes, read `docs/DAILY.md`; run `python -m pytest -q tests/test_daily.py`, then the full suite and an outside-checkout installed-wheel replay. Public tables contain only date, h3_index and requested metrics; source qualification stays in the catalog/receipts.

For historical Ocean Conditions work, read `docs/HISTORY.md` and run `tests/test_history.py` plus the daily tests and full suite. Preserve accepted delivery until full checkpoint/readback validation and consumer readiness; use explicit `--publish`.

For HYCOM surface work, read `docs/COARSE.md`; run `tests/test_coarse.py`, the full suite and installed-wheel offline replay. Preserve existing satellite delivery, require complete sample timestamps, verify source vector orientation/depth, and calculate speed before temporal averaging. Historical source transitions and SalishSeaCast products remain separate qualification tasks.

For the separate SalishSeaCast pilot, read `docs/REGIONAL.md`; run `tests/test_regional.py`, the full suite and installed-wheel replay. Never relabel grid x/y velocities as geographic components or reference salinity g/kg as practical salinity psu. Keep coarse/regional products separate until explicitly qualified.

For full-study gap supplements, read `docs/REGIONAL_GAP_HISTORY.md`; run `tests/test_regional_gap_history.py` plus regional/history/streaming tests, the full suite and an outside-checkout installed-wheel native replay. Freeze GLORYS spatial gaps and complete native availability, preserve full selected-R6 support, keep independent family checkpoints, and evict only registered generated sources after verified H3 replacements. Preserve existing pilots/archives and use explicit additive publication.

For parallel regional acquisition, keep at most two requests under one aggregate cache reservation budget. Run the gap-history concurrency, recovery and explicit-plan-upgrade tests, the full suite and installed-wheel native parity before upgrading an active frozen plan. Preserve the exact prior plan and checkpoint hashes. Live timing must distinguish cold requests from warmed/reused responses and retain serial fallback; concurrency does not change scientific support or source retention.

For ENSO or native tide events, read docs/CONTEXT.md and docs/TIDE_EVENTS.md; run tests/test_context.py and tests/test_tide_events.py, the full suite and installed-wheel replay. Preserve native periods, event multiplicity, timezone offsets and checksum-bound water support.

For the bounded GLORYS pilot, read docs/GLORYS.md; install optional `[copernicus]`, run tests/test_glorys.py, the full suite and installed-wheel offline replay. Preserve the distinct daily-mean-vector speed metric, practical salinity, source wet mask, ARCO depth/time conventions and unsupported inland nulls.

For GLORYS history, read docs/GLORYS_HISTORY_PLAN.md and run tests/test_glorys_history.py plus the full suite. Require unique-object Time Series caching, historical alternate-layout anchors, full offline installed-wheel replay, daily row groups, and explicit provenance for July 2021 interim and January 2019 forcing transitions before promotion.

For LiveOcean scalar history, read docs/LIVEOCEAN.md; run tests/test_liveocean.py,
the full suite and an outside-checkout regular-wheel native replay. Preserve
71-hour low-pass support, practical/reference-salinity conversion, source-specific
nulls and SSC checkpoints. Bound all registered source caches to 2 GB, validate
final daily partitions before publication, and delete only manifest-listed owned
intermediates after verified replacements. A mixed-model history is separate work.

For SSC Godin filtering/timing qualification, read docs/REGIONAL_FILTERED.md;
run tests/test_regional_filtered.py, the full suite and regular installed-wheel
native/offline replay. Preserve exact 71-tap versus 72-input noon-interpolation
semantics, half-hour source timing, complete padded windows and source wet masks.
Keep the shared 2 GB cap, legacy checkpoints and final-H3/provenance-only retention.
Do not activate a full historical/composite run from kernel parity alone.

For fast/complete regional scalar acquisition, read docs/SURFACE_HISTORY.md;
run tests/test_surface_history.py and tests/test_regional_filtered.py, the full
suite and regular-wheel mixed-source native/offline replay before launch. Preserve
source-time phase, explicit regional support, existing final products and legacy
checkpoints. Monthly partitions are final H3 outputs; source eviction requires
checksum-bound final partitions and provenance. Keep one active history writer,
two source requests and the shared 2 GB budget across registered caches.

For smaller SSC subsets or regional LO salinity support, read
docs/REGIONAL_SUBSETS.md; run tests/test_regional_tiles.py,
tests/test_liveocean_salinity.py and the surface/filter/LO tests plus the full
suite. Require installed-wheel monthly native tile parity, exact old-salinity
overlap, final-checkpoint offline resume and verified cleanup. Benchmark bytes
and cohort time separately; point-count savings do not establish speedups.
Preserve whole-cell native support, old outputs and immutable attempt plans.


For source-specific regional Waves, read `docs/WAVES_REGIONAL.md`, install
`.[waves-regional,test]`, run `tests/test_waves_regional.py` and the full suite,
then check a regular wheel outside the checkout with retained native replay.
Preserve source-specific cadence/T02/Tm/direction, count companions, verified
source plans, true gaps versus acquisition failures and USGS effective-coordinate
gating. Keep ERA5 unchanged. Before bulk requests, coordinate with the existing
active regional owner and stay within its aggregate two-request limit. Full
native-day qualification precedes a full archive run; only complete validated
checkpoint sets may be promoted. Report queued/running/published states honestly.
