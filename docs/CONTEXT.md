# Ocean context products

## ENSO: RONI ERSSTv6

Contract established 2026-10-28 before implementation. NOAA CPC public U.S. government
index: https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/roni/ .
`enso-roni-r5-seasonal.parquet` contains only `date`, `h3_index`, `roni_c`.
Each date is the END of a native three-month season, not its middle month or
publication date. Values are broadcast to every approved R5 reporting cell as
basin-scale context, not a local observation or daily measurement. No daily filling.
The source's year denotes the centre month; NDJ 2008 ends January 2009.

RONI subtracts tropical-mean SST anomalies from Niño 3.4 anomalies and adjusts
variance, using ERSSTv6 and a 1991–2020 baseline. It is distinct from ONI.
No event classification is produced. CPC updates by the fifth of each month;
recent values can be revised for two months. Historical issue dates are unavailable:
period start/end, unknown issue date, retrieval receipt and revision basis belong
in the catalog. This retrospective snapshot is not forecast eligible.
Missing periods or an unexpected source/version fail validation, rather than
becoming zero or a successful empty product. Publication preserves all existing
products, verifies checksums, and uses the existing locked atomic directory swap.

Run `python -m pytest -q tests/test_context.py`, full suite and regular-wheel
outside-checkout replay. Build from a checksummed retained HTML source with
`python -m oceanography.context --study /path/study.v1.json --source /path/roni.html
--receipt /path/roni.html.json --output /path/Data/Oceanography --start 2009-01-01
--end 2026-10-28`; add `--publish` only after staged readback.
