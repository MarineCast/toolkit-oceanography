# Configuration reference

[Documentation index](README.md)

The producer template is [environment_oceanographic.yaml](../config/data/environment_oceanographic.yaml).
The strict [OceanConfig model](../src/oceanography/config.py) requires schema version 1 and rejects
unknown fields. Copy templates with `oceanography init`, then edit the workspace copies.

## Workspace and geography

`--workspace` takes precedence over `OCEANOGRAPHY_WORKSPACE`; otherwise the current directory is used.
This selects the root for configuration and data. `area` names an entry in
[common.yaml](../config/common.yaml). The current routing implementation assumes the Northeast Pacific
and projects geometry to EPSG:32610; changing the bounding box alone does not establish support for
another region.

| Setting | Meaning |
| --- | --- |
| `raw_dir` | Request cache and per-family/day acquisition manifests |
| `processed_dir` | Daily normalized layers, features and build manifests |
| `report_dir` | Date-bounded HTML reports and comparisons |
| `support_dir` | Externally provisioned marine support and water graph |

These four directories must be workspace-relative, without `..` traversal. They may not be absolute.
Use [SETUP.md](SETUP.md) for the exact support filenames; installation does not generate those inputs.

## Sampling and research defaults

| Setting | Shipped value | Interpretation |
| --- | --- | --- |
| `current_interval_hours` | 4 | Six SalishSeaCast hourly-mean snapshots per day; allowed divisors are 1, 2, 3, 4, 6, 8, 12 |
| `tide_decay_km` | `[20, 40]` | Alternative normalized tide-range influence scales |
| `river_decay_km` | `[10, 25, 50]` | Alternative unnormalized discharge influence scales |
| `kernel_cutoff_multiples` | 3 | Kernel truncated at three e-folding distances |
| `min_tide_samples` | 24 | Minimum hourly station predictions retained for daily range |
| `productivity_window_days` | 7 | Fixed trailing window, including the target date |
| `productivity_min_valid_days` | 1 | A mean can exist with only one supported day; inspect counts and ages |
| `seed_snap_max_km` | 8 | Maximum candidate graph-seed distance; subject to water/connector checks |
| `seed_shore_tolerance_m` | 100 | Tolerance on short seed connectors |
| `mouth_coast_snap_max_m` | 1000 | Maximum river-mouth projection to mapped coast |
| `tide_coast_snap_max_m` | 200 | Maximum tide-station coastal projection |

Kernel scales and geometric tolerances are research assumptions, not validated transport lengths.
Do not increase tolerances just to remove unmapped stations. HYCOM sampling is separately checked
at eight three-hourly surface snapshots; `current_interval_hours` does not change that contract.

Provider settings select ERDDAP datasets, the HYCOM archive base and the DFO mesh archive. Satellite
entries record units, resolution, variable and quality controls. `tides` identifies provider/station
pairs. Each `rivers` entry supplies an explicit mouth coordinate, mapping status and rationale.
Review provider metadata before changing dataset identifiers or units.

## Validate and compose

With a workspace selected, validation is read-only:

```python
from oceanography.config import load

doc, config = load()
print(config.bbox)
print(doc.resolve_path(config.support_dir))
print(doc.config_hash)
```

The YAML loader supports `extends`. For example, save this next to the canonical producer config
as `config/data/ocean_hourly.yaml`:

```yaml
extends: environment_oceanographic.yaml
current_interval_hours: 1
```

Then pass `--config config/data/ocean_hourly.yaml`. Mappings deep-merge and lists replace inherited
lists. Config hashes are checked against acquisition manifests during builds: a new config cannot
silently reuse old family manifests just because the underlying bytes are cached. Collect under
the intended config first, using `--offline` if verified request snapshots are already present.
