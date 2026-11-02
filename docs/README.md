# Oceanography documentation

This toolkit contains unfinished research pipelines for seven oceanographic families. Start with
[setup](SETUP.md), then follow the guides below. [TODO.txt](../TODO.txt) is the prioritized work list;
package structure and tests do not establish production completeness.

| Guide | Purpose |
| --- | --- |
| [Waves](WAVES.md) | Separate ERA5 height, mean period, FROM direction and derived sea state; conservative native support and UTC reductions |
| [Regional Waves pipelines](WAVES_REGIONAL.md) | Separate SSC nowcasts, gated USGS nearshore history, native/daily support, checkpointed acquisition and actual execution status |
| [Higher-resolution wave sources](WAVE_SOURCES.md) | Dated Salish Sea archive investigation, native metadata checks, source gaps and proposed qualification |
| [Regional gap history](REGIONAL_GAP_HISTORY.md) | Monthly hourly salinity/current subsets, independent checkpoints and bounded source eviction |
| [LiveOcean surface history](LIVEOCEAN.md) | Native low-pass salinity/oxygen/nitrate, bounded bulk-object ranges and final-Parquet retention |
| [Fast/complete scalar history](SURFACE_HISTORY.md) | Regional LO-first/SSC-only modes, monthly padded hourly fallback and final daily-grain H3 partitions |
| [Smaller SSC subsets](REGIONAL_SUBSETS.md) | Measured monthly tiling tradeoffs, whole-cell native parity and salt-only regional LO extension |
| [SSC Godin timing pilot](REGIONAL_FILTERED.md) | Native hourly 71-tap filtering, half-hour phase tests and bounded final-H3 pilot retention |
| [Ocean Conditions](DAILY.md) | Simple MUR SST and MODIS chlorophyll delivery on approved study registries |
| [Ocean Conditions history](HISTORY.md) | Resumable full-history collection, SQ/NRT precedence and explicit promotion |
| [Setup and inputs](SETUP.md) | Installation, workspace selection and required seascape artifacts |
| [Configuration](CONFIGURATION.md) | Settings, geographic assumptions, sampling and composition |
| [Workflows](WORKFLOWS.md) | Collection, offline builds, replay, comparisons and command effects |
| [Products](PRODUCTS.md) | Seven families, row identity, output files, units and missingness |
| [Architecture](ARCHITECTURE.md) | Module ownership and scientific boundaries |
| [Research methodology](RESEARCH.md) | Detailed original methods and kernel interpretation |
| [Sources](DATA_SOURCES.md) | Source contracts, attribution notes and dated availability evidence |
| [Development](DEVELOPMENT.md) | Tests, wheel checks and editing conventions |
| [Migration](MIGRATION.md) | Transfer scope and executed validation |
| [Historical pilot](history/orcacast-pilot-2026-09-10.md) | Earlier OrcaCast run; not standalone toolkit validation |
| [Transfer inventory](migration-inventory.json) | Source/destination hashes at extraction time |

No complete standalone regional run, live provider verification or map visual acceptance was
performed during the extraction. Later source-specific salinity and Waves workflows
have their own dated validation below; forecast eligibility remains unestablished.

- [HYCOM surface Ocean Conditions](COARSE.md): bounded salinity/current pilot, exact public columns, model support and historical transition limits.
- [SalishSeaCast inland surface pilot](REGIONAL.md): source-separated reference salinity and locally rotated currents, overlap limitations and executed validation.
- [HYCOM history qualification](HYCOM_HISTORY_PLAN.md): provider request limits, measured bounded alternatives, native gaps and remaining history decision point.

Native-period ENSO context: [contract and validation](CONTEXT.md).

Bounded native tide events: [contract and validation](TIDE_EVENTS.md).

[October 28 history/context checkpoint](NEXT_VARIABLES_CHECKPOINT.md) records measured resource limits and remaining source blockers.

[Measured resolution/cost tradeoffs and year-run pause](RESOLUTION_COST.md).

[GLORYS12 anonymous surface pilot](GLORYS.md).

[GLORYS12 bounded full-history plan (not started)](GLORYS_HISTORY_PLAN.md).
