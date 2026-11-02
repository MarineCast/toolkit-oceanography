# SalishSeaCast Godin-filter implementation and timing pilot

`oceanography regional-filtered-pilot` implements the same mathematical 71-tap
Godin operator as LiveOcean for SSC surface reference salinity, dissolved oxygen
and nitrate. This is a bounded timing-qualification workflow, not a resumed
historical run or an activated SSC/LO composite. Preserve original 24-hour SSC
checkpoints and completed LO outputs as distinct source products.

## Scientific contract

The [official LO weights](https://github.com/parkermac/LO/blob/main/lo_tools/lo_tools/zfun.py)
are equivalent to normalized 24-, 24- and 25-sample moving averages convolved
together: 71 positive symmetric hourly taps, offsets -35..+35. This is not a
uniform 71-hour mean or a filter of existing daily H3 means. It preserves constant
and centred linear signals and rejects exact 12/24/25-hour sinusoids. Both the
frequency and time-domain checks must pass; scientific/model accuracy remains
separate from numerical parity.

SSC source fields are public V21-11 ERDDAP hourly means with native labels at
HH:30 and a nominal T-layer depth ~0.5000003 m. Physics salinity is reference
salinity in g/kg; chemistry oxygen is mmol/m³ oxygen; biology nitrate is mmol/m³
nitrogen. Source dataset/variable/standard-name/unit, complete time axis, depth,
contiguous native indices, gzip CRC and full source hashes are validated. Requests
are padded by a calendar day on both sides, covering all required native hours.
Input geometry/weights and study support are checksum-bound; positive bathymetry
alone is insufficient. Apply the official surface T wet mask, excluding the six
previously identified boundary points, without changing any legacy checkpoint.

Filter at each native wet point before spatial aggregation. Require all weighted
hours valid, preserving real zeros; never renormalize a partial temporal window.
Assign accepted native centres directly to approved R6 keys and use native
`e1t*e2t` area weights. Salinity uses the frozen 502-cell gap target; O2/nitrate use
all 960 SSC-supported study cells. Every output date includes all 2,427 reporting
keys; unsupported values remain null. No spatial fill, bias correction, inferred
occurrence or observational certification is provided. Currents are not in this
scalar pilot; filtering vector components versus speed needs its own contract.

## Timing alternatives tested

LO's native low-pass labels are noon UTC. SSC's half-hour axis cannot put a
symmetric 71-tap window exactly at noon without an additional alignment operation.

| Variant | Evaluation time | Native inputs / operator |
| --- | --- | --- |
| `native1130` | 11:30 UTC | Exact 71 Godin taps |
| `native1230` | 12:30 UTC | Exact 71 Godin taps |
| `noon_interpolated` | 12:00 UTC | Mean of bracketing filtered estimates; effective 72 native hourly inputs |

The interpolation's Godin stage is unchanged, but the effective weights equal
the 71-tap kernel convolved with `[0.5,0.5]`. It adds a small extra smoothing step;
do not call its full effective operator identical to LO's 71 native taps. Source
intrahour averaging, surface depth, model bias and spatial support also remain
distinct. Timing sensitivity on bounded native samples is not a universal error
bound or proof of equivalent model variability.

The three scalar final Parquets use **native 12:30 / 71 inputs** and explicit
valid-time provenance. A separate final H3 comparison Parquet retains all three
variants to support review. `date` remains a daily label, not a 24-hour mean or a
silently shifted noon timestamp. Full-history phase selection is not qualified by
matching the kernel alone.

## Acquisition, retention and validation

At most two padded, surface-only, multi-day field requests run concurrently under
one aggregate **2,000,000,000-byte** budget, including registered prior source
caches and response reservations. Responses are capped at 450 MB compressed and
1.25 GB decoded, with a 20 GB free-space floor. Do not retain a decoded source
archive; streaming reduction holds at most three active daily windows. Optional
direct matrix reference is limited to seven output days and kept in memory only.

Use a new owned work root, exclusive lock and immutable study/source/code/version
plan. Network failures leave work incomplete, never successful null days. Separate
source-family archives are retained only until exact final H3 readback and regular
installed-wheel offline replay. Default CLI cleanup requires verified final
products **and required provenance**, records exact owned source hashes/paths,
and deletes only those generated payloads. External geometry, legacy checkpoints
and other-model sources are not deleted. Interrupted cleanup can resume.

The pilot accepts 1..31 output days; a full historical run is deliberately not
enabled before timing qualification. The planned tests cross both a month boundary
and the 2012/2013 year boundary. Each test checks same-phase streaming versus an
independent direct matrix calculation, installed-wheel native replay, pointwise
missingness and zero handling, field units and output identity, plus native phase
versus noon-interpolation differences. Final pilot H3 files and provenance belong
under an explicit `Data/Oceanography/pilots/` output root, without changing the
accepted global catalog.

```sh
oceanography regional-filtered-pilot \
  --study /workspace/config/study.v1.json \
  --pilot /workspace/source-geometry \
  --mask /workspace/surface-tmask.nc \
  --support /workspace/prepared-support.json \
  --output /workspace/Data/Oceanography/pilots/ssc-godin71-timing \
  --root /workspace/.marinecast-work/oceanography/ssc-godin71-timing \
  --start 2012-12-31 --end 2013-01-01 --reference \
  --shared-cache /workspace/other-task/sources
```

Run `tests/test_regional_filtered.py`, the full owner suite, `git diff --check`,
and an outside-checkout regular-wheel native acquisition and offline replay.
The command does not claim historical completion, identical intrahour source
support, model-transition calibration, scientific/model eligibility or automatic
full-run activation. Record actual native results and remaining phase decisions
separately from synthetic kernel checks.

## Executed qualification — 2026-11-01

The owner suite passed **99 tests**, with one existing NumPy/netCDF binary-size
warning. A regular wheel installed outside the checkout acquired complete padded
SSC inputs for output dates **2012-12-31/2013-01-01** and
**2013-01-31/2013-02-01**. Both year/month boundary cases passed native unit,
depth, hour-axis, complete-window and H3 identity checks. Independent matrix versus
streaming differences were at most 1.14e-13. Zero-network source replay reproduced
all final values and all three timing variants bit exactly. Native valid support
was identical across variants: 502 finite salinity and 960 oxygen/nitrate cells
per date, with all other reporting keys null.

The pooled absolute 12:30-to-interpolated-noon adjustment was:

| Field | Units | Median | 95th percentile | Maximum |
| --- | --- | --- | --- | --- |
| Salinity | g/kg | 0.00381 | 0.02737 | 0.09856 |
| Oxygen | mmol/m³ | 0.03722 | 0.20979 | 1.29756 |
| Nitrate | mmol/m³ | 0.00343 | 0.02260 | 0.13357 |

These four winter dates establish implementation/timing behavior on those
samples, not a seasonal error bound or model-transition correction. Exact 71-tap
SSC output remains explicitly 12:30; no exact-noon equivalence has been claimed.
The final comparison retains the noon alternative for review before full-history
phase selection. Currents and the full-history/composite scheduler are outside
this scalar pilot.

The subsequently implemented [surface-history runner](SURFACE_HISTORY.md) owns
monthly historical fast/complete scalar scheduling. It uses the validated exact
12:30 SSC kernel, preserves LO's noon phase and leaves this bounded pilot intact.

Both cases including offline replay/cleanup took 3.36 minutes, transferring
169.28 MB of generated hourly payloads. Peak conservative shared reservations
were 1.253 GB under the unchanged 2 GB cap. All generated pilot payloads were
removed after verified final readback/replay; eight final H3 Parquets (484,812
bytes), required provenance (123,276 bytes) and small replay/control records
remain. All 50 legacy checkpoints, four legacy state files and 13 prior accepted
product hashes are unchanged. The historical run remains paused.

See [dated findings and exact replay evidence](../../../Reports/oceanography-ssc-godin71-2026-11-01/FINDINGS.md)
and [machine validation](../../../Reports/oceanography-ssc-godin71-2026-11-01/final-validation.json).
