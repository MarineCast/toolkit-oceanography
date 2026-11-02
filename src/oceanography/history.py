"""Resumable Ocean Conditions history from actual native source time axes."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import datetime as dt
import fcntl
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import time

import h3
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests
import xarray as xr

from .daily import BASE, SOURCES, publish, recover, sha, study_inputs, validate_frame

CACHE_BUDGET = 15_000_000_000
RESPONSE_BUDGET = 150_000_000
NRT = {**SOURCES['chlorophyll'], 'dataset': 'erdMH1chla1day_R2022NRT', 'variable': 'chlorophyll'}


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.part')
    with temporary.open('w') as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


class HistoryCache:
    """Compressed exact response bytes, bounded streaming, checksum-verified resume."""
    def __init__(self, root, offline=False):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.offline = offline

    def fetch(self, url):
        key = hashlib.sha256(url.encode()).hexdigest()
        target = self.root / (key + '.gz')
        receipt = self.root / (key + '.json')
        if target.exists() and receipt.exists():
            meta = json.loads(receipt.read_text())
            if meta['url'] != url or sha(target) != meta['compressed_sha256']:
                raise ValueError('History cache checksum mismatch')
            return meta
        if self.offline:
            raise ValueError('Missing offline history response: ' + url)
        used = sum(p.stat().st_size for p in self.root.glob('*.gz'))
        if used > CACHE_BUDGET - RESPONSE_BUDGET:
            raise ValueError('History compressed cache budget reached')
        if shutil.disk_usage(self.root).free < 10_000_000_000:
            raise ValueError('Less than 10 GB free; refusing acquisition')
        temporary = self.root / (key + '.part')
        started = time.monotonic()
        for attempt in range(3):
            try:
                digest = hashlib.sha256()
                size = 0
                with requests.get(url, stream=True, timeout=(20, 120), headers={'Accept-Encoding': 'gzip'}) as response:
                    response.raise_for_status()
                    with temporary.open('wb') as raw:
                        with gzip.GzipFile(fileobj=raw, mode='wb', compresslevel=3, mtime=0) as compressed:
                            for block in response.iter_content(1024 * 1024):
                                size += len(block)
                                if size > RESPONSE_BUDGET:
                                    raise ValueError('Regional response exceeds 150 MB expanded budget')
                                digest.update(block)
                                compressed.write(block)
                        raw.flush()
                        os.fsync(raw.fileno())
                break
            except requests.RequestException:
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
        meta = {'url': url, 'path': str(target), 'sha256': digest.hexdigest(),
                'compressed_sha256': sha(temporary), 'bytes': size,
                'compressed_bytes': temporary.stat().st_size,
                'retrieved_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                'elapsed_seconds': time.monotonic() - started}
        os.replace(temporary, target)
        atomic_json(receipt, meta)
        return meta

    def bytes(self, receipt):
        with gzip.open(receipt['path'], 'rb') as handle:
            data = handle.read()
        if hashlib.sha256(data).hexdigest() != receipt['sha256']:
            raise ValueError('Expanded response checksum mismatch')
        return data

    @contextmanager
    def netcdf(self, receipt, scratch):
        scratch = Path(scratch)
        scratch.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(suffix='.nc', dir=scratch)
        path = Path(name)
        try:
            digest = hashlib.sha256()
            with os.fdopen(fd, 'wb') as out, gzip.open(receipt['path'], 'rb') as source:
                for block in iter(lambda: source.read(1024 * 1024), b''):
                    digest.update(block)
                    out.write(block)
            if digest.hexdigest() != receipt['sha256']:
                raise ValueError('Expanded NetCDF checksum mismatch')
            with xr.open_dataset(path) as dataset:
                yield dataset
        finally:
            # Only this invocation's newly created disposable expanded copy.
            path.unlink(missing_ok=True)


def inventory(cache, spec, start, requested_end):
    # The plan freezes these receipts. New source vintages use a new plan/cache root.
    metadata = cache.fetch(f"{BASE}/info/{spec['dataset']}/index.json")
    rows = json.loads(cache.bytes(metadata))['table']['rows']
    attrs = {(r[1], r[2]): r[4] for r in rows if r[0] == 'attribute'}
    if attrs.get((spec['variable'], 'units')) != spec['units']:
        raise ValueError('Unexpected source units')
    first = pd.Timestamp(attrs['NC_GLOBAL', 'time_coverage_start']).date()
    last = min(pd.Timestamp(attrs['NC_GLOBAL', 'time_coverage_end']).date(), requested_end)
    lo = max(start, first)
    if lo > last:
        return {'spec': spec, 'dates': [], 'metadata': metadata}
    query = f"time[({lo}T{spec['hour']:02d}:00:00Z):1:({last}T{spec['hour']:02d}:00:00Z)]"
    axis = cache.fetch(f"{BASE}/griddap/{spec['dataset']}.csv?{query}")
    frame = pd.read_csv(io.BytesIO(cache.bytes(axis)), skiprows=[1])
    times = pd.to_datetime(frame['time'], utc=True)
    if times.duplicated().any() or not times.is_monotonic_increasing:
        raise ValueError('Invalid native time axis')
    if any(t.hour != spec['hour'] or t.minute or t.second for t in times):
        raise ValueError('Unexpected native timestamp convention')
    dates = [str(t.date()) for t in times if lo <= t.date() <= last]
    if not dates or dates[-1] != str(last):
        raise ValueError('Metadata/axis endpoint mismatch')
    return {'spec': spec, 'dates': dates, 'metadata': metadata, 'time_axis': axis}


def choose_sources(inventories, start, end):
    available = {name: set(item['dates']) for name, item in inventories.items()}
    selections = {'sst': {}, 'chlorophyll': {}}
    for stamp in pd.date_range(start, end):
        day = str(stamp.date())
        selections['sst'][day] = 'sst' if day in available['sst'] else None
        selections['chlorophyll'][day] = 'sq' if day in available['sq'] else ('nrt' if day in available['nrt'] else None)
    return selections


def chunk_url(spec, dates, bbox):
    west, south, east, north = bbox
    latitude = f'[({south}):1:({north})]' if spec['ascending'] else f'[({north}):1:({south})]'
    subset = f"[({dates[0]}T{spec['hour']:02d}:00:00Z):1:({dates[-1]}T{spec['hour']:02d}:00:00Z)]" + latitude + f'[({west}):1:({east})]'
    variables = [spec['variable']] + (['mask'] if spec['metric'] == 'sst_c' else [])
    return f"{BASE}/griddap/{spec['dataset']}.nc?" + ','.join(v + subset for v in variables)


def plan_history(study_path, cache, start, end):
    study, members, evidence = study_inputs(study_path)
    start = max(dt.date.fromisoformat(start), dt.date.fromisoformat(study['time']['start']))
    end = min(dt.date.fromisoformat(end), dt.date.fromisoformat(study['time']['end_exclusive']) - dt.timedelta(days=1))
    if start > end:
        raise ValueError('Invalid study date interval')
    inventories = {key: inventory(cache, spec, start, end) for key, spec in [('sst', SOURCES['sst']), ('sq', SOURCES['chlorophyll']), ('nrt', NRT)]}
    # Each product ends on its own actual final source date, never a requested future day.
    endings = {'sst': max(inventories['sst']['dates']), 'chlorophyll': max(inventories['sq']['dates'] + inventories['nrt']['dates'])}
    selections = choose_sources(inventories, start, max(endings.values()))
    for product in selections:
        selections[product] = {day: source for day, source in selections[product].items() if day <= endings[product]}
    jobs = []
    for product, selected in selections.items():
        for month in sorted({day[:7] for day in selected}):
            for source in sorted({v for k, v in selected.items() if k.startswith(month) and v is not None}):
                dates = [day for day, value in selected.items() if day.startswith(month) and value == source]
                spec = inventories[source]['spec']
                # Remote inclusive ranges may also contain dates assigned to higher-quality SQ.
                expected = [day for day in inventories[source]['dates'] if dates[0] <= day <= dates[-1]]
                jobs.append({'id': f'{product}-{source}-{month}', 'product': product, 'source': source, 'dates': dates, 'expected_dates': expected, 'url': chunk_url(spec, dates, study['domain']['bbox_wgs84'])})
    return {'schema_version': 1, 'study': evidence, 'study_id': study['study_id'], 'study_revision': study['domain']['revision'], 'bbox': study['domain']['bbox_wgs84'], 'start': str(start), 'endings': endings, 'inventories': inventories, 'selections': selections, 'jobs': jobs, 'members': members, 'code_sha256': sha(__file__), 'method_version': 'pixel-centre-cos-lat-v1'}


class GridAggregator:
    def __init__(self, spec, members, bbox):
        self.spec = spec
        self.members = members
        self.bbox = bbox
        self.lat = None
        self.lon = None

    def prepare(self, ds):
        spec = self.spec
        if ds[spec['variable']].dims != ('time', 'latitude', 'longitude') or ds[spec['variable']].attrs.get('units') != spec['units']:
            raise ValueError('Native dimensions/units mismatch')
        lat, lon = ds.latitude.values, ds.longitude.values
        if self.lat is not None:
            if not np.array_equal(lat, self.lat) or not np.array_equal(lon, self.lon):
                raise ValueError('Native spatial grid changed')
            return
        sign = 1 if spec['ascending'] else -1
        if not np.all(np.diff(lat) * sign > 0) or not np.all(np.diff(lon) > 0):
            raise ValueError('Native coordinates are not monotonic')
        if not np.allclose(np.abs(np.diff(lat)), spec['spacing'], atol=2e-5) or not np.allclose(np.diff(lon), spec['spacing'], atol=2e-5):
            raise ValueError('Native spacing mismatch')
        west, south, east, north = self.bbox
        tolerance = spec['spacing'] * 1.1
        if max(abs(float(min(lat))-south), abs(float(max(lat))-north), abs(float(lon[0])-west), abs(float(lon[-1])-east)) > tolerance:
            raise ValueError('Native bounds mismatch')
        self.lat, self.lon = lat.copy(), lon.copy()
        member_set = set(self.members)
        ys, xs, ids = [], [], []
        for y, a in enumerate(lat):
            for x, b in enumerate(lon):
                cell = h3.latlng_to_cell(float(a), float(b), spec['resolution'])
                if cell in member_set:
                    ys.append(y); xs.append(x); ids.append(cell)
        self.ys, self.xs = np.asarray(ys), np.asarray(xs)
        self.ids = np.asarray(ids)
        self.weights = np.cos(np.deg2rad(lat[self.ys]))

    def day(self, ds, index, day):
        self.prepare(ds)
        spec = self.spec
        values = ds[spec['variable']].isel(time=index).values.astype(float)[self.ys, self.xs]
        good = np.isfinite(values)
        if spec['metric'] == 'sst_c':
            mask = ds['mask'].isel(time=index).values[self.ys, self.xs]
            integer = np.nan_to_num(mask).astype(int)
            good &= np.isfinite(mask) & ((integer & 1) != 0) & ((integer & 2) == 0) & (values >= -3) & (values <= 45)
        else:
            good &= values > 0
        # Same pandas weighted summation as the accepted pilot preserves its values.
        samples = pd.DataFrame({'h3_index': self.ids[good], 'weighted': values[good] * self.weights[good], 'weight': self.weights[good]})
        grouped = samples.groupby('h3_index')[['weighted', 'weight']].sum()
        means = grouped.weighted / grouped.weight
        frame = pd.DataFrame({'date': [dt.date.fromisoformat(day)] * len(self.members), 'h3_index': self.members})
        frame[spec['metric']] = frame.h3_index.map(means).astype(float)
        return frame


def checkpoint_path(root, job):
    return Path(root) / (job['id'] + '.parquet')


def valid_checkpoint(root, job, binding):
    path = checkpoint_path(root, job)
    receipt = path.with_suffix('.json')
    if not path.exists() or not receipt.exists():
        return False
    meta = json.loads(receipt.read_text())
    if meta['binding'] != binding or meta['sha256'] != sha(path):
        raise ValueError('Checkpoint integrity or plan binding mismatch: ' + job['id'])
    return True


def write_checkpoint(root, job, frame, binding, source_receipt):
    target = checkpoint_path(root, job)
    temporary = target.with_suffix('.part')
    pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), temporary, compression='zstd')
    os.replace(temporary, target)
    atomic_json(target.with_suffix('.json'), {'binding': binding, 'sha256': sha(target), 'source': source_receipt, 'dates': job['dates'], 'rows': len(frame)})


def validate_native_dates(ds, spec, expected):
    times = pd.DatetimeIndex(ds.time.values)
    actual = [str(t.date()) for t in times]
    if actual != expected or any(t.hour != spec['hour'] or t.minute or t.second for t in times):
        raise ValueError('Native returned dates differ from planned actual time axis')
    return actual


def assemble(plan, checkpoint_root, output, work, binding):
    import uuid
    stage = work / ('stage-history-' + uuid.uuid4().hex)
    stage.mkdir()
    catalog = {'schema_version': 1, 'domain': 'oceanography', 'study_id': plan['study_id'], 'study_revision': plan['study_revision'], 'date_start': plan['start'], 'date_end': max(plan['endings'].values()), 'study': plan['study'], 'history_plan_sha256': binding, 'history_plan_path': str((checkpoint_root.parent / 'plan.json').resolve()), 'code_sha256': sha(__file__), 'method': 'Cos(latitude)-weighted valid native pixel centres assigned to approved water-reporting H3 cells. No toolkit spatial/temporal gap filling. MUR is provider gap-filled analysis.', 'date_basis': 'Native daily UTC date labels; MUR 09:00 UTC, MODIS 12:00 UTC.', 'source_precedence': 'MODIS R2022 science-quality (SQ) wherever that date exists on its native axis; NRT only where SQ has no date and NRT has one; otherwise null with native_source_date_absent recorded internally.', 'products': []}
    summaries = {}
    for product in ['sst', 'chlorophyll']:
        spec = SOURCES[product]
        cells = plan['members'][str(spec['resolution'])] if str(spec['resolution']) in plan['members'] else plan['members'][spec['resolution']]
        filename = f'{product}-r{spec["resolution"]}-daily.parquet'
        schema = pa.schema([('date', pa.date32()), ('h3_index', pa.string()), (spec['metric'], pa.float64())])
        nonnull = rows = 0
        low, high = float('inf'), -float('inf')
        sources = {'sst': 0, 'sq': 0, 'nrt': 0, 'native_source_date_absent': 0}
        pilot = output / filename if (output / filename).exists() else None
        pilot_matches = 0
        with pq.ParquetWriter(stage / filename, schema, compression='zstd') as writer:
            for month in sorted({day[:7] for day in plan['selections'][product]}):
                jobs = [j for j in plan['jobs'] if j['product'] == product and j['id'].endswith(month)]
                frames = []
                for job in jobs:
                    if not valid_checkpoint(checkpoint_root, job, binding):
                        raise ValueError('Missing history checkpoint')
                    frame = pq.read_table(checkpoint_path(checkpoint_root, job)).to_pandas()
                    validate_frame(frame, spec, [dt.date.fromisoformat(d) for d in job['dates']], cells)
                    frames.append(frame)
                missing = [day for day, source in plan['selections'][product].items() if day.startswith(month) and source is None]
                for day in missing:
                    frames.append(pd.DataFrame({'date': [dt.date.fromisoformat(day)] * len(cells), 'h3_index': cells, spec['metric']: np.nan}))
                frame = pd.concat(frames, ignore_index=True).sort_values(['date', 'h3_index']).reset_index(drop=True)
                dates = [dt.date.fromisoformat(day) for day in plan['selections'][product] if day.startswith(month)]
                validate_frame(frame, spec, dates, cells)
                if pilot is not None:
                    old = pq.read_table(pilot, filters=[('date', '>=', dates[0]), ('date', '<=', dates[-1])]).to_pandas().sort_values(['date', 'h3_index']).reset_index(drop=True)
                    if len(old):
                        new = frame[frame.date.isin(old.date.unique())].reset_index(drop=True)
                        pd.testing.assert_frame_equal(old, new, check_exact=True)
                        pilot_matches += len(old)
                for day, source in plan['selections'][product].items():
                    if day.startswith(month): sources[source or 'native_source_date_absent'] += 1
                values = frame[spec['metric']].dropna()
                if len(values): low, high = min(low, float(values.min())), max(high, float(values.max()))
                rows += len(frame); nonnull += len(values)
                writer.write_table(pa.Table.from_pandas(frame, schema=schema, preserve_index=False))
        # Stream full final readback; never materialize all history.
        position = 0
        dates = [dt.date.fromisoformat(day) for day in plan['selections'][product]]
        for batch in pq.ParquetFile(stage / filename).iter_batches(batch_size=len(cells)):
            frame = batch.to_pandas()
            validate_frame(frame, spec, [dates[position]], cells)
            position += 1
        if position != len(dates): raise ValueError('Final date count mismatch')
        description = spec['description']
        if product == 'chlorophyll': description += ' Science-quality dates take precedence; recent/gap dates may use provisional NRT, as recorded in the external history plan.'
        entry = {'id': product, 'path': filename, 'sha256': sha(stage / filename), 'columns': schema.names, 'metric': spec['metric'], 'units': spec['units'], 'h3_resolution': spec['resolution'], 'row_count': rows, 'date_start': plan['start'], 'date_end': plan['endings'][product], 'source_dataset': spec['dataset'], 'source_datasets': [spec['dataset']] + ([NRT['dataset']] if product == 'chlorophyll' else []), 'source_url': f'{BASE}/griddap/{spec["dataset"]}.html', 'description': description, 'native_spacing_degrees': spec['spacing'], 'nonnull': nonnull, 'null': rows - nonnull, 'minimum': low if nonnull else None, 'maximum': high if nonnull else None, 'source_day_counts': sources, 'previous_rows_verified_exact': pilot_matches}
        catalog['products'].append(entry)
        summaries[product] = entry
    atomic_json(stage / 'catalog.json', catalog)
    publish(stage, output, work)
    return summaries


def run(study, output, root, start, end, preflight=False, offline=False, limit=None, publish_ready=False):
    root = Path(root).resolve(); root.mkdir(parents=True, exist_ok=True)
    cache = HistoryCache(root / 'responses', offline)
    with (root / 'history.lock').open('a') as history_lock:
        fcntl.flock(history_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan_path = root / 'plan.json'
        if plan_path.exists():
            plan = json.loads(plan_path.read_text())
            _, _, current_evidence = study_inputs(study)
            if plan['study'] != current_evidence or plan['code_sha256'] != sha(__file__):
                raise ValueError('Frozen plan no longer matches study/code; explicit new run root required')
        else:
            plan = plan_history(study, cache, start, end)
            atomic_json(plan_path, plan)
        binding = sha(plan_path)
        summary = {'start': plan['start'], 'endings': plan['endings'], 'jobs': len(plan['jobs']), 'source_days': {p: {str(s): list(v.values()).count(s) for s in set(v.values())} for p, v in plan['selections'].items()}, 'retained_budget_bytes': CACHE_BUDGET, 'expanded_response_budget_bytes': RESPONSE_BUDGET, 'workers': 2}
        print(json.dumps(summary), flush=True)
        if preflight: return summary
        checkpoint_root = root / 'checkpoints'; checkpoint_root.mkdir(exist_ok=True)
        aggregators = {name: GridAggregator(item['spec'], plan['members'].get(str(item['spec']['resolution']), plan['members'].get(item['spec']['resolution'])), plan['bbox']) for name, item in plan['inventories'].items()}
        pending = [job for job in plan['jobs'] if not valid_checkpoint(checkpoint_root, job, binding)]
        if limit: pending = pending[:limit]
        # Only two requests in flight; completed compressed payloads are small and durable.
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {}
            cursor = 0
            for _ in range(min(2, len(pending))):
                futures[cursor] = executor.submit(cache.fetch, pending[cursor]['url']); cursor += 1
            for number, job in enumerate(pending):
                receipt = futures.pop(number).result()
                if cursor < len(pending):
                    futures[cursor] = executor.submit(cache.fetch, pending[cursor]['url']); cursor += 1
                frames = []
                spec = plan['inventories'][job['source']]['spec']
                with cache.netcdf(receipt, root / 'scratch') as dataset:
                    actual = validate_native_dates(dataset, spec, job['expected_dates'])
                    for day in job['dates']:
                        frames.append(aggregators[job['source']].day(dataset, actual.index(day), day))
                frame = pd.concat(frames, ignore_index=True)
                cells = aggregators[job['source']].members
                validate_frame(frame, spec, [dt.date.fromisoformat(day) for day in job['dates']], cells)
                write_checkpoint(checkpoint_root, job, frame, binding, receipt)
                progress = {'completed_this_run': number + 1, 'pending_this_run': len(pending), 'job': job['id'], 'rows': len(frame), 'nonnull': int(frame[spec['metric']].notna().sum()), 'compressed_bytes': receipt['compressed_bytes'], 'request_seconds': receipt['elapsed_seconds']}
                atomic_json(root / 'progress.json', progress)
                print(json.dumps(progress), flush=True)
        remaining = [j['id'] for j in plan['jobs'] if not valid_checkpoint(checkpoint_root, j, binding)]
        if remaining: return {'remaining_jobs': len(remaining), 'published': False}
        if not publish_ready: return {'remaining_jobs': 0, 'published': False, 'ready_for_validation_and_promotion': True}
        output = Path(output).resolve()
        work = output.parent.parent / '.marinecast-work' / 'oceanography'; work.mkdir(parents=True, exist_ok=True)
        with (work / 'publication.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            recover(output, work)
            summary = assemble(plan, checkpoint_root, output, work, binding)
        atomic_json(root / 'completed.json', summary)
        return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['study', 'output', 'root', 'start', 'end']: parser.add_argument('--' + name, required=True)
    parser.add_argument('--preflight', action='store_true')
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--limit-jobs', type=int)
    parser.add_argument('--publish', action='store_true', help='Promote complete validated history after consumer readiness')
    args = parser.parse_args()
    print(json.dumps(run(args.study, args.output, args.root, args.start, args.end, args.preflight, args.offline, args.limit_jobs, args.publish), indent=2))

if __name__ == '__main__':
    main()
