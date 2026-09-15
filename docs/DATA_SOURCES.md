# Oceanographic sources and evidence dates

[Documentation index](README.md)

## Evidence boundary

Provider endpoints below describe the configured implementation and historical discovery notes.
They were not re-queried for this documentation update. Archive-end dates and access outcomes are
dated observations, not current service guarantees. Verify provider terms and required attribution
before redistribution; no source datasets are bundled with the toolkit.

## Original pilot sources

Source discovery and public API collection were exercised on 2026-09-10. Raw request manifests retain exact URLs, retrieval times, byte counts, and hashes. The executed initial pilot is 2024-07-01 through 2024-07-03, not the full archives below.

| Source | Access and scope | Availability and rights |
|---|---|---|
| [CHS Integrated Water Level System](https://www.tides.gc.ca/en/web-services-offered-canadian-hydrographic-service) | `https://api-sine.dfo-mpo.gc.ca/api/v1/stations`; `/stations/{id}/data`, `time-series-code=wlp`, `resolution=SIXTY_MINUTES`. Canadian astronomical tide predictions. | CHS service terms apply; do not assume an unrestricted blanket public-domain license. Cache station metadata and keep predictions separate from measured levels. Four configured BC stations. |
| [NOAA CO-OPS](https://api.tidesandcurrents.noaa.gov/api/dev) | `https://api.tidesandcurrents.noaa.gov/api/prod/datagetter`, `product=predictions`, `interval=h`, `units=metric`, `time_zone=gmt`, `datum=MLLW`; MDAPI station inventory. | US federal data; retain NOAA attribution and service disclaimers. Five configured Washington stations. |
| [SalishSeaCast U grid](https://salishsea.eos.ubc.ca/erddap/info/ubcSSg3DuGridFields1hV21-11/index.html) / [V grid](https://salishsea.eos.ubc.ca/erddap/info/ubcSSg3DvGridFields1hV21-11/index.html) | Regional NEMO historical hourly means; `uVelocity`, `vVelocity`; surface depth about 0.5 m. Bathymetry/geolocation `ubcSSnBathymetryV21-08`. Native 898 × 398 curvilinear staggered grid. | Metadata observed in the 2026-09-10 pilot: 2007-01-01 through 2026-09-09. UBC/SalishSeaCast contributors, Apache 2.0; retain metadata acknowledgements and cite Soontiens et al. (2016), Soontiens & Allen (2017) for research use. Not full outer-coast coverage. |
| [ECCC hydrometric daily means](https://api.weather.gc.ca/collections/hydrometric-daily-mean) | OGC Features by `STATION_NUMBER` and date; `DISCHARGE` in m³/s; pagination followed. Separate from recent realtime collections. | Government of Canada open-data terms and ECCC attribution; retain discharge symbols. Historical completeness and latest published year differ by station. Current/complete daily records are not promised merely because a station is active. |
| [USGS modern OGC API](https://api.waterdata.usgs.gov/docs/ogcapi/) | `/ogcapi/v0/collections/daily/items`, `parameter_code=00060`, `statistic_id=00003`, `monitoring_location_id=USGS-...`. Pagination followed; strict units conversion. | USGS attribution and data disclaimers; retain `approval_status`, qualifiers, and revisions. Public unauthenticated pilot requests worked; rate-limit backoff is bounded. |
| NOAA ACSPO SST `noaacwLEOACSPOSSTL3SCDaily` | PolarWatch ERDDAP: 0.02° daily global SST in °C plus quality level. Regional bounding-box downloads; retain quality 4–5. | Retrieved metadata: 2000-02-24 through 2026-07-07. Dataset title and actual metadata dates can differ; code uses metadata and validates returned dates. Raw metadata includes NOAA attribution/license text. No observation inferred in cloud/coastal gaps. |
| NOAA VIIRS chlorophyll `noaacwNPPVIIRSSQchlaDaily` | PolarWatch ERDDAP: daily science-quality global ~4 km `chlor_a` in mg m⁻³. | Retrieved metadata: 2012-01-02 through 2026-08-31. Raw metadata includes NOAA attribution/license text. Positive valid retrievals only; chlorophyll is a biomass proxy, not primary production. |

The newer merged VIIRS dataset title looked suitable, but the tested PolarWatch mirror `noaacwNPPN20VIIRSchlociDaily` stopped in 2021. It was rejected for this pilot rather than silently pulling the nearest old date. NOAA PFEG/other candidate endpoints had connectivity or access failures during discovery; the selected PolarWatch endpoints returned real regional NetCDF data.

The configured bounds come from `config/common.yaml` (`model_area`). Gauges may be outside that marine rectangle: Fraser at Hope is intentionally retained because its river drains into the model region. Geographic coverage follows the water polygon and native source support, not a simple BC/WA latitude split.


## Additional implemented research sources

| Family | Configured adapter | Preserved contract and unfinished checks |
| --- | --- | --- |
| `offshore_currents` | HYCOM GOFS 3.1 `GLBy0.08/expt_93.0/uv3z`, with year appended to the NCSS base | Requests `water_u`/`water_v` at depth zero; verifies eight three-hourly valid times and velocity units before R5 aggregation. Provider archive/rights and regional overlap need renewed validation. |
| `tidal_model` | DFO WebTide Northeast Pacific v0.7 archive selected by `tide_model_url` | Reads embedded ZIP data without executing the installer; interpolates complex harmonics inside valid mesh triangles, then reconstructs with UTide 0.3.1. Outside or ambiguous support remains missing. Source rights, model coverage and withheld-station validation remain open. |

See [regional_sources.py](../src/oceanography/regional_sources.py) for executable request and
validation logic and [configuration](CONFIGURATION.md) for the checked-in settings. These two
families extend the initial five-family pilot description. Their presence in code is not evidence
of a newly completed comparison, production coverage or current provider availability.
