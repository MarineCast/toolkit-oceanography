# Package structure and scientific boundaries

| Module | Responsibility |
| --- | --- |
| `config` and `core/config` | Strict Pydantic research settings, composed YAML and workspace paths |
| `download` | Bounded source acquisition and request-addressed, checksummed cache |
| `normalization` | Shared source-time checks and native-grid-to-H3 aggregation |
| `build` | Daily normalized layers, candidate features and lineage records |
| `spatial` | Water-network distances, coastal seed audit and influence kernels |
| `regional_sources` | HYCOM subsets and DFO WebTide archive/interpolation/reconstruction |
| `composite` | Strictly trailing productivity windows, observation counts and ages |
| `compare` | Regional and broader-provider comparison reports |
| `inspect` | Water-clipped research HTML maps and source/feature catalog |
| `cli` | Explicit-date commands and non-overwriting workspace initialization |

The original calculation modules remain grouped together so this extraction does not combine
packaging work with a scientific refactor. Source-specific module splitting is deferred.
Configuration helpers are toolkit-local. No OrcaCast import or sibling-source path injection is used.

Daily tables retain H3/date identity, source resolution, units, QC and coverage. R5 parent mapping
does not create fine-scale information. Missing ocean support stays missing. Station tide range,
water-distance discharge influence, native-current speed and satellite retrievals have distinct
spatial and temporal meanings; they must not be blended as interchangeable measurements.

The implementation remains retrospective research: availability timestamps are unknown and products
are not forecast eligible. Model selection, ecological interpretation and application integration
belong downstream. Source rights are documented in [DATA_SOURCES.md](DATA_SOURCES.md).

Raw cache integrity and atomic JSON writes already exist. Multi-artifact transactional publication,
complete code lineage and a validated cross-toolkit support contract remain unfinished; see
[TODO.txt](../TODO.txt). Configuration templates in `config/` and `src/oceanography/resources/config/`
must remain synchronized. Validate edits with `python -m pytest -q` and a regular wheel smoke check.
