"""Independent, checkpointed, source-qualified regional wave deliveries."""
from contextlib import ExitStack
import datetime as dt
import fcntl
import hashlib
import importlib.metadata
import platform
import json
from pathlib import Path
import shutil
import uuid

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import shapely

from .daily import sha, study_inputs, publish, recover
from .history import atomic_json
from .waves import sea_state

METHOD = 'native-water-centres-coslat-r5-regional-waves-v1'
FIELDS = ['significant_wave_height_m', 'mean_wave_period_t02_s', 'mean_wave_direction_from_deg', 'sea_state_code']
DAILY = ['significant_wave_height_mean_m', 'significant_wave_height_max_m', 'mean_wave_period_t02_mean_s',
         'mean_wave_direction_from_circular_mean_deg', 'sea_state_code_max']
COUNTS = ['geometric_native_centres', 'finite_height_centres', 'finite_period_centres', 'finite_direction_centres']


def names(provider):
    if provider not in ('salishseacast', 'usgs-nearshore'):
        raise ValueError('Unknown regional Waves provider')
    return ([n.replace('t02', 'source_tm') for n in FIELDS],
            [n.replace('t02', 'source_tm') for n in DAILY]) if provider == 'usgs-nearshore' else (FIELDS, DAILY)


def schema(provider, frequency):
    hourly, daily = names(provider)
    key = ('date', pa.date32()) if frequency == 'daily' else ('datetime', pa.timestamp('us', tz='UTC'))
    values = daily if frequency == 'daily' else COUNTS if frequency == 'support' else hourly
    return pa.schema([key, ('h3_index', pa.string()), *[(n, pa.int32() if n in COUNTS else pa.int8()
                      if 'sea_state' in n else pa.float64()) for n in values]])


def convention(provider):
    return dict(product='waves-'+provider, method=METHOD, h3_resolution=5, timezone='UTC',
        cadence_minutes=30 if provider == 'salishseacast' else 60,
        native_statistic='instantaneous source values; H3 cosine-latitude-weighted mean of valid native centres',
        direction='FROM true north; circular spatial and complete-day time mean; undefined resultant null',
        period='T02 second-frequency-moment mean' if provider == 'salishseacast' else 'source Tm mean; spectral moment unspecified, not interchangeable with T02 or ERA5 mwp',
        sea_state='height-derived WMO 3700 proxy; exact positive bounds in lower category; daily maximum',
        spatial_support='native centres strictly inside approved water and same H3; partial cell sample, no relocation/interpolation',
        missingness='unavailable archive dates and unsupported quantities/cells null; retrieval failures are pending, never fabricated gaps',
        daily_support='all scheduled native samples per UTC day per quantity required',
        model_eligible=False, forecast_eligible=False)


def mapping(study_path, lat, lon):
    study, members, evidence = study_inputs(study_path)
    frame = gpd.read_parquet((Path(study_path).resolve().parent/study['grid_registry']['mask_relative_path']).resolve())
    if frame.crs.to_epsg() != 4326:
        raise ValueError('Regional wave mask must be WGS84')
    water = frame.geometry.union_all()
    shapely.prepare(water)
    lat, lon = np.asarray(lat), np.asarray(lon)
    if lat.shape != lon.shape or not np.isfinite(lat).all() or not np.isfinite(lon).all():
        raise ValueError('Invalid native wave coordinates')
    selected = np.flatnonzero(shapely.contains_xy(water, lon.ravel(), lat.ravel()))
    cells = members[5]
    cell_ids = [h3.latlng_to_cell(float(lat.ravel()[i]), float(lon.ravel()[i]), 5) for i in selected]
    keep = np.array([c in cells for c in cell_ids], dtype=bool)
    selected = selected[keep]
    groups = np.array([cells.index(c) for c, ok in zip(cell_ids, keep) if ok], dtype=int)
    weights = np.cos(np.deg2rad(lat.ravel()[selected]))
    return cells, selected, groups, weights, evidence


