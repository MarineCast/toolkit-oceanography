# Ocean Conditions

The `oceanography.daily` command is a separate bounded satellite workflow. It does not invoke the legacy seven-family research default, river discharge, trailing composites, routing graphs or Seascape producers.

Public products contain exactly three columns:

| File | Columns | Native source |
| --- | --- | --- |
| `sst-r6-daily.parquet` | `date`, `h3_index`, `sst_c` | NOAA CoastWatch ERDDAP `jplMURSST41`, MUR v4.1, daily 0.01° gap-filled foundation SST analysis in °C |
| `chlorophyll-r5-daily.parquet` | `date`, `h3_index`, `chlorophyll_mg_m3` | `erdMH1chla1day_R2022SQ`, MODIS Aqua R2022 science-quality daily chlorophyll, approximately 4.6 km / 1/24°, mg m⁻³ |

Arrow types are date32, string and nullable float64. Every approved water-reporting cell occurs on each requested date, sorted by date then H3 key. Null means no qualified estimate; it is never replaced with zero. Chlorophyll is a biomass proxy, not a HAB label. MUR's provider interpolation is intrinsic to that source; the toolkit adds no gap filling. These are daily native source date labels (MUR 09:00 UTC, MODIS 12:00 UTC), not local-day averages. Available retrieval time does not establish historical forecast availability.

The method averages valid native pixel centres assigned to each H3 cell, weighted by cosine latitude. MUR requires open-sea and non-land mask bits and −3…45 °C; chlorophyll requires finite positive values. This is not an exact pixel/water intersection integral. Coastal source masks, clouds and coarse chlorophyll support leave narrow waterways missing. No H3 centroid is substituted for water geometry. R5 and R6 are separate supports; do not silently join or upsample them.

The shared approved study JSON supplies the acquisition planning envelope and exact independently hashed R5/R6 water-reporting registries. Its validated revision, mask, registry manifest, count and H3 resolution are verified. This family-specific interface does not require the legacy R8 graph or old Seascape directory names. Existing research CLI behavior remains unchanged.

`catalog.json` carries product paths and SHA-256 hashes, source identities, units, resolution, date range, source receipts, method and validation counts. Qualification stays outside public tables. Readers must check the file checksum before consuming a listed product. Native metadata receipts retain provider attribution/license text; no provider terms are accepted by this command. Source endpoint documentation: https://coastwatch.pfeg.noaa.gov/erddap/griddap/jplMURSST41.html and https://coastwatch.pfeg.noaa.gov/erddap/griddap/erdMH1chla1day_R2022SQ.html.

Example from the MarineCast workspace with the package installed:

```sh
python -m oceanography.daily --study config/study.v1.json --output Data/Oceanography --cache Toolkits/toolkit-oceanography/.oceanography/cache --start 2024-07-01 --end 2024-07-03 --preflight
python -m oceanography.daily --study config/study.v1.json --output Data/Oceanography --cache Toolkits/toolkit-oceanography/.oceanography/cache --start 2024-07-01 --end 2024-07-03
```

Use `--offline` to require checksum-verified receipts. Acquisition is serial and bounded to 250 MB; dates are limited to 31 days per invocation. Preflight is read-only. A failed request, malformed response or failed qualification raises an error rather than silently publishing partial success. Requests contain only regional latitude/longitude ranges and one time slice. Raw inputs remain in the explicitly supplied cache, outside Data.

Publication stages both tables and the catalog under `.marinecast-work/oceanography` outside Data, holds an exclusive writer lock, and renames the complete directory. The directory-swap interval can briefly make the destination unavailable; readers should retry a missing path rather than mixing generations. A journal restores the old directory after interruption before promotion. Previous output backups are retained outside Data; cleanup requires explicit scoped approval. No permanent deletion is performed. Public output replacement is reserved for this workflow's own delivery directory.

Validation: `python -m pytest -q tests/test_daily.py`, then `python -m pytest -q`. Build and install a regular wheel in an isolated environment; run tests from an outside-checkout copy and run the installed module with `--offline` into a separate temporary destination. Tests and synthetic checks do not certify live source coverage. Pilot evidence is in the delivered catalog and separate task validation report.
