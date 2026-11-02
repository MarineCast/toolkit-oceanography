# GLORYS12 surface conditions

Contract established 2026-10-29 before adding this producer. July 1–3, 2024 only,
full approved R5 reporting membership, null where no valid native wet centres lie
inside the reporting water mask and same H3 cell. No interpolation, nearest-water
fill, inland extrapolation or replacement of accepted products.

Official product GLOBAL_MULTIYEAR_PHY_001_030; dataset
cmems_mod_glo_phy_my_0.083deg_P1D-m, version 202311. The official public STAC
catalog advertises timeChunked Zarr data assets for direct library access. Anonymous
metadata, coordinate and actual surface data reads returned HTTP 200 without login.
No passwords, browser cookies, tokens, credential files or auth configuration were
accessed. The official data licence remains applicable; attribution is Copernicus
Marine Service, DOI 10.48670/moi-00021. Public STAC licence points to
https://marine.copernicus.eu/user-corner/service-commitments-and-licence .

The approximately 1/12-degree regular grid contains already-collocated geographic
east/north components. The official manual (Issue 1.7, November 2025) defines daily
means over midnight-to-midnight, centred at noon. ARCO labels are at midnight; the
calendar day label is retained, with this distinction recorded externally. ARCO
uses negative elevation values despite inherited positive=down attributes. Select
the shallowest magnitude, -0.494024992 m, and report physical depth 0.494024992 m
below surface, consistent with the official positive-depth table. Never select
array index zero, which is deepest in this ARCO store. Gregorian calendar.

Outputs are source-separated: `glorys12-salinity-r5-daily.parquet` contains
`date,h3_index,salinity_psu`; `glorys12-currents-r5-daily.parquet` contains
`date,h3_index,current_east_m_s,current_north_m_s,current_daily_mean_vector_speed_m_s`.
Salinity is practical salinity (provider units 1e-3, unit_long Practical Salinity
Unit), not SalishSeaCast reference salinity g/kg. Current components are m/s.
Speed is the spatially weighted mean of native magnitudes of DAILY mean vectors,
not mean hourly speed, and not the magnitude of the spatially averaged vector.
Native cell weights are cos(latitude), appropriate to the regular angular grid.
Require wet-mask=1, finite paired currents, physical range checks and exact dates.
Metadata, receipts, units, source versions and method live outside the public tables.

The manual explicitly states tidal constituents are NOT included. Thus these
currents cannot substitute for tidal-flow detail in SalishSeaCast or navigational
predictions. A global model's geographic extent does not guarantee narrow-water
support. The pilot has explicit Puget Sound and narrow-passage coverage diagnostics.
Recent historical extension may include an interim reanalysis regime; do not assume
all dates have homogeneous final quality or silently append operational forecasts.
Full history was subsequently authorized and published; see the history completion below.

The source-native chunk boundaries overfetch adjacent ocean area but only two
latitude chunks at the single surface level per variable/day are retrieved; no
global grid or all-depth acquisition. Retain checksummed raw chunks and metadata
for offline replay. The producer stages additive products; existing delivery remains
unchanged until explicit promotion. Validate with `tests/test_glorys.py`, full suite,
regular-wheel offline replay and full staged readback. Install optional `[copernicus]`
for the public Zarr compression codec; the toolbox/login are not required here.


## Verified pilot outcome, 2026-10-29

Anonymous requests to the official STAC-linked data assets succeeded. Dataset time
axis actually read: 1993-01-01 through 2026-09-22. This is not a claim of homogeneous
final-quality reanalysis throughout, nor of coverage through today's date. No
operational product was appended. No authentication step is required for this
public-asset pilot; browser/toolbox login remains a separate facility.

Twenty surface/mask chunks totalled 16,514,372 retained bytes and 7.244 seconds
summed serial request time. Complete offline source verification/decoding/mapping
required 0.606 seconds; the installed-wheel validation process took 1.74 seconds
including startup/readback, with 205 MB peak footprint (262 MB maximum RSS).
Spatial subset: 68 × 99 grid points; 3,659 native wet points within the acquisition
rectangle, 625 native wet centres also inside approved reporting water/H3 support.