def aggregate(raw, groups, weights, ncell):
    """Per-quantity native support; no source value is moved to another cell."""
    raw = np.asarray(raw, dtype=float)
    if raw.ndim != 3 or raw.shape[0] != 3 or raw.shape[2] != len(groups):
        raise ValueError('Regional wave input shape')
    h, p, d = raw.copy()
    h[~np.isfinite(h) | (h < 0)] = np.nan
    p[~np.isfinite(p) | (p <= 0)] = np.nan
    d[~np.isfinite(d) | (d < 0) | (d > 360) | (h == 0)] = np.nan
    d %= 360
    ntime = h.shape[0]
    values = np.full((3, ntime, ncell), np.nan)
    counts = np.zeros((4, ntime, ncell), dtype='i4')
    geometry = np.bincount(groups, minlength=ncell)
    counts[0] = geometry
    for t in range(ntime):
        for k, a in enumerate((h[t], p[t], d[t])):
            good = np.isfinite(a)
            counts[k+1, t] = np.bincount(groups[good], minlength=ncell)
            denominator = np.bincount(groups[good], weights=weights[good], minlength=ncell)
            if k < 2:
                numerator = np.bincount(groups[good], weights=weights[good]*a[good], minlength=ncell)
                np.divide(numerator, denominator, out=values[k, t], where=denominator > 0)
            else:
                s = np.bincount(groups[good], weights=weights[good]*np.sin(np.deg2rad(a[good])), minlength=ncell)
                c = np.bincount(groups[good], weights=weights[good]*np.cos(np.deg2rad(a[good])), minlength=ncell)
                angle = np.degrees(np.arctan2(s, c)) % 360
                angle[np.isclose(angle, 360, rtol=0, atol=1e-10)] = 0
                good_cell = (denominator > 0) & (np.hypot(s, c) > denominator*1e-12)
                values[k, t, good_cell] = angle[good_cell]
    return values, counts


def day_tables(provider, day, values, counts, cells):
    step = convention(provider)['cadence_minutes']
    n = 1440//step
    if np.shape(values) != (3, n, len(cells)) or np.shape(counts) != (4, n, len(cells)):
        raise ValueError('Regional wave scheduled sample/cell count')
    h, p, d = values
    daily = []
    for a, statistic in ((h, 'mean'), (h, 'max'), (p, 'mean')):
        good = np.isfinite(a).all(axis=0)
        finite = np.where(np.isfinite(a), a, 0 if statistic == 'mean' else -np.inf)
        daily.append(np.where(good, finite.mean(axis=0) if statistic == 'mean' else finite.max(axis=0), np.nan))
    valid = np.isfinite(d).all(axis=0)
    rad = np.deg2rad(np.where(np.isfinite(d), d, 0))
    s, c = np.sin(rad).mean(axis=0), np.cos(rad).mean(axis=0)
    angle = np.degrees(np.arctan2(s, c)) % 360
    angle[np.isclose(angle, 360, rtol=0, atol=1e-10)] = 0
    daily += [np.where(valid & (np.hypot(s, c) > 1e-12), angle, np.nan), sea_state(daily[1])]
    native_names, daily_names = names(provider)
    result = {}
    metadata = {b'waves_regional': json.dumps(convention(provider), sort_keys=True).encode()}
    for frequency, arrays, columns in [('native', [h, p, d, sea_state(h)], native_names),
                                      ('daily', daily, daily_names), ('support', counts, COUNTS)]:
        periods = 1 if frequency == 'daily' else n
        data = {'h3_index': pa.array(cells*periods)}
        if periods == 1:
            data['date'] = pa.array([day]*len(cells), type=pa.date32())
        else:
            data['datetime'] = pa.array(pd.date_range(day, periods=n, freq=f'{step}min', tz='UTC').repeat(len(cells)), type=pa.timestamp('us', tz='UTC'))
        for column, a in zip(columns, arrays):
            a = np.asarray(a).ravel()
            data[column] = pa.array(np.where(np.isfinite(a), a, 0), mask=~np.isfinite(a), type=schema(provider, frequency).field(column).type)
        result[frequency] = pa.Table.from_pydict(data, schema=schema(provider, frequency).with_metadata(metadata))
    return result


