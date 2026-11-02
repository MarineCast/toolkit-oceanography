"""Bounded official ERA5 wave chunks; native coordinates and nulls stay explicit."""
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import threading

import numpy as np
import pandas as pd
import requests
import yaml

from .daily import sha
from .history import atomic_json

BASE = ('https://arco.datastores.ecmwf.int/cadl-arco-geo-003/arco/'
        'reanalysis_era5_single_levels/wav/geoChunked.zarr')
FIELDS = {'swh': (140229, 'm'), 'mwp': (140232, 's'), 'mwd': (140230, 'Degree true')}
MAX_OBJECT = 8 * 1024**2


def fetch(name):
    """Credentials only to the fixed official origin; no proxies or redirects."""
    rc = Path(os.environ.get('CDSAPI_RC', str(Path.home()/'.cdsapirc'))).expanduser()
    key = os.environ.get('CDSAPI_KEY')
    if not key and rc.is_file():
        value = yaml.safe_load(rc.read_text())
        key = value.get('key') if isinstance(value, dict) else None
    if not isinstance(key, str) or not key.strip():
        raise ValueError('Configure CDSAPI_KEY or CDSAPI_RC for official ERA5 wave access')
    try:
        with requests.Session() as session:
            session.trust_env = False
            with session.get(BASE+'/'+name, headers={'Authorization': 'Bearer '+key.strip()},
                             timeout=(15, 60), allow_redirects=False, stream=True) as response:
                if response.status_code != 200:
                    raise ValueError('Source status')
                chunks, count = [], 0
                for block in response.iter_content(256*1024):
                    count += len(block)
                    if count > MAX_OBJECT:
                        raise ValueError('Object limit')
                    chunks.append(block)
                return b''.join(chunks)
    except Exception:
        raise RuntimeError('Official ECMWF wave retrieval failed; credentials/response redacted') from None


