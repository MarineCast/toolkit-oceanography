# Incomplete oceanography extraction — 2026-09-15

## Scope

Moved the existing research implementation from
`orcacast.domains.environment.oceanographic` to `oceanography` in `toolkit-oceanography`.
This is a structural extraction, not completion of the scientific pipeline. [TODO.txt](../TODO.txt)
records the remaining engineering, provider, validation and research work.

The transfer includes 11 original Python modules, the scientific tests, producer configuration,
research catalog, source documentation and historical pilot notes. Minimal shared configuration
helpers were copied locally so package installation does not require OrcaCast. Shared originals
remain in OrcaCast for its other domains. The copied helpers introduce no sibling-toolkit imports.

## Preserved and changed

| Before | After | Reason |
| --- | --- | --- |
| OrcaCast internal package | `src/oceanography` | Independent research-code ownership |
| Application configuration helpers | Local `core/config` | Remove application dependency |
| Application checkout path resolution | Current directory, `OCEANOGRAPHY_WORKSPACE`, or `--workspace` | Installed-wheel workspace support |
| Module-only command | `oceanography` CLI and `python -m oceanography` | Installable entry points |
| Source README and notes | `docs/` guides and historical pilot note | Separate usage and prior-run evidence |
| No explicit completion plan in toolkit | Root `TODO.txt` | Make unfinished work visible |

Scientific formulas, dataset meanings, provider URLs and family names were retained. Package/import
names and HTTP user-agent identity changed. CLI initialization copies packaged configuration without
overwriting user edits; CLI date requirements remain explicit for research commands. Offline and
refresh flags are rejected together. No provider migration or new scientific feature was implemented.

The [inventory](migration-inventory.json) records 22 directly transferred files with working-tree
source SHA-256 values, destination paths and extraction-time destination hashes. Later
documentation edits may differ from those snapshot hashes; the inventory is historical provenance. It includes
uncommitted source edits and the previously untracked comparison, composite, normalization and
regional-source modules. No source reset to HEAD occurred.

## OrcaCast boundary

Removed 17 transferred producer-owned files from OrcaCast, removed the oceanography entries from
its project/data configuration catalogs and generic domain-config list, and added
`docs/oceanography-extraction.md` there. No application producer implementation remains under the
old package. Unrelated dirty-worktree changes were preserved.

Existing raw data, processed products, reports and application research stay in their original
locations. Historical notes contain old paths and commands intentionally, with a dated provenance
notice. Application analyses referencing them will require explicit toolkit integration. This
extraction does not wire or validate a downstream application.

## Validation performed

- **17 tests passed** on Python 3.14: 13 migrated tests and four standalone-package checks.
  Scientific fixtures cover discharge units/date identity, missingness, kernels, disconnected water,
  current-face colocation, source timestamps, cache integrity, trailing windows, dateline handling,
  and invalid/ambiguous tidal support.
- A regular wheel built and installed into a temporary environment; `pip check` passed.
  The environment reused existing third-party libraries; a fresh dependency download was not tested.
- From outside the checkout, **17 installed submodules imported with OrcaCast imports blocked**;
  workspace initialization, configuration loading, path resolution and CLI help succeeded.
- Transfer hashes, Python 3.11 syntax, local documentation links and Git whitespace checks passed.
  Python 3.11 runtime execution and remote CI were not run.
- OrcaCast's edited project/data configuration documents and remaining workflow registrations loaded.
  This is not a full application test.

No network acquisition, actual NetCDF provider decoding, UTide reconstruction, regional support
provisioning, end-to-end standalone build, map visual QA, production publication or historical
backfill was performed. These remain open in TODO.txt. No datasets were redistributed, and no
commits or pushes were made.