def validate_day(provider, day, tables, cells):
    n = 1440//convention(provider)['cadence_minutes']
    if set(tables) != {"native", "daily", "support"}:
        raise ValueError("Regional wave tables missing")
    for f, table in tables.items():
        if table.schema.metadata != {b"waves_regional": json.dumps(convention(provider), sort_keys=True).encode()}:
            raise ValueError("Regional wave convention metadata mismatch")
        for column in table.column_names[2:]:
            a = table[column].to_numpy()
            if np.issubdtype(a.dtype, np.floating) and np.isnan(a).sum() != table[column].null_count:
                raise ValueError("Nonfinite wave values must be Arrow nulls")
        if not table.schema.equals(schema(provider, f), check_metadata=False):
            raise ValueError('Regional wave schema mismatch')
        expected = n if f != 'daily' else 1
        if table['h3_index'].to_pylist() != cells*expected:
            raise ValueError('Regional wave cell identity mismatch')
        key = 'date' if f == 'daily' else 'datetime'
        expected_times = ([day]*len(cells) if f == 'daily' else
            pd.date_range(day, periods=n, freq=f'{convention(provider)["cadence_minutes"]}min', tz='UTC').repeat(len(cells)).to_pydatetime().tolist())
        if table[key].to_pylist() != expected_times:
            raise ValueError('Regional wave temporal identity mismatch')
    raw = np.array([tables['native'][x].to_numpy().reshape(n, len(cells)) for x in names(provider)[0][:3]])
    count = np.array([tables['support'][x].to_numpy().reshape(n, len(cells)) for x in COUNTS])
    if not np.isfinite(count).all() or (count < 0).any() or (count[1:] > count[0]).any():
        raise ValueError('Regional wave support counts invalid')
    for k in range(3):
        if (np.isfinite(raw[k]) & (count[k+1] == 0)).any():
            raise ValueError('Regional wave values outside native support')
    h, p, d = raw
    if (np.isinf(raw).any() or (h[np.isfinite(h)] < 0).any() or (p[np.isfinite(p)] <= 0).any()
            or ((d[np.isfinite(d)] < 0) | (d[np.isfinite(d)] >= 360)).any()):
        raise ValueError('Regional wave physical domain mismatch')
    recomputed = day_tables(provider, day, raw, count, cells)
    for frequency in ('native', 'daily'):
        for column in names(provider)[frequency == 'daily']:
            if not np.allclose(tables[frequency][column].to_numpy(), recomputed[frequency][column].to_numpy(), rtol=1e-12, atol=1e-9, equal_nan=True):
                raise ValueError('Regional wave sea-state/daily reduction mismatch')


def checkpoint(root, provider, day, tables, cells, source):
    root.mkdir(parents=True, exist_ok=True)
    target = root/str(day)
    if target.exists():
        raise ValueError('Refusing to overwrite regional Waves checkpoint')
    stage = root/('stage-'+uuid.uuid4().hex); stage.mkdir()
    validate_day(provider, day, tables, cells)
    files = {}
    for f, table in tables.items():
        path = stage/(f+'.parquet'); pq.write_table(table, path, compression='zstd')
        files[f] = dict(file=path.name, sha256=sha(path), bytes=path.stat().st_size, rows=len(table))
    atomic_json(stage/'receipt.json', dict(provider=provider, day=str(day), files=files, source=source))
    stage.rename(target)
    return dict(files=files, source=source)


def read_checkpoint(path, provider, day, cells):
    record = json.loads((path/'receipt.json').read_text())
    if record['provider'] != provider or record['day'] != str(day) or set(record['files']) != {'native','daily','support'}:
        raise ValueError('Regional wave checkpoint identity mismatch')
    tables = {}
    for f, entry in record['files'].items():
        p = path/entry['file']
        if p.is_symlink() or entry['file'] != f+'.parquet' or sha(p) != entry['sha256'] or p.stat().st_size != entry['bytes']:
            raise ValueError('Regional wave checkpoint hash mismatch')
        tables[f] = pq.read_table(p)
        if len(tables[f]) != entry['rows']:
            raise ValueError('Regional wave checkpoint row mismatch')
    validate_day(provider, day, tables, cells)
    return record, tables


