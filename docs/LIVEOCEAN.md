# LiveOcean historical surface scalars

**Combined-history eligibility — 2026-11-01:** these delivered 71-hour products
do not meet the earlier 24-hour-only requirement. The user's latest proposed
route is applying the same Godin filter to SSC hourly inputs; that could reuse
these completed LO products under a common filtered-statistic contract. Bounded
[SSC native timing tests](REGIONAL_FILTERED.md) passed, with exact 71-tap SSC output
at 12:30 UTC versus LO noon. The [regional scalar history runner](SURFACE_HISTORY.md)
now implements source selection with that offset recorded and exact SSC71 retained.
The user calls LO plus SSC fallback `fast` mode and SSC-only
inner waters `complete` mode, with flexible outer-coast sources in both. No pseudo
24-hour conversion has been applied. Files and lineage remain preserved. See the
[mode policy and activation work](REGIONAL_HYBRID_PLAN.md).

`oceanography liveocean-history` acquires the official `cas7_t0_x4b` surface
low-pass archives for 2013–2024 using bounded S3 byte ranges. It processes logical
calendar-month cohorts, verifies daily H3 checkpoints, evicts generated source
payloads, and assembles final Parquet tables. Completed final products replace
all task-generated source/month intermediates after exact readback. Small plans,
progress, cleanup proofs and required scientific lineage remain. Existing SSC
checkpoints and other source-specific products are not changed.

## Source and scientific contract

