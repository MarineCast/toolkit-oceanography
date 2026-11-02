# Ocean Conditions checkpoint — 2026-10-28

## Historical salinity and currents

No HYCOM bulk retry or new account/access configuration was performed. The previous
[HYCOM qualification](HYCOM_HISTORY_PLAN.md) remains applicable. No task-scoped
Copernicus credentials were present in the checked environment/default locations;
parent is clarifying account access. GLORYS12 access/terms and its daily-mean current
semantics must be qualified before using it. Magnitude of daily-mean velocity must
not silently replace mean magnitude of subdaily velocity.

SalishSeaCast v21-11 has hourly physics/u/v and monthly physics, not a matching
native daily mean-speed product. The full surface 2009-01-01 day was acquired and
validated against existing depth/units/grid/calendar/vector contracts. All three
fields had 960 supported R6 cells out of 2,427. Source-separated practical and
reference salinity products remain unchanged.

Measured salinity/u/v decoded response sizes: 34,321,104 / 34,320,592 / 34,320,600
bytes. Requests took 11.91 / 10.88 / 10.68 seconds. Lossless gzip sizes were
7,005,093 / 7,513,630 / 7,533,201 bytes. HTTP already uses gzip; these are retained
file compression measurements, not a direct wire-byte measurement. `.nc4` was
explicitly rejected by this dataset and was not retried.

A 6,507-day extrapolation is approximately 670 GB decoded, 143.5 GB compressed,
60.5 serial acquisition hours, excluding processing/retries. This is a one-day
benchmark, not a validated history availability census or guaranteed ETA.
Free disk measured 91.3 GB. Existing one-day calculation peaked at 1.015 GB memory
footprint (1.007 GB RSS); a future runner should process hourly tiles/arrays to stay
comfortably below 1 GiB and retain only bounded native scratch plus checked daily
aggregates. Do not launch full history with the current retained-source strategy.

Next executable qualification: implement an hourly streaming accumulator preserving
24 complete intervals, grid rotation, native wet support and mean vector magnitude;
compare accepted pilot results, then measure a bounded seven-day serial run. Before
expansion, establish explicit retention/replay policy (retained native historical
arrays currently exceed free space), provider-friendly concurrency and latest actual
source dates/gaps. Keep daily checkpoints bound to source request/hash, code, geometry,
units and study. Source failures are pending failures, never successful null days.
No full-history run is active.

## Delivered context and tide pilot

ENSO: `Data/Oceanography/enso-roni-r5-seasonal.parquet`, 98,619 rows,
213 periods × 463 approved R5 cells; 2009-01-31 through 2026-09-30. Columns:
`date,h3_index,roni_c`. Range -1.6 to 2.3 degrees C. RONI ERSSTv6 is basin-scale
three-month context; date is period end, issue date unknown, monthly update with
recent revisions. It is not daily local SST. See [context contract](CONTEXT.md).

Tides: `Data/Oceanography/tide-events-r6-daily.parquet`, 7,281 rows,
July 1–3, 2024 × 2,427 approved R6 cells. Four list metrics preserve all high/low
UTC timestamps and corresponding offset-bearing local ISO8601 strings. Five stations
connect without land snapping; 153 cells/day supported, 2,274/day null. Across H3
rows: 800 high and 883 low event timestamps, duplicated only as documented station
proxies across mapped cells. No single-event reduction. Four station coordinates lie
outside the source water polygon and remain unmapped. See [tide contract](TIDE_EVENTS.md).

Seascape checksums are SHA256(filename bytes + file bytes), not plain file SHA256.
The bound inputs passed that documented convention; both hashes are recorded. No
Seascape files were edited. Code reuse changes only the optional water-polygon path
in the existing routing helper; its legacy default remains unchanged.

Both new products passed full readback, exact installed-wheel replay and preservation
of all pre-existing delivery checksums. 49 tests passed, including source/parser
failure handling, omitted final NOAA HTML row, seasonal rollover, duplicate events,
CHS bracketing and DST fold. Existing water-routing land exclusion tests passed.
No app integration is claimed; app owner must add native seasonal and list-event
rendering. Small exact handoffs are in the task directory.

## Upwelling: acquisition blocker, not a null product

