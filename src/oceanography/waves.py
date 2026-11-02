"""Separate ERA5 Waves: strict native water-centre support, no gap filling."""
from contextlib import ExitStack
import argparse
import datetime as dt
import fcntl
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import uuid
from types import SimpleNamespace

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import shapely

from .daily import sha, study_inputs, publish, recover
from .history import atomic_json
from .waves_source import Source, BASE, FIELDS

METHOD = 'era5-native-water-centres-r5-waves-utc-v1'
HEIGHT_BOUNDS = np.array([0., .1, .5, 1.25, 2.5, 4., 6., 9., 14.])
STATE_LABELS = ['calm_glassy', 'calm_rippled', 'smooth_wavelets', 'slight', 'moderate',
                'rough', 'very_rough', 'high', 'very_high', 'phenomenal']
HOURLY = ['significant_wave_height_m', 'mean_wave_period_s', 'mean_wave_direction_from_deg', 'sea_state_code']
DAILY = ['significant_wave_height_mean_m', 'significant_wave_height_max_m', 'mean_wave_period_mean_s',
         'mean_wave_direction_from_circular_mean_deg', 'sea_state_code_max']


def sea_state(height):
    """WMO 3700 height-derived proxy; exact positive bounds stay in lower class."""
    a = np.asarray(height, dtype=float)
    return np.where(np.isfinite(a) & (a >= 0), np.searchsorted(HEIGHT_BOUNDS, a, side='left'), np.nan)


def sanitize(raw):
    height, period, direction = np.asarray(raw, dtype=float).copy()
    height = np.where(np.isfinite(height) & (height >= 0), height, np.nan)
    period = np.where(np.isfinite(period) & (period > 0), period, np.nan)
    direction = np.where(np.isfinite(direction) & (direction >= 0) & (direction <= 360)
                         & (height != 0), direction % 360, np.nan)
    return height, period, direction


def summarize(hourly):
    """Complete-day independent scalar support and equal-time circular direction."""
    height, period, direction = hourly
    good_h = np.isfinite(height).sum(axis=0) == 24
    good_p = np.isfinite(period).sum(axis=0) == 24
    good_d = np.isfinite(direction).sum(axis=0) == 24
    height_mean = np.where(good_h, np.where(np.isfinite(height), height, 0).sum(axis=0)/24, np.nan)
    height_max = np.where(good_h, np.where(np.isfinite(height), height, -np.inf).max(axis=0), np.nan)
    period_mean = np.where(good_p, np.where(np.isfinite(period), period, 0).sum(axis=0)/24, np.nan)
    radians = np.deg2rad(np.where(np.isfinite(direction), direction, 0))
    s, c = np.sin(radians).mean(axis=0), np.cos(radians).mean(axis=0)
    angle = np.degrees(np.arctan2(s, c)) % 360
    angle = np.where(np.isclose(angle, 360, rtol=0, atol=1e-10), 0, angle)
    angle = np.where(good_d & (np.hypot(s, c) > 1e-12), angle, np.nan)
    return [height_mean, height_max, period_mean, angle, sea_state(height_max)]


def schema(frequency):
    names = HOURLY if frequency == 'hourly' else DAILY
    key = ('datetime', pa.timestamp('us', tz='UTC')) if frequency == 'hourly' else ('date', pa.date32())
    return pa.schema([key, ('h3_index', pa.string()),
                      *[(n, pa.int8() if 'sea_state' in n else pa.float64()) for n in names]])


def spatial_support(study_path, source, study, cells):
    """Actual native centres; no nearest-wet or footprint extrapolation."""
    mask_path = (Path(study_path).resolve().parent/study['grid_registry']['mask_relative_path']).resolve()
    water = gpd.read_parquet(mask_path)
    if water.crs.to_epsg() != 4326:
        raise ValueError('Wave study water mask must be WGS84')
    geometry = water.geometry.union_all()
    west, south, east, north = study['domain']['bbox_wgs84']
    yi = np.flatnonzero((source.lat >= south) & (source.lat <= north))
    xi = np.flatnonzero((source.lon >= west) & (source.lon <= east))
    allowed = set(cells)
    points = []
    for y in yi:
        for x in xi:
            lat, lon = float(source.lat[y]), float(source.lon[x])
            cell = h3.latlng_to_cell(lat, lon, 5)
            if cell in allowed and shapely.contains_xy(geometry, lon, lat):
                points.append(dict(y=int(y), x=int(x), latitude=lat, longitude=lon, h3_index=cell))
    if len({p['h3_index'] for p in points}) != len(points):
        raise ValueError('This strict point product requires at most one native centre per R5 cell')
    return points