The [provider portal](https://faculty.washington.edu/pmacc/LO/data_access.html)
offers two bulk NetCDF/HDF5 archives, 2013–2019 and 2020–2024. These are public
downloads for model-output analysis. This workflow is local research delivery;
redistribution rights and independent scientific/model eligibility have not been
qualified. The provider warns that Salish Sea nitrate is generally biased high.

The provider's [low-pass driver](https://github.com/parkermac/LO/blob/main/extract/lowpass/extract_lowpass.py)
and [worker](https://github.com/parkermac/LO/blob/main/extract/lowpass/lp_worker.py)
use 71 hourly inputs and Godin weights, centered on daily noon. Archive history
must name `lowpassed.nc` and surface rho-layer index 29. Output `date` is the
native noon-label date, **not a complete 24-hour UTC mean**. Surface depth follows
ROMS terrain coordinates; it is not asserted equal to SSC's ~0.5 m level. This
implementation neither joins model years nor performs bias correction.

| Product / final filename prefix | Metric | Units |
| --- | --- | --- |
| `liveocean-salinity` | `reference_salinity_g_kg` | g/kg |
| `liveocean-oxygen` | `dissolved_oxygen_mmol_m3` | mmol oxygen/m³ |
| `liveocean-nitrate` | `nitrate_mmol_m3` | mmol nitrogen/m³ |

Each `*-r6-daily.parquet` has exactly `date,h3_index,<metric>`, all approved R6
keys for each acquired date, and one daily row group. Salt in the native extract
has no units attribute; provider [model-analysis code](https://github.com/parkermac/LO/blob/main/obsmod/combine_obs_mod.py)
treats it as practical salinity SP. The explicit
[TEOS-10 reference-salinity](https://www.teos-10.org/pubs/gsw/html/gsw_SR_from_SP.html)
conversion is `SR=SP*(35.16504/35)`; this is not absolute salinity or a model-bias
correction. O2 and nitrate preserve their native molar substance bases.

Native mask=1 centres must lie in checksum-bound approved study water and approved
R6 membership. Assign centres directly to H3 and weight by `1/(pm*pn)`; this is
not exact water-area integration. The explicit support input selects the existing
502-cell GLORYS gap target for salinity and all 960 SSC-supported study cells for
new oxygen/nitrate. Qualification found 465/915 LO-supported cells respectively;
unsupported cells stay null. No nearest-water fill or silent SSC fallback is
performed. Numeric zero remains valid. Nonfinite/fill/negative concentrations and
salt above 50 are excluded at the native point; counts remain in lineage. A wholly
missing field/day fails instead of becoming a successful null day. Source depth,
filter and native support remain material qualifications for future comparison.

## Bounded execution and recovery

Install the optional reader with `pip install -e '.[test,liveocean]'`. Native HDF5
time axes, layouts, field units and cross-archive grid hashes are checked.
ETag/If-Match, exact 206 Content-Range, lengths and SHA256 bind every request.
The runner never stages the complete ~31 GB archive. Default `chunks` transport
reads only selected compressed chunks inside the bulk objects with at most two
requests. Optional `bulk` uses the enclosing monthly byte span, including unrelated
fields; it is not presumed faster. Tiny metadata reads are coalesced into 64 KiB
ranges. Native fields are handled one day at a time; no full-year decoded arrays
are retained.

The aggregate source cap is 2,000,000,000 bytes, with reservations before requests,
a 450 MB per-response ceiling and a 20 GB free-space floor. Include every other
task-owned source cache with repeated `--shared-cache`; overlapping cache roots
are rejected. Concurrent unrelated writers must be stopped/coordinated first;
these paths account for existing payloads, not reservations owned by other jobs.
`--reuse-cache` references checksum/ETag-bound qualification ranges without copying
them, and never deletes external seed files during normal source eviction.

Use a new empty work root. `ownership.json`, an exclusive run lock and a frozen
plan protect resume. The plan binds dates, support, source ETags, source grid,
study, code and dependency versions. Each monthly checkpoint must pass exact
identity/schema/readback/checksum validation before its generated source chunks
are removed. Interrupted/failed months remain pending; valid completed months
resume without acquisition. `--limit-months 1` qualifies the first month without
pretending the whole run is complete. Source errors do not mark null months done.

Final assembly reads every month and checks every final daily partition against
its checkpoint, then publishes additively under the catalog publication lock.
Conflicting existing products are rejected. A prepared publication record enables
recovery after a partially completed rename. Cleanup checks all final hashes,
records exact owned paths/checksums before deletion, preserves required lineage,
and can resume after interruption. Unknown files and symlinks stop cleanup.

```sh
oceanography liveocean-history \
  --study /workspace/config/study.v1.json \
  --support /workspace/task/support.json \
  --output /workspace/Data/Oceanography \
  --root /workspace/.marinecast-work/oceanography/liveocean-history-2013-2024 \
  --start 2013-01-01 --end 2024-12-31 \
  --shared-cache /workspace/other-task/sources
```

The JSON support input contains `study_sha256`, `salinity_r6`, `scalar_r6` and
provenance for their frozen source-mask/gap evidence. It is an explicit prepared
input, not a sibling-source-code dependency. All selected keys must be approved
study members. Outputs are three final Parquets, one shared
`liveocean-lineage.json` and additive catalog records. Currents, ammonium and
silicon are not in these surface extracts and are not produced here.

## Validation and dated status

Run `python -m pytest -q tests/test_liveocean.py`, the full owner suite,
`git diff --check`, and an outside-checkout regular installed-wheel native replay.
Tests cover units/zero/missingness, weights, exact ranges, shared reservations,
corruption, checkpoint-gated eviction, atomic publication recovery and safe cleanup.
Full acquisition and final-product completion must be recorded separately from
these code checks. The 2026-11-01 user instruction authorizes this standalone LO
acquisition and removal of its processing intermediates; SSC remains paused.

**Completed 2026-11-01:** all 144 months / 4,383 native daily labels for
2013-01-01–2024-12-31 were acquired, processed and published locally. Each of the
three Parquets has 10,637,541 rows (2,427 approved keys per day), with 465 finite
salinity cells / 915 finite O2 and nitrate cells on every day. The three files
total 198,864,567 bytes; their shared required lineage is 12,011,360 bytes.
The job took 35.01 minutes, transferred 14,890,113,077 new range bytes (including
metadata; earlier qualification ranges were reused), and peaked at 652,062,832
bytes of shared source-budget accounting, including other registered caches.

The final build passed 88 owner tests and a regular installed-wheel two-day
native acquisition plus exact offline raw replay. Every one of the 13,149 final
daily partitions passed independent identity/value/support checks and assembly
readback; all 30,450 retained earlier pilot values matched the final products.
Completed offline resume made no network requests or catalog changes. The 50
SSC checkpoint hashes and all ten previously accepted product hashes remained
unchanged. These checks establish acquisition, arithmetic, identity, retention
and local delivery, not independent observational accuracy/model eligibility.

Generated source/month files were removed after verified replacements, and the
earlier LO qualification sources/pilot data (203,008,929 bytes) were removed under
the user's explicit instruction. The current workflow retains no raw/month
data intermediates; exact native replay now requires reacquisition. The sleep
guard ended with the worker. See the [final validation and cleanup evidence](../../../Reports/oceanography-liveocean-history-2026-11-01/FINDINGS.md).
