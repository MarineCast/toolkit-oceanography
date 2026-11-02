# Bounded 2024 SalishSeaCast history

For the separately authorized full-study gap-only run, use the new
[monthly regional history pipeline](REGIONAL_GAP_HISTORY.md). It has independent
salinity/current checkpoints, a 2 GB transient source cache, final readback and
additive gap products. The older 2024 runner and sources documented here remain
preserved; they were not resumed or repurposed.

Authorized scope: 2024 daily reference salinity and geographic currents, all approved
R6 reporting cells. Preserve accepted July 1–3 values and all other products.
Same sources/depth/grid/wet mapping and 24-hour mean-speed semantics as REGIONAL.md.
Native files are retained as lossless gzip with raw and compressed checksums; no
source deletion or uncompressed scratch. Serial requests, maximum 40 MB decoded
response, bounded timeouts and attempts, 10,000,000,000-byte entire-cache cap and
20,000,000,000-byte free-disk floor. Failures remain pending, not null days.
Seven-day benchmark July 1–7 gates year acquisition. Reuse verified pilot inputs.
Require estimated source volume plus 15% headroom below the cache cap. Daily Parquet
checkpoints have complete sorted membership, physical-range and vector checks.
Frozen plan binds producer code, geometry, study and baseline product checksums.
No automatic publication until whole-year readback and pilot parity pass. Final
files have one row group per UTC day; publication uses the shared locked transaction.

**Current state:** seven-day benchmark completed; year acquisition is paused by latest user direction. No automatic continuation exists. Read [resolution/cost comparison](RESOLUTION_COST.md) before deciding the next acquisition.

On 2026-10-31 the user requested full-study historical qualification and selected
assessment of final daily H3 retention with a bounded source cache. The new
[full-study plan and live bulk benchmarks](REGIONAL_FULL_HISTORY_PLAN.md) supersede
the earlier cost assumptions for that proposed workflow. The existing 2024 runner
and its frozen seven-day sources/checkpoints remain unchanged; no full backfill
or cleanup batch has been executed.