def tables(day, raw, points, cells):
    indices = {cell: i for i, cell in enumerate(cells)}
    values = np.full((3, 24, len(cells)), np.nan)
    clean = sanitize(raw)
    for j, point in enumerate(points):
        values[:, :, indices[point['h3_index']]] = np.asarray(clean)[:, :, j]
    hourly = [*values, sea_state(values[0])]
    daily = summarize(values)
    result = {}
    for frequency, arrays, names in [('hourly', hourly, HOURLY), ('daily', daily, DAILY)]:
        n = 24 if frequency == 'hourly' else 1
        key = ('datetime', pa.array(pd.date_range(day, periods=24, freq='h', tz='UTC').repeat(len(cells)),
                                   type=pa.timestamp('us', tz='UTC'))) if n == 24 else ('date', pa.array([day]*len(cells), type=pa.date32()))
        columns = {key[0]: key[1], 'h3_index': pa.array(list(cells)*n)}
        for name, a in zip(names, arrays):
            a = a.ravel()
            columns[name] = pa.array(np.where(np.isfinite(a), a, 0), mask=~np.isfinite(a),
                                    type=pa.int8() if 'sea_state' in name else pa.float64())
        result[frequency] = pa.Table.from_pydict(columns, schema=schema(frequency))
    return result


def conventions():
    return dict(product='waves', method=METHOD, h3_resolution=5, timezone='UTC',
        hourly_time='instantaneous native samples at exact UTC hours; not hourly means',
        daily_time='UTC day 00:00 through 23:00; 24 finite samples per quantity required',
        direction='degrees clockwise from true north, coming FROM; equal-time circular daily mean',
        period='source mean wave period mwp, not peak period',
        height='significant height of combined wind waves and swell',
        spatial_method='native centres strictly inside approved water mask and same R5; no nearest-wet, interpolation or filling',
        sea_state=dict(definition='WMO 3700 height-derived proxy, not observed sea state or Beaufort wind force',
            upper_bounds_m=HEIGHT_BOUNDS.tolist(), exact_bounds='lower category', labels=STATE_LABELS,
            daily='maximum hourly code; complete height support required'),
        units={**{n: ('derived WMO category' if 'sea_state' in n else 'm' if 'height' in n else 's' if 'period' in n else 'degree true FROM')
                   for n in HOURLY+DAILY}})


def _directory(output):
    expected = {'catalog.json', 'waves-hourly.parquet', 'waves-daily.parquet'}
    if output.is_symlink() or (output.exists() and not output.is_dir()):
        raise ValueError('Waves output must be a dedicated regular directory')
    if output.exists() and any(p.name not in expected or not p.is_file() or p.is_symlink() for p in output.iterdir()):
        raise ValueError('Unrelated Waves output entries; preserved')


def _sources(cache, output):
    expected = dict(pipeline='waves', output=str(output))
    marker = cache/'ownership.json'
    if cache.is_symlink():
        raise ValueError('Symlink source cache refused')
    if cache.exists() and any(cache.iterdir()):
        if not marker.is_file() or marker.is_symlink() or json.loads(marker.read_text()) != expected:
            raise ValueError('Waves source ownership mismatch; preserved')
    else:
        cache.mkdir(parents=True, exist_ok=True)
        atomic_json(marker, expected)