Each product contains 1,389 rows (463 approved R5 cells × three dates). Each metric
has 735 nonnull and 654 null rows: 245 supported and 218 unsupported cells/day.
Salinity range 12.4958–31.8155 psu. Daily-vector speed range 0.001365–0.775615 m/s.
Seattle waterfront, Tacoma and Vancouver Harbour probe cells are null. The Puget
diagnostic rectangle (-123.25,47.0,-122.0,48.25) contains 41 approved R5 cell centres,
only three supported. A northern-passages rectangle (-126.5,49.75,-124.5,51.0)
contains 60 approved centres, 24 supported. These diagnostic rectangles are not
formal waterbody boundaries. A supported coarse cell does not prove resolution of
an individual narrow passage or uniform conditions throughout that cell.

Recommendation: appropriate as a broad background product with explicit nulls;
not a universal replacement for inland SalishSeaCast coverage or tidal currents.
Retain existing sources and products. Before a full-history decision, benchmark a
month to test variable chunk size, latency, caching and reanalysis regime boundaries.
Three-day extrapolation suggests much lower cost than native Salish hourly history,
but does not establish a guaranteed full-history runtime/storage requirement.

57 tests passed, including canonical numcodecs decompression and xarray CF unpack
comparison, surface-index/sign guard, distinct speed semantics and prior regressions.
Installed-wheel replay was byte-identical to the first staged Parquets and exactly
matched the independently extracted pilot frame. Complete readback, all date/member
identities and representative inland nulls passed. All eight published product
checksums remain unchanged. New products are staged, not promoted; the precise
stage/catalog/product checksums and coverage evidence are in the task handoff.


## Local catalog integration

Published locally on 2026-10-29 after explicit parent authorization. Both pilot
files and their source-specific records are now in `Data/Oceanography/catalog.json`;
all eight pre-existing products retain their exact checksums. No source was replaced
or deleted. Exact app handoff: task file `glorys-pilot-handoff.json` (`published=true`).
The app should keep GLORYS12 distinct from HYCOM and SalishSeaCast; display the speed
as magnitude of daily mean currents, with no tidal constituents. Its local coverage
is 245/463 cells; unsupported cells must remain visually missing, not nearest-filled.
Full history is now published; see [the corrected plan and measured completion](GLORYS_HISTORY_PLAN.md).

## Full history, 2026-10-29

Both local GLORYS products now span 2009-01-01–2026-09-22, 2,997,462 rows each, 463 approved R5 cells/date, 6,474 daily row groups. All pilot values are preserved. The official Time Series (`geoChunked`) layout provides identical values much more efficiently for history; a short-period layout is not a valid cost model when time-optimized storage exists. Native daily definitions, depth, practical salinity, missingness and no-tides limitation remain unchanged.

External catalog provenance distinguishes documented reanalysis through 2021-06-30 and interim NRT-assimilation lineage from 2021-07-01, based on QUID section V page 50. No later authoritative final reprocessing was established. The 2019-01-01 atmospheric forcing change is separate. Retrospective values are not forecast-eligible. See GLORYS_HISTORY_PLAN.md for exact timings, source receipts, checksums and limitations.

## Spatial support review — 2026-10-31

A read-only check of all 6,474 delivered days verified identical salinity and
three-metric current support: 245 R5 cells always supported and 218 always null,
with exact daily membership and catalog checksums. Independently decoded retained
native geometry/wet-mask inputs reproduce that footprint using 625 accepted wet
centres. Of the missing cells, 138 have no native centres inside reporting water;
80 have eligible centres that are all source dry. These are cell counts, not
fractions of water area, and do not authorize interpolation or filling.

The existing diagnostic rectangles still give 3/41 supported centres for Puget
and 24/60 for northern passages; they are not formal waterbody boundaries.
Selected Seascape research-axis probes find Admiralty Inlet's midpoint and the
sampled Tacoma Narrows segment unsupported. San Juan Channel, Sansum Narrows and
Porlier Pass midpoint cells have estimates, but their nearest accepted native
points are approximately 13.2, 11.1 and 11.1 km away respectively. Straight-line
distance is not water connectivity or a physical-accuracy test. A supported R5
cell must not be represented as resolving its narrow channels. The no-tides
limitation also remains unchanged.

Local workspace QA (outside this standalone clone):
[audit, map evidence and replay instructions](../../../Reports/oceanography-spatial-2026-10-31/README.md).
This reviews spatial support only; no source acquisition, delivered-data change,
producer behavior change, scientific validation against observations, or new
forecast eligibility was performed.
