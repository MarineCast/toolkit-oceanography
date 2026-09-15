# Oceanography documentation

This toolkit contains unfinished research pipelines for seven oceanographic families. Start with
[setup](SETUP.md), then follow the guides below. [TODO.txt](../TODO.txt) is the prioritized work list;
package structure and tests do not establish production completeness.

| Guide | Purpose |
| --- | --- |
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
performed during the extraction. Waves, general salinity products and forecast eligibility remain
outside the implemented research scope.