def run_waves(study_path, start=None, end=None, *, output=None, cache_dir=None,
              shared_caches=(), offline=False, rebuild=False, allow_partial_final_day=False):
    """Build/append a separate Waves product, preserving all unrelated deliveries."""
    if any(type(v) is not bool for v in (offline, rebuild, allow_partial_final_day)):
        raise ValueError('Waves mode flags must be booleans')
    provided = [dt.date.fromisoformat(str(d)) if d is not None else None for d in (start, end)]
    if all(provided) and provided[0] > provided[1]:
        raise ValueError('Waves dates are reversed')
    study, members, evidence = study_inputs(study_path)
    cells = members[5]
    first = provided[0] or dt.date.fromisoformat(study['time']['start'])
    limit = dt.date.fromisoformat(study['time']['end_exclusive'])-dt.timedelta(days=1)
    if first < dt.date.fromisoformat(study['time']['start']) or first > limit or (provided[1] and not first <= provided[1] <= limit):
        raise ValueError('Waves dates must be inside the approved study')
    data_root = (Path(study_path).resolve().parent/study['storage']['data_root']).resolve()
    output = Path(output).expanduser().absolute() if output else data_root/'Oceanography'/'waves'
    if output.is_symlink():
        raise ValueError('Symlink Waves delivery refused')
    output = output.resolve()
    _directory(output)
    identity = hashlib.sha256(str(output).encode()).hexdigest()[:16]
    control = data_root.parent/'.marinecast-work'/'oceanography'/('waves-'+identity)
    cache = Path(cache_dir).expanduser().absolute() if cache_dir else control/'sources'
    if cache.is_symlink() or cache.resolve() == output or cache.resolve() in output.parents or output in cache.resolve().parents:
        raise ValueError('Separate Waves cache and delivery roots required')
    cache = cache.resolve()
    control.mkdir(parents=True, exist_ok=True)
    code = {n: sha(Path(__file__).parent/n) for n in ('waves.py', 'waves_source.py', 'daily.py')}
    with (control/'publication.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        recover(output, control)
        old = None
        if output.exists() and any(output.iterdir()):
            check_waves(output/'catalog.json', study_path=study_path)
            old = json.loads((output/'catalog.json').read_text())
            if not rebuild and old['code_sha256'] != code:
                raise ValueError('Changed wave code requires explicit rebuild')
            if not rebuild and provided[1] and old['date_start'] <= str(first) and old['date_end'] >= str(provided[1]):
                return dict(catalog_path=str(output/'catalog.json'), unchanged=True)
        if shutil.disk_usage(control).free < 22_000_000_000:
            raise ValueError('Waves require staging headroom above the 20 GB disk floor')
        _sources(cache, output)
        with (control/'sources.lock').open('a') as source_lock:
            fcntl.flock(source_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Online updates need fresh time coordinates and recent ERA5(T)
            # chunks. Preserve older retrievals and count all snapshots together.
            payload_cache = cache if offline else cache/('retrieval-'+uuid.uuid4().hex)
            source = Source(payload_cache, offline=offline, shared=shared_caches, budget_root=cache)
            frontier = pd.Timestamp(source.times[-1], unit='s', tz='UTC')
            last = provided[1] or min(limit, frontier.date() if allow_partial_final_day or frontier.hour == 23 else frontier.date()-dt.timedelta(days=1))
            if first > last or last > frontier.date() or (last == frontier.date() and frontier.hour != 23 and not allow_partial_final_day):
                raise ValueError('Waves dates exceed complete source support')
            points = spatial_support(study_path, source, study, cells)
            if not points:
                raise ValueError('No native wave centres intersect approved reporting water')
            retained = old if old and not rebuild else None
            old_first = dt.date.fromisoformat(retained['date_start']) if retained else None
            old_last = dt.date.fromisoformat(retained['date_end']) if retained else None
            if retained and retained['native_points'] != points:
                raise ValueError('Wave native support changed; explicit rebuild required')
            grid = {name: dict(count=len(axis), first=float(axis[0]), last=float(axis[-1]), spacing=.5)
                    for name, axis in (('latitude', source.lat), ('longitude', source.lon))}
            if retained and retained['native_grid'] != grid:
                raise ValueError('Wave grid changed; explicit rebuild required')
            if retained and old_first <= first and old_last >= last:
                return dict(catalog_path=str(output/'catalog.json'), unchanged=True)
            if retained:
                first, last = min(first, old_first), max(last, old_last)
            acquired = ([(first, last)] if not retained else [(a, b) for a, b in
                ((first, old_first-dt.timedelta(days=1)), (old_last+dt.timedelta(days=1), last)) if a <= b])
            stage = control/('stage-'+uuid.uuid4().hex)
            stage.mkdir()
            atomic_json(control/'staging-manifest.json', dict(owner='waves', output=str(output),
                exact_paths=[str(stage), str(cache)], purpose='Waves candidates and owned source objects',
                expected_source_cap_bytes=300_000_000, expected_output_bytes=1_500_000_000,
                cleanup_status='sources/candidates retained until verified final delivery'))
            files = {f: stage/f'waves-{f}.parquet' for f in ('hourly', 'daily')}
            saved = {f: pq.ParquetFile(output/retained['products'][f]['file']) for f in files} if retained else {}
            nulls = {f: dict.fromkeys(HOURLY if f == 'hourly' else DAILY, 0) for f in files}
            rows = dict.fromkeys(files, 0)
            samples = []
            native_days = {d for a, b in acquired for d in (a, b)}
            for a, b in acquired:
                if a <= dt.date(2012, 2, 29) <= b:
                    native_days.add(dt.date(2012, 2, 29))
            with ExitStack() as stack:
                writers = {f: stack.enter_context(pq.ParquetWriter(p, schema(f).with_metadata(
                    {b'waves': json.dumps(conventions(), sort_keys=True).encode()}), compression='zstd')) for f, p in files.items()}
                for i, stamp in enumerate(pd.date_range(first, last)):
                    day = stamp.date()
                    reuse = bool(retained and old_first <= day <= old_last)
                    if i % 365 == 0:
                        print(json.dumps(dict(stage='waves', day=str(day), reuse=bool(reuse))), flush=True)
                        if shutil.disk_usage(control).free < 20_000_000_000:
                            raise ValueError('Waves disk floor reached; sources preserved')
                    raw = None
                    if reuse:
                        produced = {f: q.read_row_group((day-old_first).days) for f, q in saved.items()}
                    else:
                        raw = source.day(day, points)
                        produced = tables(day, raw, points, cells)
                    for f, table in produced.items():
                        writers[f].write_table(table)
                        rows[f] += len(table)
                        for name in nulls[f]:
                            nulls[f][name] += table[name].null_count
                    if day in native_days:
                        samples.append((day, raw))
            # Compare written hourly values directly with selected native points.
            native_checks = []
            q = pq.ParquetFile(files['hourly'])
            for day, raw in samples:
                actual = q.read_row_group((day-first).days)
                expected = sanitize(raw)
                for j, point in enumerate(points):
                    column = cells.index(point['h3_index'])
                    for k, name in enumerate(HOURLY[:3]):
                        values = actual[name].to_numpy().reshape(24, len(cells))[:, column]
                        if not np.array_equal(values, expected[k][:, j], equal_nan=True):
                            raise ValueError('Waves native point replay mismatch')
                native_checks.append(dict(date=str(day), native_points=len(points), exact_parity=True))
            source_evidence = dict(metadata_sha256=source.metadata_sha256, objects=source.used,
                fields={n: source.meta[n+'/.zattrs'] for n in FIELDS})
            proof_hash = hashlib.sha256(json.dumps(source_evidence, sort_keys=True).encode()).hexdigest()
            proofs = dict(retained['source_evidence']) if retained else {}
            proofs[proof_hash] = source_evidence
            epochs = list(retained['source_epochs']) if retained else []
            epochs += [dict(start=str(a), end=str(b), evidence_sha256=proof_hash,
                           source_end=frontier.isoformat()) for a, b in acquired]
            catalog = dict(conventions(), schema_version=1, display_name='Waves',
                date_start=str(first), date_end=str(last), source_end=frontier.isoformat(),
                study=evidence, reporting_cell_count=len(cells), native_points=points,
                native_grid=grid,
                geometrically_supported_cells=len(points), source=BASE, source_evidence=proofs,
                source_epochs=sorted(epochs, key=lambda e: e['start']), native_checks=native_checks,
                code_sha256=code, run_date_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                environment={n: importlib.metadata.version(n) for n in ('numpy','pandas','pyarrow','h3','numcodecs','shapely','geopandas')},
                source_revision='ERA5 versus ERA5T and historical availability unknown',
                forecast_eligible=False, model_eligible=False,
                attribution='Contains modified Copernicus Climate Change Service information 2026; ECMWF ERA5, CC BY 4.0',
                acquisition=dict(requests=source.requests, bytes=source.bytes, peak_shared_reservation_bytes=source.peak,
                                 retained_cache_path=str(payload_cache)),
                products={f: dict(file=p.name, rows=rows[f], sha256=sha(p), bytes=p.stat().st_size,
                                 null_counts=nulls[f]) for f, p in files.items()})
            atomic_json(stage/'catalog.json', catalog)
            validation = check_waves(stage/'catalog.json', study_path=study_path)
            catalog['coverage'] = validation['coverage']
            atomic_json(stage/'catalog.json', catalog)
            output.parent.mkdir(parents=True, exist_ok=True)
            publish(stage, output, control)
            check_waves(output/'catalog.json', study_path=study_path)
            atomic_json(control/'staging-manifest.json', dict(owner='waves', output=str(output),
                products=catalog['products'], retained_source_cache=str(cache),
                cleanup_status='committed; bounded sources and any previous delivery retained; no automatic deletion'))
    return dict(catalog_path=str(output/'catalog.json'), unchanged=False)


def check_waves(catalog_path, *, study_path):
    path = Path(catalog_path)
    catalog = json.loads(path.read_text())
    study, members, evidence = study_inputs(study_path)
    cells = members[5]
    if (catalog.get('schema_version') != 1 or any(catalog.get(k) != v for k, v in conventions().items())
            or catalog['study'] != evidence or catalog['reporting_cell_count'] != len(cells)):
        raise ValueError('Waves catalog convention or study identity mismatch')
    first, last = [dt.date.fromisoformat(catalog[k]) for k in ('date_start', 'date_end')]
    if (first > last or first < dt.date.fromisoformat(study['time']['start'])
            or last >= dt.date.fromisoformat(study['time']['end_exclusive'])):
        raise ValueError('Wave catalog dates outside the study')
    axes = {}
    for name, grid in catalog['native_grid'].items():
        if (name not in ('latitude', 'longitude') or grid['spacing'] != .5
                or type(grid['count']) is not int or not 1 <= grid['count'] <= 720):
            raise ValueError('Invalid native wave grid')
        axes[name] = grid['first']+np.arange(grid['count'])*.5
        if axes[name][-1] != grid['last']:
            raise ValueError('Invalid native wave coordinate bounds')
    expected_points = spatial_support(study_path, SimpleNamespace(lat=axes['latitude'], lon=axes['longitude']), study, cells)
    if (catalog['native_points'] != expected_points
            or catalog['geometrically_supported_cells'] != len(expected_points)):
        raise ValueError('Wave native point support differs from the approved mask/grid')
    cursor = first
    for epoch in catalog['source_epochs']:
        if dt.date.fromisoformat(epoch['start']) != cursor:
            raise ValueError('Wave source epochs do not partition dates')
        if (dt.date.fromisoformat(epoch['end']) < cursor
                or pd.Timestamp(epoch['end'], tz='UTC') > pd.Timestamp(epoch['source_end'])):
            raise ValueError('Invalid wave source epoch dates')
        proof = catalog['source_evidence'][epoch['evidence_sha256']]
        if hashlib.sha256(json.dumps(proof, sort_keys=True).encode()).hexdigest() != epoch['evidence_sha256']:
            raise ValueError('Wave source evidence hash mismatch')
        cursor = dt.date.fromisoformat(epoch['end'])+dt.timedelta(days=1)
    if cursor != last+dt.timedelta(days=1):
        raise ValueError('Wave source epochs incomplete')
    sources = {}
    for f, p in catalog['products'].items():
        target = path.parent/p['file']
        if p['file'] != f'waves-{f}.parquet' or target.is_symlink() or target.stat().st_size != p['bytes'] or sha(target) != p['sha256']:
            raise ValueError('Wave product size/hash mismatch')
        q = pq.ParquetFile(target)
        if (not q.schema_arrow.equals(schema(f), check_metadata=False)
                or q.num_row_groups != (last-first).days+1
                or json.loads((q.schema_arrow.metadata or {}).get(b'waves', b'{}')) != conventions()):
            raise ValueError('Wave schema/metadata/row groups mismatch')
        sources[f] = q
    if set(sources) != {'hourly', 'daily'}:
        raise ValueError('Both wave frequencies required')
    nulls = {f: dict.fromkeys(HOURLY if f == 'hourly' else DAILY, 0) for f in sources}
    rows = dict.fromkeys(sources, 0)
    geometric = {p['h3_index'] for p in catalog['native_points']}
    covered = set()
    for i, stamp in enumerate(pd.date_range(first, last)):
        frames = {f: q.read_row_group(i) for f, q in sources.items()}
        for f, table in frames.items():
            periods = 24 if f == 'hourly' else 1
            key = 'datetime' if periods == 24 else 'date'
            stamps = (pa.array(pd.date_range(stamp.date(), periods=24, freq='h', tz='UTC').repeat(len(cells)), type=pa.timestamp('us', tz='UTC'))
                      if periods == 24 else pa.array([stamp.date()]*len(cells), type=pa.date32()))
            if not table[key].combine_chunks().equals(stamps) or not table['h3_index'].combine_chunks().equals(pa.array(cells*periods)):
                raise ValueError('Wave date/time/cell identity mismatch')
            rows[f] += len(table)
            for name in nulls[f]:
                values = table[name].to_numpy(zero_copy_only=False)
                if np.isinf(values).any() or np.isnan(values).sum() != table[name].null_count:
                    raise ValueError('Nonfinite wave values must be Arrow nulls')
                if np.isfinite(values).reshape(periods, len(cells))[:, [j for j,c in enumerate(cells) if c not in geometric]].any():
                    raise ValueError('Unsupported wave area was filled')
                nulls[f][name] += table[name].null_count
        raw = [frames['hourly'][n].to_numpy().reshape(24, len(cells)) for n in HOURLY[:3]]
        clean = sanitize(raw)
        if any(not np.array_equal(a, b, equal_nan=True) for a, b in zip(raw, clean)):
            raise ValueError('Invalid wave physical domain or calm direction')
        codes = sea_state(raw[0]).ravel()
        if not np.array_equal(codes, frames['hourly']['sea_state_code'].to_numpy(), equal_nan=True):
            raise ValueError('Wave hourly sea-state category mismatch')
        for name, expected in zip(DAILY, summarize(raw)):
            if not np.allclose(frames['daily'][name].to_numpy(), expected, rtol=1e-12, atol=1e-10, equal_nan=True):
                raise ValueError('Wave complete-day or circular reduction mismatch')
        present = np.isfinite(raw[0]).any(axis=0)
        covered.update(c for c, ok in zip(cells, present) if ok)
    for f in sources:
        if nulls[f] != catalog['products'][f]['null_counts'] or rows[f] != catalog['products'][f]['rows']:
            raise ValueError('Wave row/null accounting mismatch')
    coverage = dict(geometric_cells=len(geometric), ever_finite_height_cells=len(covered),
                    no_geometric_support_cells=len(cells)-len(geometric), never_finite_height_cells=len(cells)-len(covered))
    if 'coverage' in catalog and catalog['coverage'] != coverage:
        raise ValueError('Wave coverage summary mismatch')
    return dict(valid=True, date_start=str(first), date_end=str(last), reporting_cell_count=len(cells),
                products={f: dict(rows=rows[f], null_counts=nulls[f]) for f in sources}, coverage=coverage)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', required=True)
    parser.add_argument('--start')
    parser.add_argument('--end')
    parser.add_argument('--output')
    parser.add_argument('--cache')
    parser.add_argument('--shared-cache', action='append', default=[])
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--rebuild', action='store_true')
    parser.add_argument('--allow-partial-final-day', action='store_true')
    parser.add_argument('--check')
    args = parser.parse_args(argv)
    if args.check:
        result = check_waves(args.check, study_path=args.study)
    else:
        result = run_waves(args.study, args.start, args.end, output=args.output, cache_dir=args.cache,
            shared_caches=args.shared_cache, offline=args.offline, rebuild=args.rebuild,
            allow_partial_final_day=args.allow_partial_final_day)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
