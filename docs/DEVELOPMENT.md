# Development and validation

[Documentation index](README.md)

## Offline checks

From the toolkit checkout, using the environment where it is installed:

```sh
python -m pip install -e '.[test]'
python -m pytest -q
git diff --check
```

The extraction recorded 17 passing tests on Python 3.14: 13 scientific fixtures and four package
checks. This is a dated result, not a claim that arbitrary future changes pass. See
[MIGRATION.md](MIGRATION.md) for the exact scope and unrun checks.

Fixtures cover units/date identity, missingness, disconnected water, current-face colocation,
request-cache integrity, trailing windows and tidal interpolation. They do not execute live
provider acquisition, real UTide reconstruction or a full regional build.

## Regular wheel smoke check

```sh
python -m pip wheel --no-deps . --wheel-dir dist
```

Install the resulting wheel into a separate environment. From outside the source checkout:

```sh
oceanography --help
oceanography init --workspace /path/to/new-smoke-workspace
```

Load configuration and import modules with OrcaCast unavailable. These checks should work without
regional datasets. A clean environment/dependency installation and supported Python runtime matrix
remain CI work in [TODO.txt](../TODO.txt); the extraction's temporary environment reused libraries.

## Editing contracts

- Keep templates under `config/` synchronized with `src/oceanography/resources/config/`.
- Preserve native dates, units, depth, grid identity, wet support and missingness in scientific edits.
- Validate feature-table keys and output schema changes; update product docs and catalog metadata.
- Keep research limitations explicit. Do not mark a source or family production-ready from imports
  or isolated arithmetic tests alone.
- Keep historical reports under `docs/history/`; identify their dates and original execution context.
  Migration inventory hashes describe the extraction snapshot, not all later documentation revisions.

Use TODO priorities to sequence work: first reproducible support handoff and publication/failure
handling, then provider/scientific validation, then broader research capabilities. No live data
collection, release promotion or application integration is implied by documentation maintenance.
