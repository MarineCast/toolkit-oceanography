# Higher-resolution wave sources — 2026-11-01 investigation

This is source qualification, not a new producer or dataset promotion. The accepted
[Waves product](WAVES.md) and its 21 cells with finite ERA5 height are unchanged.
The objective is better coastal/Salish Sea support from 2009 onward while retaining
all unsupported locations, dates and quantities as null.

## Finding and recommended sequence

No single continuous, high-resolution, whole-Salish-Sea archive from 2009 through
the current ERA5 frontier was verified. Two complementary sources deserve a
bounded pilot: USGS CoSMoS for historical US nearshore conditions, and SalishSeaCast
WAVEWATCH III for gridded Strait of Georgia conditions. Neither can currently be
promoted as a replacement for the whole approved R5 water domain.

1. Resolve the USGS actual output coordinates and direction/period definitions,
   then test a small historical nearshore sample from 2009 and the final complete
   native day. Keep this a distinct nearshore product until its support is qualified.
2. Qualify the SalishSeaCast **file archive**, including first/last internal times,
   missing days, run/lead selection and native wet support. Its rolling gridded
   forecast is useful for a spatial pilot, not proof of a 2009 archive.
3. Assess overlap and retain source-specific statistics and native cadence. Only
   then decide whether a source-aware height/sea-state composite is defensible.
   A full-domain, high-resolution historical hindcast is separate computational
   work if the Canadian/early-year gaps cannot be sourced.

## USGS CoSMoS: strongest verified historical nearshore lead

