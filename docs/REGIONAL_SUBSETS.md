# Smaller SSC fallback requests and regional LiveOcean salinity

The original fast scalar route retains LO salinity only inside the old 502-cell
GLORYS gap target. It therefore requests SSC for 495/960 regional salinity cells
in LO years, although LO's independently checked native footprint supports 915
of those 960 cells. These retained-product omissions are distinct from the 45
true native-footprint gaps. Do not infer all missing LO salinity values are model
holes or reduce the requested regional support to hide them.

`liveocean-salinity-extension` re-reads only salt chunks from the same official
bulk archives, applies the existing native-wet-centre R6 aggregation and explicit
SP-to-SR conversion, and produces a separate final monthly partitioned regional
salinity dataset for 2013–2024. It does not redownload oxygen/nitrate, modify the
old salinity product, or make daily remote-file requests. Source objects, noon
Godin statistic, depth and rights remain as in [LIVEOCEAN.md](LIVEOCEAN.md).
All overlapping finite old salinity values must match exactly before accepting
each new monthly output. Source chunks are evicted only after final H3 readback,
required provenance and old-value parity. Keep the shared 2 GB cap and two-request
limit, including the earlier failed run's retained source fields.

Final extension files are `YYYY-MM.parquet` (daily date/H3/reference salinity),
`provenance/YYYY-MM.json` and a checksum-bound `manifest.json`. Its regional target
and model footprint remain explicit, rather than an inner/outer boundary or an
observational coverage claim. A consumer must verify the complete manifest and
all referenced outputs before using it in a new frozen history plan.

`regional_tiles.partitions` divides fallback H3 cells into compact groups. Every
cell belongs to exactly one group and keeps all native wet centres used by the
existing calculation. Each group requests its enclosing rectangle; rectangles
can overlap and still overfetch, but aggregation uses only assigned cells. This
avoids changing spatial support, splitting and improperly averaging H3 cell means,
or introducing nearest-water/stride approximations. Every tile retains the full
hourly axis and filter padding. No point-count reduction is a measured speedup.

For the 45 true LO gaps, 192 required SSC points sit inside one 247,641-position
rectangle. Four whole-cell groups total 132,346 positions (46.6% reduction); eight
total 79,187 (68.0%). Native-point-only splits can be smaller but require a different
numerator/denominator reduction, so those old sizing candidates are not used here.
The 70 study months outside 2013–2024 still require SSC regional fields; tiling
cannot replace their absent LO years.

Before activation, compare tiled/bounding-box native H3 results bit exactly,
record request ordering/provider warming, transferred bytes, server preparation,
aggregate cohort time and shared cache peak. More requests can offset smaller
responses. The first large new-history cohort failed a 600-second response bound
without completing a month; preserve its completed source fields and legacy
checkpoints rather than calling it a running/completed historical product.

Run tests/test_regional_tiles.py, tests/test_liveocean_salinity.py, existing
surface/filter/LiveOcean tests and the full suite; use a regular installed-wheel
native/offline replay before launching changed acquisition. Keep the old frozen
plans and source/code lineage. Record actual optimization/launch outcomes in the
dated report, not inferred full-history runtime guarantees.

## Executed result — 2026-11-01

For January 2013 oxygen at the 45 true LO gaps, four whole-cell subsets transferred
136,738,572 bytes in 444.73 s; one enclosing rectangle transferred 208,530,540 bytes
in 239.31 s. This is **34.4% fewer wire bytes but 85.8% more acquisition time** in
this ordered test. Tiles ran first and the rectangle second; server/file caches
can warm, so the ratio is not a controlled cold-provider speedup/slowdown claim.
All three filtered timing variants were bit-exact at H3 level over all 31 dates.
Regular installed-wheel offline replay and actual tiled monthly publishing also
matched exactly. The five benchmark payloads were removed after final H3 and
provenance verification. Default history remains one rectangle; `--max-tiles 4`
is an explicit byte-reduction option, not a demonstrated runtime optimization.

All 115 tests passed (one existing NumPy/netCDF warning). The installed-wheel
salt-only native pilot produced 915 finite regional cells/day on 2013-01-01/02,
matched all 930 overlapping retained salinity values exactly, and resumed without
network after payload/metadata cleanup. The source objects match the original
LO lineage exactly. This establishes implementation/overlap parity on the sample,
not full extension completion or cross-model observational accuracy.

The optimized worker was launched to finish the salt-only regional extension
first, then resume `surface-history` with `--lo-salinity-extension` and the default
one-rectangle policy. The expected salinity fallback in LO years is 45 instead of
495 cells, conditional on actual source validity. O2/nitrate already had 45 gaps.
All 70 months outside 2013–2024 still require regional SSC fields. No revised
whole-history ETA is established by this sample.

The earlier large run stopped before completing a month. Two verified generated
fields remain in its owned cache and are registered for exact request reuse in
the new plan, without another archive copy. They may be evicted only after the
new monthly final H3/provenance replacements are verified. The new worker preserves
the 50 legacy SSC checkpoints and source-specific final products, uses one active
acquisition phase, two requests and a shared 2 GB cap, and holds a task-scoped Mac
sleep guard. Its status is distinct from that failed prior worker.

Retries now apply the 600-second response bound to each attempt rather than
letting an earlier preparation timeout invalidate a subsequent prepared response.
Byte caps stay unchanged; receipts record attempts, per-response and total time.
The regression fixture tests an earlier >600-second timeout followed by a valid
quick response. Full historical transport performance remains to be measured.

See [timing/native evidence and current phase](../../../Reports/oceanography-surface-subsets-2026-11-01/FINDINGS.md).
Install the existing optional dependency group `.[liveocean]` for the salt-only
extension; the qualified runtime pins h5py 3.15.1.