class Source:
    """Two requests at most, <300 MB owned raw cache and shared 2 GB accounting.

    Decoded native time blocks live in memory, never as a second on-disk archive.
    Registered other caches are read only; a 900 MB reservation leaves room for
    the existing regional runner's two bounded requests if it is resumed.
    """
    def __init__(self, root, *, offline=False, shared=(), fetcher=None, budget_root=None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.budget_root = Path(budget_root).resolve() if budget_root else self.root
        if self.budget_root != self.root and self.budget_root not in self.root.parents:
            raise ValueError('Wave budget root must contain the source snapshot')
        self.offline, self.fetcher = offline, fetcher or fetch
        self.shared = sorted(set(Path(p).resolve() for p in shared))
        if any(p == self.budget_root or p in self.budget_root.parents or self.budget_root in p.parents for p in self.shared):
            raise ValueError('Overlapping wave/shared source cache roots')
        self.lock = threading.RLock()
        self.reserved = self.requests = self.bytes = self.peak = 0
        self.used, self.loaded = {}, None
        raw = self.object('.zmetadata')
        self.metadata_sha256 = hashlib.sha256(raw).hexdigest()
        self.meta = json.loads(raw)['metadata']
        for name, (pid, units) in FIELDS.items():
            a, attrs = self.meta[name+'/.zarray'], self.meta[name+'/.zattrs']
            if (a['chunks'] != [135168, 2, 4] or a['dtype'] != '<f4'
                    or attrs.get('units') != units or attrs.get('GRIB_paramId') != pid
                    or attrs.get('GRIB_stepType') != 'instant'
                    or attrs.get('_ARRAY_DIMENSIONS') != ['time', 'latitude', 'longitude']):
                raise ValueError('Wave field identity/layout/units/instantaneous support changed: '+name)
        self.times, self.lat, self.lon = [self.coordinate(n) for n in ('time', 'latitude', 'longitude')]
        if (self.meta['time/.zattrs'].get('units') != 'seconds since 1970-01-01'
                or self.meta['time/.zattrs'].get('calendar') != 'proleptic_gregorian'
                or not np.all(np.diff(self.times) == 3600)
                or not np.allclose(np.diff(self.lat), .5, rtol=0, atol=1e-10)
                or not np.allclose(np.diff(self.lon), .5, rtol=0, atol=1e-10)
                or self.lat[0] != -90 or self.lon[0] != -180):
            raise ValueError('Wave source coordinate convention changed')
        for name in FIELDS:
            if self.meta[name+'/.zarray']['shape'] != [len(self.times), len(self.lat), len(self.lon)]:
                raise ValueError('Wave field shape differs from actual coordinate axes')

    def _budget(self, extra):
        own = sum(p.stat().st_size for p in self.budget_root.rglob('*') if p.is_file())
        other = sum(p.stat().st_size for root in self.shared if root.exists()
                    for p in root.rglob('*') if p.is_file())
        reserve_other = 900_000_000 if self.shared else 0
        if (own+self.reserved+extra > 300_000_000
                or own+other+self.reserved+extra+reserve_other > 2_000_000_000):
            raise ValueError('Wave/shared source cache budget exceeded; sources preserved')
        if shutil.disk_usage(self.root).free < 20_000_000_000+extra:
            raise ValueError('Wave source stopped at 20 GB free-space floor')
        self.peak = max(self.peak, own+other+self.reserved+extra+reserve_other)

    def object(self, name):
        path = self.root/name
        receipt = path.with_name(path.name+'.receipt.json')
        if path.exists() != receipt.exists():
            raise ValueError('Incomplete wave source cache object; preserved')
        if path.exists() and receipt.exists():
            record = json.loads(receipt.read_text())
            if (path.is_symlink() or path.stat().st_size > MAX_OBJECT
                    or record['source'] != BASE+'/'+name or record['sha256'] != sha(path)
                    or record['bytes'] != path.stat().st_size):
                raise ValueError('Corrupt wave source cache object')
            raw = path.read_bytes()
        else:
            if self.offline:
                raise ValueError('Missing offline wave source object: '+name)
            with self.lock:
                self._budget(MAX_OBJECT)
                self.reserved += MAX_OBJECT
                self.requests += 1
            try:
                raw = self.fetcher(name)
                if len(raw) > MAX_OBJECT:
                    raise ValueError('Wave source object exceeds bound')
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_name(path.name+'.part')
                with temporary.open('wb') as handle:
                    handle.write(raw)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, path)
                record = dict(source=BASE+'/'+name, bytes=len(raw), sha256=sha(path),
                              retrieved_at_utc=dt.datetime.now(dt.timezone.utc).isoformat())
                atomic_json(receipt, record)
                with self.lock:
                    self.bytes += len(raw)
            finally:
                with self.lock:
                    self.reserved -= MAX_OBJECT
        with self.lock:
            self.used[name] = record
        return raw

    def decode(self, name):
        import numcodecs
        spec = self.meta[name.split('/')[0]+'/.zarray']
        if (spec['zarr_format'] != 2 or spec['order'] != 'C' or spec.get('filters')
                or np.prod(spec['chunks'])*np.dtype(spec['dtype']).itemsize > MAX_OBJECT):
            raise ValueError('Unsupported wave Zarr encoding or decoded size')
        blob = numcodecs.get_codec(spec['compressor']).decode(self.object(name))
        if len(blob) != int(np.prod(spec['chunks']))*np.dtype(spec['dtype']).itemsize:
            raise ValueError('Wave decoded chunk size mismatch')
        return np.frombuffer(blob, dtype=spec['dtype']).reshape(spec['chunks'])

    def coordinate(self, name):
        spec = self.meta[name+'/.zarray']
        if (len(spec['shape']) != 1 or len(spec['chunks']) != 1 or spec['shape'][0] > 2_000_000
                or spec['chunks'][0] <= 0 or spec['dtype'] not in ('<i8', '<f8')):
            raise ValueError('Unsupported wave coordinate layout')
        return np.concatenate([self.decode(name+'/'+str(i)) for i in
            range((spec['shape'][0]+spec['chunks'][0]-1)//spec['chunks'][0])])[:spec['shape'][0]]

    def block(self, index, points):
        key = (index, tuple((p['y'], p['x']) for p in points))
        if self.loaded is not None and self.loaded[0] == key:
            return self.loaded[1]
        count = min(135168, len(self.times)-index*135168)
        output = np.full((3, count, len(points)), np.nan, dtype='<f4')
        tasks = [(fi, name, y, x) for fi, name in enumerate(FIELDS)
                 for y, x in sorted({(p['y']//2, p['x']//4) for p in points})]
        def read(task):
            fi, name, y, x = task
            values = self.decode(f'{name}/{index}.{y}.{x}')[:count]
            selected = [i for i, p in enumerate(points) if p['y']//2 == y and p['x']//4 == x]
            for i in selected:
                p = points[i]
                output[fi, :, i] = values[:, p['y'] % 2, p['x'] % 4]
            sentinel = self.meta[name+'/.zattrs'].get('GRIB_missingValue')
            if sentinel is not None:
                part = output[fi, :, selected]
                output[fi, :, selected] = np.where(part == np.float32(sentinel), np.nan, part)
        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(read, tasks))
        self.loaded = (key, output)
        return output

    def day(self, day, points):
        seconds = pd.date_range(day, periods=24, freq='h', tz='UTC').as_unit('s').asi8
        positions = np.searchsorted(self.times, seconds)
        valid = positions < len(self.times)
        if not np.array_equal(self.times[positions[valid]], seconds[valid]):
            raise ValueError('Wave date not present on source time coordinates')
        values = np.full((3, 24, len(points)), np.nan)
        for index in sorted(set((positions[valid]//135168).tolist())):
            chosen = np.flatnonzero(valid & (positions//135168 == index))
            values[:, chosen] = self.block(index, points)[:, positions[chosen] % 135168]
        return values
