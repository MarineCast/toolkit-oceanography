> Historical OrcaCast report retained for provenance. Paths, commands, metrics and validation below
> describe that earlier run; they are not a validated run of the standalone toolkit.

# Environmental oceanographic pilot — 2026-09-10

Implemented and executed collection, normalization, marine feature transformation, and five HTML maps for 2024-07-01 through 2024-07-03. Prey remains separate. This is a three-day retrospective pilot, not a full historical backfill or a completed model-selection experiment.

- Entrypoint: `python -m orcacast.domains.environment.oceanographic run --start 2024-07-01 --end 2024-07-03`
- Config: `config/data/environment_oceanographic.yaml`
- Source documentation and reproduction: `src/orcacast/domains/environment/oceanographic/README.md` and `DATA_SOURCES.md`
- Map hub: `outputs/domains/environmental_layer/oceanographic/2024-07-01_2024-07-03/index.html`
- Machine-readable source/feature chain: `FEATURE_CATALOG.json` beside the map hub; static research catalog in the owning package.
- Raw data: about 64 MB; processed normalized layers plus features: about 18 MB for this pilot.

## Marine interpretation

Tides and discharge are propagated along the canonical R8 water graph, then averaged to R6 with water-area weights. Tide range uses normalized weights; discharge sums flow times distance-decay weights from explicitly mapped river mouths. The scales are sensitivity candidates, not calibrated physical transport lengths. At least half of a parent's water area must be supported; missing expected gauges invalidate the affected parent. All daily R6 families use the 1,252 canonical cells with actual marine overlap. Chlorophyll uses 242 R5 parent cells.

All 14 river gauges (6 ECCC, 8 USGS) returned daily flow for the pilot, and all 14 mouth seeds mapped. The expanded roster includes Washington outer-coast Hoh, Queets and Quinault, as well as Vancouver Island rivers. It does not represent every catchment or total mouth discharge. Estuary coastal snapping is bounded and recorded; BC mouth approximations need review.

All nine tide stations returned hourly predictions. Eight mapped to marine support. Neah Bay remains unmapped: its position is about 812 m from the current water mask, exceeding the 200 m station coastal-snap limit. Do not increase that limit merely to eliminate the warning; review station and shoreline geometry first.

## Coverage limits

- SalishSeaCast current candidates occur in cells containing about 66.9% of model-support water area; the model leaves outer-coast gaps.
- SST candidates occur in cells containing about 91.8–98.4% of support water area across these three days.
- Chlorophyll candidates occur in cells containing about 72.6–91.3% across these days. Cloud/optical-quality gaps remain null.
- River and tide influence coverage depends on the selected kernel scale and water-network reachability. Use per-column coverage and fine-grid support fractions in the reports; broader kernels do not establish more observed coverage.
- These percentages describe water area of cells with a candidate, not complete native-pixel observation of that area.
- Provider archive metadata spans more years, but those years have not been collected or verified by this pilot. Canadian published daily discharge and USGS provider-day definitions remain distinct.

## Validation

- 29 focused oceanographic and existing environmental baseline/candidate tests passed.
- All 15 family/date partitions built, and an offline replay from checksummed raw snapshots succeeded.
- Processed layer, feature, code, and spatial-input checksums verified; no duplicate date/H3 keys.
- Five HTML maps passed JavaScript selector/redraw checks with mocked DOM and Leaflet (35 redraws across all dates/metrics, including initial draws).
- Water-clipped surfaces were visually reviewed in `preview.png`.
- Actual browser rendering/interaction validation was not performed; map logic checks do not establish it. Leaflet and basemap tiles need network access.

Next: review the remaining shoreline mismatch and approximate mouth associations, collect representative winter windows, evaluate temporal aggregation and kernel scales inside the blocked model-selection folds, then backfill the chosen date range. No production model columns or weekly baseline inputs were changed.
