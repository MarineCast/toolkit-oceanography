# Tide event pilot contract

Contract established 2026-10-28. Native predicted high/low events, not observed
water levels, hourly sampled extrema or surge forecasts. NOAA CO-OPS uses `interval=hilo`,
`time_zone=gmt`; CHS IWLS uses `wlp-hilo` with a maximum 366-day request. The pilot
retains padded June 30–July 4 source events for July 1–3, 2024. U.S. government
NOAA data and CHS Open Government Licence attribution remain in receipts/catalog.

Public `tide-events-r6-daily.parquet`: `date`, `h3_index`, `high_tide_times_utc`,
`low_tide_times_utc`, `high_tide_local_times`, `low_tide_local_times`.
UTC fields are lists of UTC timestamps; local fields are corresponding ISO8601
strings with numeric UTC offset. Every native event is retained, sorted by UTC;
`date` is its UTC day. Local calendar dates may differ. IANA station timezones
are stored separately. No single-high/single-low reduction. Null lists mean
unsupported; empty lists mean a qualified day with no event of that type.
NOAA event types are explicit. CHS omits types: classify only a strict extremum
relative to both bracketing native event heights, failing on equal/ambiguous values.
Heights are used within a station only and are not published or mixed across datums.

Spatial support is a station-timing proxy, not an interpolated local tidal phase.
Use checksummed Seascape R8 water-passable graph and its representative water
points. Station connectors must stay entirely in the water polygon, with no
shoreline buffering or land snapping. A 20 km water-path limit bounds candidate
station influence. Each approved R6 cell chooses the nearest connected R8 child
and station, deterministically; this does not establish uniform timing over that
cell. All approved R6 cells are emitted; unsupported cells stay null. Keep source
station, distance and mapping qualifications outside the public table. This
research proxy must not be used for navigation. No offshore extrapolation.

The pilot is retrospective; source issue dates are unknown. Current source
predictions do not establish what forecasts were available historically. Historical
expansion requires station/timezone and prediction-regime qualification, not merely
repeating the pilot. Test DST transitions, event multiplicity, null versus empty,
classification, source errors, checksums, membership and publication preservation.
