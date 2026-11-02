# SalishSeaCast inland surface pilot

The original pilot below is preserved. Full-study spatial gap supplements now use
the separate [monthly regional history pipeline](REGIONAL_GAP_HISTORY.md), with
independent salinity/current checkpoints and bounded generated-source eviction.

This is a source-separated July 1–3, 2024 pilot, not a HYCOM mosaic. Planned
products: `salishsea-salinity-r6-daily.parquet` with
`date,h3_index,reference_salinity_g_kg`; and `salishsea-currents-r6-daily.parquet`
with `date,h3_index,current_east_m_s,current_north_m_s,current_speed_m_s`.
Use all 2,427 approved R6 reporting cells each UTC day, null outside qualified
support. Native horizontal scale is approximately 500 m; R6 aggregation does
not imply full water-area observation. No offshore extrapolation is permitted.

Sources are SalishSeaCast ERDDAP `ubcSSg3DPhysicsFields1hV21-11`,
`ubcSSg3DuGridFields1hV21-11`, `ubcSSg3DvGridFields1hV21-11`, and geometry
`ubcSSnBathymetryV21-08`. Data are hourly means labelled at interval midpoints
00:30–23:30 UTC. Require all 24 intervals at each native location. Select only
top depth ~0.5000003 m, positive down. Salinity is **reference salinity** in
`g kg-1`, not practical salinity psu. Do not silently convert or blend HYCOM's
0 m practical salinity with this product.

Velocity fields are model-grid x/y components. Collocate adjacent C-grid faces
to tracer centres, excluding the first row/column, as documented by official
SalishSeaTools `unstagger`. Compute a local geographic grid angle from official
U-point coordinates, using the spherical geodesic direction halfway between
adjacent U points surrounding each T cell. Rotate the collocated vector into
east/north; preserve its magnitude. Validate coordinate identity against the
ERDDAP geometry and orientation against an independent spherical-bearing formula.
Do not use one constant 29-degree angle (the compressed Fraser region differs).
The coordinates file is `coordinates_seagrid_SalishSea201702.nc` from the
Apache-2.0 licensed SalishSeaCast/grid repository; retain its exact checksum.

Require positive native bathymetry, the approved water polygon, and same-cell
H3 membership. Native land values/invalid samples stay excluded. A native coastal
zero velocity is not automatically missing. Use native horizontal cell area
`e1t*e2t` for spatial weighting. Current components and speed share support;
speed is the average magnitude of collocated **hourly-mean** vectors, not the
magnitude of the daily-mean vector or the mean of instantaneous speed.

Preflight: 898×398 regional grid, three scalar variables × 24 hours × 3 days ×
4 bytes ≈309 MB; geometry 8.6 MB, coordinates 26.9 MB. Bound acquisition to
500 MB and process one day at a time under 1 GiB RAM, subject to actual measurement.
Keep source receipts/checksums outside Data. Publish source-specific products
additively only after tests, installed-wheel replay and independent checks.
No override rule is applied. Comparing overlap does not establish interchangeable
depths, salinity definitions, tidal physics or geographic support. Parent/user
must decide eventual combined versus source-separated app representation.

References: https://salishsea.eos.ubc.ca/erddap/ ;
https://github.com/SalishSeaCast/grid ;
https://salishsea-meopar-tools.readthedocs.io/en/latest/SalishSeaTools/api.html
SalishSeaCast results are Apache-2.0, credited to SalishSeaCast Project Contributors
and UBC. Cite Soontiens et al. (2016), doi:10.1080/07055900.2015.1108899, and
Soontiens & Allen (2017), doi:10.1016/j.ocemod.2017.02.008; retain dataset IDs and
retrieval dates in receipts. No scientific equivalence to observations is claimed.

## Executed result — 2026-10-27

The three-day pilot has 7,281 rows per product: 2,427 approved R6 cells × 3 UTC
days. Each metric has 2,880 non-null and 4,401 null rows (960 supported cells per
day). There are 77,097 qualified native wet centres inside study water. Reference
salinity ranges approximately 3.10e-8–32.3497 g/kg; near-freshwater model values
are preserved rather than discarded as missing. Sampled mean speed ranges
0.00508–1.41497 m/s. Processing/staging took 3.09 seconds and peak resident memory
was 950,878,208 bytes, below 1 GiB. Source retention is bounded at 500 MB.

An independent great-circle midpoint/bearing implementation and native-point
weighted calculations verified fifteen date/cell samples. The regular installed
wheel reproduced identical Parquet checksums. Forty toolkit tests and three
outside-checkout regional tests passed. Existing four public product checksums
were preserved. The regional supported R6 cells map to 192 R5 parents: 31 shared
with supported HYCOM R5 cells, 161 regional-only parents, and 151 HYCOM-only cells.
This is parent-key overlap, not exact area equivalence or a fusion validation.

```sh
python -m oceanography.regional --study config/study.v1.json --output Data/Oceanography --root Toolkits/toolkit-oceanography/.oceanography/salish-pilot-20261027 --start 2024-07-01 --end 2024-07-03
```

The command reads checksum-bound cached inputs and stages only; `--publish`
explicitly promotes validated products. It refuses to replace an existing regional
product implicitly. The bounded acquisition script and its receipts are retained
with task execution evidence; a general historical regional downloader is not yet
implemented. Checks: `python -m pytest -q tests/test_regional.py`, full suite,
regular wheel and outside-checkout offline replay. App rendering remains a
separate owner acceptance task.

For the measured low-memory historical option, see [the follow-up checkpoint](NEXT_VARIABLES_CHECKPOINT.md#follow-up-disk-safe-options-and-historical-tides) and `regional_streaming.temporal_means`. This is a validated calculation primitive, not a completed historical acquisition runner.

## Spatial comparison with GLORYS12 — 2026-10-31

A read-only check of all July 1–3, 2024 delivered rows confirms identical spatial
availability for reference salinity and all three current metrics, with 960 R6
cells supported each day. Exact geometric overlay with the GLORYS R5 reporting
footprint, using the full shared-study water mask in equal-area EPSG:6933,
finds substantial added inland support. In the Puget diagnostic rectangle
(-123.25,47.0,-122.0,48.25), SalishSeaCast provides approximately 2,122 km² of
reporting footprint where GLORYS is unavailable, or 97.2% of the GLORYS-gap
reporting-water footprint in that rectangle. This is not a formal waterbody
boundary or a measured-water coverage statistic.

Selected reference-axis probes gain support at Admiralty Inlet and Tacoma Narrows
midpoints. Some Tacoma Narrows reference positions remain unsupported. SalishSeaCast
also adds support along selected Deception Pass, Porlier Pass and San Juan Channel
segments where their GLORYS cells are null. The selected Johnstone Strait midpoint
is GLORYS-only; the regional product does not replace all northern or offshore
support. Reference segments are bounded research geometry, not complete named
passages or flow validation.

No temporal extension, source mosaic or value conversion was performed. The
three-day pilot, salinity-definition differences and distinct current-speed
semantics remain unchanged. Local workspace evidence (outside a standalone clone):
[comparison, exact checks and replay](../../../Reports/oceanography-spatial-2026-10-31/salishsea-comparison/README.md).

Full study-history extension was qualified separately on 2026-10-31. See
[live dates, bulk-transfer measurements and bounded-cache implementation plan](REGIONAL_FULL_HISTORY_PLAN.md).
The delivered three-day pilot remains unchanged; that plan is not a completed backfill.