def finalize(root, output, plan, study_path):
    provider = plan['provider']; cells = plan['cells']
    output = Path(output).resolve(); root = Path(root).resolve()
    if output.exists() and not output.is_dir():
        raise ValueError('Wave delivery must be a directory')
    expected = {'catalog.json', 'waves-native.parquet', 'waves-daily.parquet', 'waves-support.parquet'}
    if output.exists() and any(p.name not in expected or p.is_symlink() for p in output.iterdir()):
        raise ValueError('Unrelated regional wave delivery entries preserved')
    if output.exists() and (output/'catalog.json').exists():
        old = json.loads((output/'catalog.json').read_text())
        if old.get('product') != 'waves-'+provider or old.get('study') != plan['study']:
            raise ValueError('Other wave producer/study delivery preserved')
    recover(output, root)
    stage = root/('publish-'+uuid.uuid4().hex); stage.mkdir()
    products = {}; records = {}; finite_cells = set()
    counts = {f:dict.fromkeys(COUNTS if f == 'support' else names(provider)[f == 'daily'],0) for f in ('native','daily','support')}
    rows = dict.fromkeys(counts, 0)
    with ExitStack() as stack:
        writers = {f:stack.enter_context(pq.ParquetWriter(stage/f'waves-{f}.parquet', schema(provider,f).with_metadata(
            {b'waves_regional':json.dumps(convention(provider),sort_keys=True).encode()}),compression='zstd')) for f in counts}
        for stamp in pd.date_range(plan['start'],plan['end']):
            day = stamp.date(); record, tables = read_checkpoint(root/'checkpoints'/str(day),provider,day,cells)
            validate_source(plan,day,record['source'])
            records[str(day)] = record['source']
            for f,table in tables.items():
                writers[f].write_table(table);rows[f]+=len(table)
                for c in counts[f]:counts[f][c]+=table[c].null_count
            h=tables['daily'][names(provider)[1][0]].to_numpy()
            finite_cells.update(c for c,ok in zip(cells,np.isfinite(h)) if ok)
    for f in counts:
        p=stage/f'waves-{f}.parquet';products[f]=dict(file=p.name,sha256=sha(p),bytes=p.stat().st_size,rows=rows[f],null_counts=counts[f])
    catalog=dict(convention(provider),schema_version=1,study=plan['study'],date_start=plan['start'],date_end=plan['end'],
        reporting_cell_count=len(cells),cells=cells,source_plan_sha256=sha(root/'plan.json'),source_plan=plan,
        daily_sources=records,products=products,environment=environment(),complete=True,ever_complete_daily_height_cells=len(finite_cells),
        run_date_utc=dt.datetime.now(dt.timezone.utc).isoformat())
    atomic_json(stage/'catalog.json',catalog)
    check(stage/'catalog.json',study_path=study_path)
    output.parent.mkdir(parents=True,exist_ok=True);publish(stage,output,root)
    check(output/'catalog.json',study_path=study_path)
    atomic_json(root/'progress.json',dict(status='complete',catalog_path=str(output/'catalog.json'),products=products))
    return dict(catalog_path=str(output/'catalog.json'))


