# Oceanography Toolkit

**Incomplete research implementation.** Extracted from OrcaCast into the installable
`toolkit-oceanography` distribution, with Python package and command `oceanography`.
The remaining work is tracked in [TODO.txt](TODO.txt).

Existing research families cover station tides, SalishSeaCast currents, river discharge,
satellite SST and chlorophyll, HYCOM offshore currents, and DFO WebTide harmonics.
General waves/salinity pipelines and production forecast eligibility are not implemented.

## Install and initialize

Python 3.11+:

```sh
python -m pip install -e '.[test]'
python -m pytest -q
oceanography --help
oceanography init --workspace /path/to/ocean-workspace
```

A regular `python -m pip install .` or wheel install works without OrcaCast or a sibling checkout.
Install `.[tides]` for DFO harmonic reconstruction; it pins UTide 0.3.1 because the research code
uses private UTide APIs. Initialization copies configuration/reference metadata and preserves
existing files; it does not download or build data.

## Structure

```text
src/oceanography/        Research producers, normalization, inspection and CLI
  core/config/          Local configuration support; no OrcaCast imports
  resources/config/     Packaged workspace templates
config/                 Editable configuration templates and research catalog
tests/                  Migrated scientific fixtures and package checks
docs/                   Usage, source contracts, migration and historical pilot notes
TODO.txt                Prioritized unfinished work
```

Read the [documentation index](docs/README.md), [workspace and input guide](docs/SETUP.md),
[configuration reference](docs/CONFIGURATION.md), [workflows](docs/WORKFLOWS.md),
[product definitions](docs/PRODUCTS.md), and [migration report](docs/MIGRATION.md).
Existing datasets remain in their original location. Offline tests do not establish live provider
access, regional reconstruction, map acceptance or application integration.
