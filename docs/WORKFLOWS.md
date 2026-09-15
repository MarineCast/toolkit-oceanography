# Research workflows

[Documentation index](README.md)

Start with [setup](SETUP.md) and provision the required seascape products. Commands below assume
`OCEANOGRAPHY_WORKSPACE` selects that workspace. These are execution instructions, not evidence that
a full standalone regional run has passed.

## Command effects

| Command | Behavior |
| --- | --- |
| `init` | Copies three configuration/reference files; leaves existing files intact |
| `collect` | Acquires bounded provider requests and writes acquisition manifests |
| `build` | Reads cached sources and support; writes daily research features/manifests |
| `inspect` | Reads processed products and geometry; writes HTML and report metadata |
| `compare` | Reads several families and the DFO model; writes research comparison outputs |
| `run` | Collects, builds, optionally compares, then inspects |

All commands except `init` require ordered `--start` and `--end` dates. `--family` may be repeated;
omitting it selects all seven families. Install `.[tides]` before DFO reconstruction or comparison.
`--offline` controls collection; it is not a dry run and downstream steps still write products.
`--refresh` starts a fresh immutable request-cache directory and cannot be used with `--offline`.

## Bounded single-family run

```sh
oceanography collect --family river_discharge --start 2024-07-01 --end 2024-07-03
oceanography build --family river_discharge --start 2024-07-01 --end 2024-07-03
oceanography inspect --family river_discharge --start 2024-07-01 --end 2024-07-03
```

Review acquisition errors and processed coverage before interpreting the report. Cached request
bytes are checked against their recorded SHA-256 values. Failed or changed source support must not
be represented as measured zero. A successful CLI return does not guarantee every family has data.

## Seven-day productivity window

```sh
oceanography collect --family productivity --start 2024-07-01 --end 2024-07-07
oceanography build --family productivity --start 2024-07-01 --end 2024-07-07
oceanography inspect --family productivity --start 2024-07-01 --end 2024-07-07
```

Collection and build include June 25–30 as antecedent input for this example. Composites for July 1
use June 25–July 1 only. Future observations cannot contribute. A low valid-day count remains
visible; it is not a complete seven-day observation. See [products](PRODUCTS.md).

## Replay and compare

```sh
oceanography run --family river_discharge --start 2024-07-01 --end 2024-07-03 --offline
oceanography compare --start 2024-07-01 --end 2024-07-07
```

The replay requires verified cache entries, support and matching configuration. The comparison
requires station tides, DFO tidal-model sources, regional/offshore current outputs and productivity
outputs for the interval. `compare` operates across those families; `--family` does not narrow its
implementation. A `run` including all five comparison families invokes comparison automatically.
Do not compare unlike native support as if both sources sampled the same water volume.

## Inspect outputs and limitations

Under `processed_dir`, review each `<family>/<date>/MANIFEST.json` alongside `FEATURES.parquet`.
Check status, source errors, config/source hashes, coverage and the meaning of each metric. Raw
family manifests and request manifests have different responsibilities; preserve both.

Reports are written under `report_dir/<start>_<end>/`. Inspectors limit each report to 31 days.
HTML depends on browser rendering and external map resources; file generation alone is not visual
or interaction QA. Regional support availability and provider failures can leave missing areas.

Individual writes have some atomic protection, but there is no validated transaction for a whole
family/date release. A rerun can replace daily outputs. Use separate workspaces for experiments,
retain prior validated artifacts, and follow [TODO.txt](../TODO.txt) before production promotion.
