# HYCOM surface Ocean Conditions

Published source-specific pilot products: `hycom-salinity-r5-daily.parquet`
with `date,h3_index,salinity_psu`, and `hycom-currents-r5-daily.parquet` with
`date,h3_index,current_east_m_s,current_north_m_s,current_speed_m_s`.
Dates are UTC interval starts; H3 R5 is the exact approved water reporting registry.
Every requested date/cell exists; unsupported values are null. These are modeled
conditions, not observations. R5 does not imply resolved narrow channels.

The initial source is GOFS 3.1 GLBy0.08/expt_93.0, July 1–3 2024. Select only depth
0 m (positive down), salinity (source units psu), eastward water_u and northward
water_v (m/s). Preserve psu as the provider's practical-salinity convention; do
not relabel as reference/absolute salinity g/kg. NetCDF packing/fill values must
be decoded before validation. Expected timestamps are 00,03,...,21 UTC per day.
A failed request or unexpected source axis is an error, never an all-null day.

Require all eight finite samples at each qualifying native point. Current
components share one joint valid footprint. Calculate hypot(u,v) at each native
time/point, then temporal mean; this is sampled mean speed, not speed of mean
flow or a continuous daily integral. Spatial averages use cosine-latitude
weights of native grid centres inside the approved reporting water polygon and
assigned to the same approved H3 cell. No nearest-water fill, interpolation,
land-crossing assignment, or source-missingness zero fill is permitted. Native
source fill values supply model wet support; the study mask further restricts
reporting. Different coastal masks leave explicit nulls.

Sources: https://www.hycom.org/dataserver/gofs-3pt1/analysis and
https://ncss.hycom.org/thredds/ncss/grid/GLBy0.08/expt_93.0/ts3z/2024/dataset.xml
plus corresponding uv3z metadata. HYCOM provides data as-is, public distribution
unlimited; archive availability is not guaranteed. Retain source receipts and
checksums outside Data. Publication is additive and transactional, preserving
validated SST/chlorophyll files and their product records unchanged.

Historical expansion is conditional on measured pilot requests and qualified
experiments: 53.X reanalysis through 2015, subsequent GOFS analysis experiments,
then ESPC-D-V02 from August 2024. These are not a homogeneous reanalysis. ESPC
includes tidal physics and operational best-forecast substitution; daily detided
means are unsuitable substitutes for sampled current speed. Verify native axes,
units/depth/orientation and overlapping dates before choosing documented seams.
No full-history download or scientific equivalence is established yet.

SalishSeaCast is a separate published pilot (see [REGIONAL.md](REGIONAL.md)): reference salinity g/kg at its
actual top-cell depth, with collocated and rotated geographic currents only
after grid/angle validation. No source mosaic is presently authorized as valid.

## Executed pilot — 2026-10-27

Both subsets were acquired without credentials: salinity 243,878 bytes / 52.10 s;
paired currents 450,745 bytes / 86.54 s. Each contains 24 timestamps, one depth
at 0 m, and 141×103 latitude/longitude points. Decoded arrays total about 4.2 MB.
Aggregation/staging took 1.21 s, peak resident memory 266,223,616 bytes. There are
1,680 native centres inside the study water polygon and membership; the source
wet mask further limits support. Each product has 1,389 rows (463 cells × 3 days),
546 non-null and 843 null rows per metric. Salinity 13.3524–32.8881 psu; mean
sampled speed 0.01617–0.64086 m/s. This is partial coarse support, not a claim of
complete ocean/inlet coverage. Fifteen independent date/cell comparisons included
outer-coast values and unsupported inland cells. Installed-wheel replay produced
identical output checksums. Existing satellite history checksums were unchanged.

Run from the MarineCast workspace with an installed wheel:

```sh
python -m oceanography.coarse --study config/study.v1.json --output Data/Oceanography --cache Toolkits/toolkit-oceanography/.oceanography/hycom-pilot-20261027 --start 2024-07-01 --end 2024-07-03 --offline
```

The default stages only. `--publish` promotes after validation. Existing HYCOM
products are deliberately rejected until an explicit history-preserving update
is implemented; a rerun cannot silently shrink them. All existing delivery files
are checksum-verified and hard-linked into staging without modifying their bytes.
Publication uses the shared Oceanography lock/recovery journal. Native receipts
remain outside Data. No app code is changed by this producer.

Checks: `python -m pytest -q tests/test_coarse.py`, full `python -m pytest -q`,
regular wheel build and outside-checkout offline replay. The executed suite has
37 passing tests, including five new surface/vector/missingness/identity checks.
The installed-wheel five-test run also passed. Full history is not yet acquired or validated; the separate regional pilot is documented in REGIONAL.md.

## Historical acquisition preflight — 2026-10-27

A seven-day 2009 regional request timed out after 180.2 seconds. A reduced one-day
request succeeded in 21.06 seconds / 251,120 bytes and passed the same 0 m,
psu/east-north, eight-sample and spatial qualification checks. Linear extrapolation
to 6,507 days is approximately 38 hours serial and 1.63 GB retained responses,
before retries, source transitions or newer per-file archive overhead. This is
not a reliable completion estimate. No bulk run was launched. The 2009 native axis
contains 2,887 timestamps and only 333 complete eight-sample days; 32 dates have
six or seven samples. Do not weaken completeness merely to avoid null days.
The current ESPC 2026 archive catalog contains runs through 2026-10-25 12 UTC;
valid timestamps and complete UTC days require per-file metadata checks, not
inference from run filenames. Historical experiment seams remain unqualified.
A reliable bounded strategy or authenticated alternate source must be resolved
before large acquisition; existing Copernicus credentials were not configured.


## Provider request limits

The official https://www.hycom.org/faqs specifies at most one day per NCSS
request and one simultaneous NCSS connection per IP; the general service cap
is ten connections per IP. The initial three-day pilot and seven-day preflight
predated this verification and must not be repeated over the network. Retained
pilot receipts remain replayable offline. New `coarse` acquisitions now split
into sequential one-day requests; multiday network calls fail before I/O.
Avoid the documented THREDDS maintenance windows, 02:00–03:00 and 12:00–13:00
US Eastern local time, including daylight-saving changes. The slow seven-day
request cannot be used as evidence that larger requests are a supported strategy.

The completed bounded historical qualification is in [HYCOM_HISTORY_PLAN.md](HYCOM_HISTORY_PLAN.md). Full acquisition remains unstarted; the documented provider limits and lineage gaps take precedence over earlier exploratory request examples.
