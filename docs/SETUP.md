# Workspace, prerequisites and commands

Use the [root installation instructions](../README.md), then initialize a dedicated workspace.
`--workspace` overrides `OCEANOGRAPHY_WORKSPACE`; without either, paths use the current directory.
The Python API follows the environment-variable/current-directory rule too.

```sh
export OCEANOGRAPHY_WORKSPACE=/path/to/ocean-workspace
oceanography init
```

Edit `config/common.yaml` for named geography and `config/data/environment_oceanographic.yaml`
for provider settings, gauges, stations, kernels, and input/output directories. Paths in that
producer configuration must be workspace-relative and cannot contain parent traversal.
Defaults retain the Northeast Pacific pilot assumptions; spatial routing uses EPSG:32610.
The packaged `config/feature_catalog.yaml` is an inherited research catalog, not a completed schema registry.

## Required external seascape products

The configured `support_dir` defaults to
`data/processed/domain/environmental_layer/seascape/spatial_support`. Provision validated products
at that location (or another relative location selected in configuration):

| Relative path beneath support_dir | Used for |
| --- | --- |
| `h3_geometry/H3_MODEL_AREA_SUPPORT_RES_6.parquet` | Marine overlap and water-area support; R5 parent aggregation |
| `h3_geometry/H3_MODEL_AREA_SUPPORT_RES_8.parquet` | Fine-grid water graph and influence support |
| `water_network/H3_WATER_PASSABLE_EDGES_RES_8.parquet` | Water-constrained routing |
| `water_geometry/TERRITORIAL_WATER_POLYGON.parquet` | Water and coastal seed geometry |
| `h3_geometry/H3_MARINE_WATER_CLIPPED_GEOMETRY_RES_6.parquet` | Inspection-map geometry |

These are data dependencies on toolkit-seascape's product contracts, not Python imports. Installing
this package does not create them. No support artifacts were transferred with the extraction.
The build currently fingerprints all four non-map inputs even for a selected single family.
A formal preflight/compatibility gate remains in TODO.txt.

## Research commands

Use explicit bounded dates and select families deliberately:

```sh
oceanography collect --family river_discharge --start 2024-07-01 --end 2024-07-03
oceanography build --family river_discharge --start 2024-07-01 --end 2024-07-03
oceanography inspect --family river_discharge --start 2024-07-01 --end 2024-07-03
```

`collect` makes network requests; `build` and `inspect` use local files. `run` chains collection,
build and inspection (plus comparison when the required families are included). `--offline` allows
collection only from verified cache entries. `--refresh` makes a new request-cache directory;
it cannot be combined with `--offline`. Existing daily outputs are not a protected release snapshot:
use isolated workspaces for experimental runs until publication hardening is complete.

Family names: `tides`, `currents`, `river_discharge`, `ocean_temperature`, `productivity`,
`offshore_currents`, `tidal_model`. Omitting `--family` selects all seven. Productivity requests
include the preceding six days for its trailing window. Inspection reports are limited to 31 days.

Source errors, coverage and provenance appear in per-family manifests. Inspect those records before
interpreting a command's successful return as scientific success; stricter aggregate exit-status
behavior is unfinished. Full standalone acquisition/rebuild and visual map QA have not been run.

Continue with the [configuration reference](CONFIGURATION.md), [workflow guide](WORKFLOWS.md),
and [product definitions](PRODUCTS.md). Use [development](DEVELOPMENT.md) for package validation.