CUTI author download `https://mjacox.com/wp-content/uploads/CUTI_daily.csv` returned
HTTP 406. The author's NetCDF alternative also returned 406. NOAA OceanView timed out
at 60 seconds; official Upwell and CoastWatch ERDDAP `erdCUTIdaily` metadata endpoints
both timed out at 20 seconds. No bypass, credentials or repeated bulk request was used.
No verified CUTI array is available, so no unit-inferred or fabricated product was
published. Next step is a successful permitted official mirror/endpoint response and
unit/grid/date validation. CUTI support is 31–47°N in 1° coastal latitude bands within
75 km offshore; it must not be spread through northern Salish waters or treated as
local upwelling observation. Metric name/units remain pending source metadata.

## Scope and evidence

Existing SST/chlorophyll full history and coarse/regional pilots preserved. No app,
other toolkit, Knowledge, commit, push, service or credential changes. Knowledge
handoff is left to parent because this task owns only Oceanography toolkit/Data.
No owned jobs or sleep inhibitors remain after bounded commands finish. No source
cache or prior delivery was permanently deleted. Staging is retained in the task
manifest; cleanup requires its applicable explicit permission.


## Follow-up: disk-safe options and historical tides

Measured on 2026-10-28 after the initial checkpoint:

- New `regional_streaming.temporal_means` processes one hourly surface slice per
  field, retaining all 24 intervals and calculating magnitude before temporal means.
  All four native outputs were bit-exact against the accepted full-array method on
  2009-01-01, including null masks. NetCDF replay: 0.221 seconds calculation,
  169,673,496-byte peak footprint, 222,691,328-byte maximum RSS. Direct gzip replay:
  1.051 seconds, 319,538,088-byte peak footprint, 373,096,448-byte maximum RSS.
  Compressed replay needs no uncompressed on-disk scratch and passed exact parity.
- The 77,097 needed native wet centres, including velocity-face halo requirements,
  span rows 0–897 and columns 0–386. One rectangular subset retains 97.2% of the
  original grid. Sixteen row strips retain 59.0% but require 48 requests/day rather
  than three. Dry regions already compress well; request multiplication is unlikely
  to improve compressed transfer sufficiently. No strip downloads were launched.
- A 366-day 2024 run extrapolates to 8.071 GB compressed retained source, about
  3.40 hours serial acquisition, plus small daily aggregates/outputs. This is the
  recommended bounded next acquisition option, with a 10 GB cache cap, 20 GB free
  space floor, one concurrent request, complete receipt/checksum validation and
  resumable daily checkpoints. First run a seven-day benchmark (about 155 MB) and
  confirm seasonal size variation before committing the year. Full history remains
  outside the currently feasible retained-source budget. No year/backfill launched.
- The current remote hourly datasets have no equivalent native daily mean-speed
  product. Monthly or magnitude-of-daily-vector substitution is not acceptable.

Historical tides: Neah Bay NOAA high/low predictions for December 30, 2008 through
February 2, 2009 returned 6,775 decoded bytes in 0.502 seconds. The same bounded
period for Tsawwassen CHS returned HTTP 200 with an empty array in 0.387 seconds;
this is an unqualified historical availability gap, not a successful zero-event day.
The fixed pilot mapping has 119 NOAA-supported cells (35 Neah Bay, 26 Port Townsend,
31 Cherry Point, 27 Friday Harbor) and 34 CHS-supported cells. Remaining 2,274 cells
stay unsupported; no fallback remapping is proposed when a source period is absent.

Efficient tide-history plan: padded half-year source requests, below CHS's 366-day
limit and NOAA's conservative one-year limit, only for the five mapped stations.
At most about 180 requests for 18 years, with a conservative 20 MB raw-source cap;
validate all returned event order, bracketing, classification and requested period
coverage. Preserve publication/issue-time uncertainty and current-station-coordinate
proxy interpretation. CHS historical availability and ambiguous native extrema must
be qualified before full promotion. NOAA-only historical coverage must not be
presented as all 153 pilot cells having historical values. Local-zone history must
be bound to the IANA timezone data version, especially for recent Canadian changes.

Upwelling diagnosis: one additional HEAD inspection returned Apache HTTP 406 with
HTML content type, no `Vary: Accept`, format alternatives or authentication challenge.
This does not distinguish server filtering from other rejection causes and supplies
no basis for a negotiation retry. No spoofed headers or bypass was attempted. The
previous official NOAA alternatives remain timed out; a permitted authoritative
working distribution is still required before implementation/publication of values.

Follow-up changes affect only Oceanography source/tests/docs and a bounded compressed
benchmark cache (~22 MB). The eight published products were not changed. No existing
sources were deleted and no full-year/native-history acquisition is active.