Primary source: [USGS regional wave metadata](https://cmgds.marine.usgs.gov/catalog/pcmsc/DataReleases/CMGDS_DR_tool/DR_P14VOPEY/Regional_CoSMoSwaves_metadata.html),
[release DOI](https://doi.org/10.5066/P14VOPEY), and its downloadable NetCDF headers.
The July 2026 release supplies reanalysis plus future scenarios, packaged by county
and sea-level condition. Only the **sea-level 000 m, historical Hs/Tm/Dm** fields
were considered. CMIP6 wave changes and raised-sea-level scenarios are excluded
from a historical environmental feature. USGS metadata specifies CC0 1.0 with
source attribution. Waves are not the separate hydrodynamic/water-level product.

Bounded HTTP-range inspection succeeded for **12 baseline county files**:
San Juan, Thurston, Snohomish, Clallam, Mason, Whatcom, King, Pierce, Skagit,
Island County, Kitsap and Jefferson. Together they contain 2,990 stored station
coordinates. They are nearshore point outputs, not a uniform high-resolution
open-water grid or coverage of all Canadian Salish Sea waters.

All twelve actual time axes have 725,473 entries, units `hours since 1941-01-01`,
with sampled endpoints **1941-01-01 00:00 to 2023-10-06 00:00 UTC**. Thus
**2023-10-05** is the last candidate complete UTC day, conditional on full temporal
and value checks. The general metadata's 2023-12-31 bound is not the observed file
frontier. Endpoint/count checks do not establish that all interior timestamps or
all wave quantities are complete. The archive contains the requested 2009 interval
within its declared axis span, but no 2024–2026 extension was verified.

| Native field | Header meaning / units | Qualification |
| --- | --- | --- |
| `Hs` | Significant wave height / m | Historical reanalysis-derived wave value |
| `Tm` | Mean wave period / s | Spectral-moment definition still needs verification |
| `Dm` | Mean direction / degree | Header says degrees relative to true north; incoming versus propagation convention remains unresolved |

Each field is packed int32 with `_FillValue=-9999`, scale factor 0.0001 and offset
0. Mask the packed fill **before** scaling. The file explicitly suppresses `Tm`
and `Dm` where `Hs < 0.05 m`; those nulls must survive even when height is valid.
The dataset uses a wave lookup table and linear swell propagation, so it is a
downscaled modeled reconstruction, not direct buoy observations or an unrestricted
hour-by-hour SWAN field archive.

**Spatial blocker:** the San Juan header, and the other inspected county headers,
state that outputs represent nearby **10 m isobath** model locations, while the
contained latitude/longitude values identify the original NetCDF station points
used to select the nearest isobath point. Explicit `lat_10mIso/lon_10mIso` arrays
were absent from the inspected San Juan file. Source clarification or the exact
model-to-output mapping is required before assigning the wave estimates to H3.
Nearest-node relocation across islands/channels is not an acceptable silent fix.

A diagnostic using the **stored original coordinates**, strict containment in the
checksum-bound approved water mask and same approved R5 membership intersects
**69 cells**, including **66 currently null ERA5 cells**; union with the 21 ERA5
cells would be 87 **stored-coordinate candidates**. This is not 87 validated wave
cells, a coverage promise, or evidence that nearshore values represent the rest of
a cell. No production null was filled. See the exact stored-coordinate arrays,
per-file counts and qualifiers in the workspace investigation evidence.

The twelve files total approximately 163.56 GB, but only about 4.18 MB was required
for one complete coordinate/header pass. The San Juan file alone is 27.43 GB.
Its Hs/Tm/Dm chunks span 80,609 hours × 44 stations (~14.2 MB decoded per field
chunk), so a one-hour request can still require a large historical chunk. HTTP
206 byte ranges were verified. Do not download all scenarios or full county files
for a qualification pilot; calculate actual compressed-chunk and disk budgets first.

## SalishSeaCast: best gridded Strait of Georgia lead

Primary sources: [wave file inventory](https://salishsea.eos.ubc.ca/erddap/tabledap/ubcSSWaveWatch3-SoGFilesV17-02.html)
and [gridded forecast metadata](https://salishsea.eos.ubc.ca/erddap/info/ubcSSf2DWaveFields30mV17-02/index.html).
They describe a WAVEWATCH III v5.16, approximately **500 m** grid, with 30-minute
outputs, about 48–50.97°N and 126–122.003°W. Fields include `hs` (m), `t02` (s),
`dir` (mean wave FROM direction), `fp` (peak frequency), and `dp` (peak direction).
T02 is a second-frequency-moment mean and must not be silently equated with ERA5
`mwp` or the unresolved USGS `Tm`. The source is Apache 2.0 with UBC/SalishSeaCast
attribution. Model results remain distinct from observed wave measurements.

The gridded feed is a moving forecast window starting five days before the most
recent forecast run, not a long reanalysis. Metadata seen through the web reader
showed 2026-10-21–2026-10-28 11:30 UTC; this is a cached observed window, not a
verified current analysis frontier. The separately advertised file inventory is
real, but its model-time coverage was **not verified**. File modification dates
and the V17-02 configuration name do not establish an archive start date.

Live search discovery succeeded. Metadata/file-list and one-time native-grid
sample requests timed out, including the alternative files interface. Therefore
no finite H3-cell count, full historical completeness, 2009 availability or
nowcast/forecast lead selection is claimed. Archive qualification can proceed
when this endpoint supports bounded reads; no publication or communication to
source maintainers was performed. Its latitude extent also excludes much of
southern Puget Sound, so it cannot alone solve that geographic gap.

## Other leads and their limits

- **PNNL/UW regional SWAN:** [provider portal](https://www.pnnl.gov/projects/ocean-dynamics-modeling/resources),
  [published study](https://doi.org/10.1016/j.ecss.2019.04.043), and
  [authors' conference description](https://ecm.github.io/ECM15/abstracts.html).
  The described five-year wave study uses 2011–2015 and covers the main Salish
  Sea basins. Its longer 1980–2015 WRF forcing span must not be reported as wave
  output coverage. The linked UW archive failed TLS hostname validation and
  HTTP redirected to the same HTTPS host. No verification was disabled; actual
  files, full rights and any broader date range remain unverified. This lead
  does not establish a 2009-to-present archive.
- **DOE/NLR US Wave West Coast:** [official data guide](https://us-marine-energy-resource.github.io/wave/hindcast/)
  and [access guide](https://us-marine-energy-resource.github.io/data-access/)
  describe 1979–2020, 3-hourly, unstructured SWAN/WW3 history, about 200 m in
  shallow water to 10 km offshore. This is a promising **outer-coast** extension,
  not verified inland Salish coverage. Native mesh/wet support, sample values
  and rights were not queried here. Preserve three-hourly cadence; do not invent
  hourly values or substitute energy/peak/zero-crossing periods for one another.
- **Copernicus WAVERYS:** the [official product](https://data.marine.copernicus.eu/product/GLOBAL_MULTIYEAR_WAV_001_032/description)
  offers a finer global 0.2° historical grid. The linked manual describes 3-hourly
  history while the product page labels hourly products as well; choose and
  verify a specific dataset/version before use. This resolution still does not
  establish narrow-channel support. No native coastal coverage was measured.

## Null-preserving extension rules

Keep the existing ERA5 history immutable during qualification. Retain every
approved reporting key but derive source eligibility separately for each location,
quantity and time. Record native source point/element IDs, wet connectivity,
representative fraction, original versus effective coordinates, native period,
source version/run/lead and per-cell/date source lineage. A single 10 m-isobath
station is not complete observation of an R5 cell.

Do not change missing height into calm, copy wave conditions across an island,
extend a regional archive before its first or after its final native time, fill
missing half-hour/three-hour samples, arithmetic-average directions, or silently
merge distinct period statistics. Preserve calm/weak-wave direction masks and
undefined circular resultants. Derive the existing WMO sea-state proxy only from
qualified height; it does not turn modeled height into an observed sea-state report.

A future pilot should test native 2009 values, a winter/summer overlap, the final
complete day, shoreline/island barriers, packed fill/scaling, low-height masks,
period/direction definitions, temporal holes and source transitions. It should
produce new source-qualified companions before any proposed composite. Regional
accuracy against NOAA/DFO/ONC buoy records and ecological/viewability suitability
remain separate validation.

## Retained evidence and checks

Workspace evidence: `Reports/oceanography-wave-sources-2026-11-01/`, especially
`usgs-native-metadata.json`, `usgs-coordinate-coverage.json`, `discovery.json`,
`details.json`, the small probe scripts and task manifest. Metadata/range payloads
remain outside Data in the task-owned `.marinecast-work/oceanography` directory.
No full county file, bulk hindcast, new production pipeline or dataset change was
made. This source/doc investigation requires scoped link/whitespace checks; it
does not claim a fresh run of the 129-test software suite or any new scientific
or application qualification.


## Subsequent implementation and qualification — 2026-11-01

The user's follow-up authorized separate pipelines. The subsequent
[regional Waves contract](WAVES_REGIONAL.md) supersedes this investigation's SSC
historical-access uncertainty: canonical daily nowcasts span 2017-04-12–2026-11-01,
with 36 missing files, and sampled native height support covers 172 R5 cells.
USGS effective geolocation remains unresolved and blocks publication. The owner
now implements both source routes, preserving ERA5 and unsupported nulls. SSC's
full backfill is queued behind an active source worker; sample qualification is
not a completed archive or final-product validation. See the contract and dated
execution evidence for the current implemented/validated/pending distinction.