def check(catalog_path, *, study_path):
    path=Path(catalog_path);cat=json.loads(path.read_text());provider=cat['source_plan']['provider']
    _,members,evidence=study_inputs(study_path);cells=members[5]
    if plan_dates_invalid(cat) or cat['reporting_cell_count']!=len(cells) or cat['source_plan']['cells']!=cells or cat['source_plan']['study']!=evidence or cat['study']!=evidence or cat['cells']!=cells or any(cat.get(k)!=v for k,v in convention(provider).items()) or not cat.get('complete'):
        raise ValueError('Regional wave catalog/study/conventions mismatch')
    plan=cat['source_plan']
    if hashlib.sha256((json.dumps(plan,indent=2,sort_keys=True)+'\n').encode()).hexdigest()!=cat['source_plan_sha256']:
        raise ValueError('Regional wave source plan hash mismatch')
    if provider=='salishseacast':
        yy,xx=np.meshgrid(plan['native_grid']['latitude'],plan['native_grid']['longitude'],indexing='ij')
        _,selected,groups,weights,_=mapping(study_path,yy,xx)
        m=plan['mapping']
        if not (np.array_equal(selected,m['selected']) and np.array_equal(groups,m['groups']) and np.array_equal(weights,m['weights'])):
            raise ValueError('SSC native spatial mapping mismatch')
        geometric=np.bincount(groups,minlength=len(cells))
    else:
        geometric=np.zeros(len(cells),dtype=int)
        for qsource in plan['sources'].values():
            _,_,groups,_,_=mapping(study_path,qsource['latitude'],qsource['longitude'])
            geometric+=np.bincount(groups,minlength=len(cells))
    frequencies={'native','daily','support'}
    if set(cat['products'])!=frequencies:raise ValueError('Regional wave products missing')
    q={}
    for f,e in cat['products'].items():
        p=path.parent/e['file']
        if e['file']!=f'waves-{f}.parquet' or p.is_symlink() or sha(p)!=e['sha256'] or p.stat().st_size!=e['bytes']:
            raise ValueError('Regional wave product hash mismatch')
        q[f]=pq.ParquetFile(p)
        if q[f].num_row_groups!=(dt.date.fromisoformat(cat['date_end'])-dt.date.fromisoformat(cat['date_start'])).days+1:
            raise ValueError('Regional wave row group count mismatch')
    finite_cells=set()
    nulls={f:dict.fromkeys(COUNTS if f=='support' else names(provider)[f=='daily'],0) for f in frequencies};rows=dict.fromkeys(frequencies,0)
    for i,stamp in enumerate(pd.date_range(cat['date_start'],cat['date_end'])):
        day=stamp.date();tables={f:reader.read_row_group(i) for f,reader in q.items()};validate_day(provider,day,tables,cells)
        finite_cells.update(c for c,v in zip(cells,tables['daily'][names(provider)[1][0]].to_pylist()) if v is not None)
        source=cat['daily_sources'][str(day)]
        validate_source(plan,day,source)
        observed=tables['support'][COUNTS[0]].to_numpy().reshape(-1,len(cells))
        if not np.array_equal(observed,np.broadcast_to(geometric if source['status']=='available' else np.zeros(len(cells),dtype=int),observed.shape)):
            raise ValueError('Regional wave geometric support differs from native mapping')
        if provider=='usgs-nearshore' and not all(s.get('direction_from_evidence') for s in plan['sources'].values()):
            if tables['native'][FIELDS[2]].null_count!=len(tables['native']):
                raise ValueError('Unqualified USGS direction was populated')
        if source.get('status')=='unavailable' and any(tables['native'][c].null_count!=len(tables['native']) for c in names(provider)[0]):
            raise ValueError('Unavailable archive day was filled')
        for f,t in tables.items():
            rows[f]+=len(t)
            for c in nulls[f]:nulls[f][c]+=t[c].null_count
    if len(finite_cells)!=cat['ever_complete_daily_height_cells']:raise ValueError('Regional wave coverage count mismatch')
    for f in frequencies:
        if rows[f]!=cat['products'][f]['rows'] or nulls[f]!=cat['products'][f]['null_counts']:
            raise ValueError('Regional wave row/null accounting mismatch')
    return dict(valid=True,provider=provider,date_start=cat['date_start'],date_end=cat['date_end'],reporting_cell_count=len(cells),products={f:dict(rows=rows[f],null_counts=nulls[f]) for f in frequencies})


def plan_dates_invalid(cat):
    plan=cat['source_plan']
    return cat['date_start']!=plan['start'] or cat['date_end']!=plan['end'] or plan['start']>plan['end']


def validate_source(plan,day,source):
    if plan['provider']=='salishseacast':
        entry=plan['inventory'].get(str(day))
        if entry is None:
            if source.get('status')!='unavailable':raise ValueError('Invented SSC support outside frozen inventory')
        elif (source.get('status')!='available' or source.get('url')!=entry['url'] or source.get('bytes')!=entry['bytes']
              or not isinstance(source.get('sha256'),str) or len(source['sha256'])!=64):
            raise ValueError('SSC source receipt differs from frozen inventory')
    elif source.get('status')!='available':
        raise ValueError('Qualified USGS hours cannot be silently replaced by missing acquisition')


def environment():
    return dict(python=platform.python_version(),packages={name:importlib.metadata.version(name) for name in
        ('toolkit-oceanography','numpy','pandas','pyarrow','geopandas','shapely','h3','h5py','requests')})


def delivery_target(output,provider,evidence):
    path=Path(output)
    expected={'catalog.json','waves-native.parquet','waves-daily.parquet','waves-support.parquet'}
    if path.exists():
        if not path.is_dir() or path.is_symlink() or any(p.name not in expected or p.is_symlink() for p in path.iterdir()):
            raise ValueError('Unrelated regional wave delivery preserved')
        if (path/'catalog.json').exists():
            old=json.loads((path/'catalog.json').read_text())
            if old.get('product')!='waves-'+provider or old.get('study')!=evidence:
                raise ValueError('Other wave producer/study delivery preserved')
        elif any(path.iterdir()):raise ValueError('Unpaired regional wave delivery preserved')
