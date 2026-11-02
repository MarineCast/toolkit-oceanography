"""Bounded, lossless ERDDAP surface subsets for the regional history runner."""
from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import struct
import threading
import time
import zlib

import numpy as np
import pandas as pd
import requests

from .daily import sha
from .regional import SPECS
from .regional_history import DATASETS

BASE = 'https://salishsea.eos.ubc.ca/erddap'
RESPONSE_CAP = 450_000_000


class InsufficientSourceCoverage(ValueError):
    """An optional retained subset cannot cover the current native rectangle."""


def source_bytes(directory):
    total = 0
    for path in Path(directory).glob('*.gz'):
        try:
            total += path.stat().st_size
        except FileNotFoundError:  # another request discarded its failed partial
            pass
    return total


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.part')
    with temporary.open('w') as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def nc_header(blob):
    """Read fixed-variable NetCDF3 headers without materializing data arrays."""
    stream = io.BytesIO(blob)
    magic = stream.read(4)
    if magic not in (b'CDF\x01', b'CDF\x02'):
        raise ValueError('Require fixed-variable NetCDF3 response')
    def uint():
        return struct.unpack('>I', stream.read(4))[0]
    def name():
        length = uint()
        value = stream.read(length)
        stream.read((-length) % 4)
        return value.decode()
    types = {1: (1, 'i1'), 2: (1, 'S1'), 3: (2, '>i2'), 4: (4, '>i4'), 5: (4, '>f4'), 6: (8, '>f8')}
    def attrs():
        tag, count = uint(), uint()
        if tag != 12 and (tag, count) != (0, 0):
            raise ValueError('Invalid NetCDF attributes')
        result = {}
        for _ in range(count):
            key, typ, length = name(), uint(), uint()
            size = length * types[typ][0]
            value = stream.read(size)
            stream.read((-size) % 4)
            result[key] = value.decode(errors='replace') if typ == 2 else np.frombuffer(value, dtype=types[typ][1]).tolist()
        return result
    records, tag, count = uint(), uint(), uint()
    if records or tag != 10:
        raise ValueError('Unsupported record-variable NetCDF')
    dimensions = [(name(), uint()) for _ in range(count)]
    global_attrs = attrs()
    tag, count = uint(), uint()
    if tag != 11:
        raise ValueError('Missing NetCDF variables')
    variables = {}
    for _ in range(count):
        key = name()
        dims = [uint() for _ in range(uint())]
        attributes, typ, size = attrs(), uint(), uint()
        offset = struct.unpack('>Q' if magic[-1] == 2 else '>I', stream.read(8 if magic[-1] == 2 else 4))[0]
        variables[key] = dict(dimensions=[dimensions[i][0] for i in dims], shape=[dimensions[i][1] for i in dims],
                              attributes=attributes, dtype=types[typ][1], itemsize=types[typ][0], begin=offset, vsize=size)
    return dict(dimensions=dict(dimensions), variables=variables, global_attributes=global_attrs)


def inspect_source(path, kind, start, end, required):
    """Validate time/depth/indices and permit retained inputs wider than target."""
    with gzip.open(path, 'rb') as handle:
        prefix = handle.read(262144)
    header = nc_header(prefix)
    def axis(name):
        v = header['variables'][name]
        n = int(np.prod(v['shape']))
        return np.frombuffer(prefix[v['begin']:v['begin'] + n*v['itemsize']], dtype=v['dtype'])
    expected = pd.date_range(str(start)+'T00:30:00Z', str(end)+'T23:30:00Z', freq='h')
    time_attributes=header['variables']['time']['attributes']
    if time_attributes.get('units') != 'seconds since 1970-01-01T00:00:00Z' or time_attributes.get('calendar','standard') not in ('standard','gregorian','proleptic_gregorian'):
        raise ValueError('Regional time origin/calendar mismatch')
    if not np.array_equal(axis('time'), expected.as_unit('s').asi8):
        raise ValueError('Incomplete or shifted hourly UTC intervals')
    depth = header['variables']['depth']['attributes']
    if depth.get('units') != 'm' or depth.get('positive') != 'down' or len(axis('depth')) != 1 or abs(float(axis('depth')[0])-.5000003) > 1e-6:
        raise ValueError('Regional surface depth mismatch')
    y, x = axis('gridY'), axis('gridX')
    if not len(y) or not len(x) or not np.array_equal(y, np.arange(y[0], y[-1]+1)) or not np.array_equal(x, np.arange(x[0], x[-1]+1)):
        raise ValueError('Regional grid indices must be contiguous')
    a, b, c, d = required
    if not (0 <= y[0] <= a <= b <= y[-1] < 898 and 0 <= x[0] <= c <= d <= x[-1] < 398):
        raise InsufficientSourceCoverage('Source does not contain required staggered faces')
    var, units, standard = SPECS[kind]
    field = header['variables'][var]
    if field['dimensions'] != ['time','depth','gridY','gridX'] or field['shape'] != [len(expected),1,len(y),len(x)] or field['dtype'] != '>f4':
        raise ValueError('Regional variable layout mismatch')
    if field['attributes'].get('units') != units or field['attributes'].get('standard_name') != standard:
        raise ValueError('Regional variable units/convention mismatch')
    return header, [int(y[0]),int(y[-1]),int(x[0]),int(x[-1])]


class Transport:
    """Only this run's registered sources may be evicted; external seeds stay put."""
    def __init__(self, root, seeds=(), offline=False, cap=2_000_000_000, floor=20_000_000_000,
                 requests_in_flight=1):
        if requests_in_flight not in (1, 2):
            raise ValueError('Require one or two in-flight requests')
        self.root = Path(root).resolve()
        self.sources = self.root/'sources'
        self.receipts = self.root/'receipts'
        for directory in (self.sources, self.receipts):
            directory.mkdir(parents=True, exist_ok=True)
            if directory.is_symlink():
                raise ValueError('Symlink cache directories are not allowed')
        self.cap, self.floor, self.offline = cap, floor, offline
        self.seeds = [Path(p).resolve() for p in seeds]
        self.requests_in_flight = requests_in_flight
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._reserved = {}
        self._futures = {}
        self._active = {}
        self._peak_bytes = source_bytes(self.sources)
        self._peak_requests = 0
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='regional-source') if requests_in_flight == 2 else None

    def __enter__(self):
        return self

    def __exit__(self, *exception):
        self._stop.set()
        if self._pool is not None:
            # Active HTTP reads retain the existing bounded timeout. Do not let a
            # background request mutate receipts after the run lock is released.
            self._pool.shutdown(wait=True, cancel_futures=True)
        self._save_state()

    def state(self):
        with self._lock:
            return dict(request_limit=self.requests_in_flight, active_requests=list(self._active.values()),
                        active_request_count=len(self._active), peak_request_count=self._peak_requests,
                        reserved_remaining_bytes=sum(self._reserved.values()), source_cache_bytes=source_bytes(self.sources),
                        peak_source_cache_bytes=self._peak_bytes, cache_cap_bytes=self.cap)

    def _save_state(self):
        atomic_json(self.root/'transport-state.json', self.state())

    def _reserve(self, key, url):
        with self._lock:
            if self._stop.is_set():
                raise RuntimeError('Source acquisition cancelled')
            self.budget(RESPONSE_CAP)
            self._reserved[key] = RESPONSE_CAP
            self._active[key] = dict(url=url, started_at_utc=dt.datetime.now(dt.timezone.utc).isoformat())
            self._peak_requests = max(self._peak_requests, len(self._active))
            self._save_state()

    def _release(self, key):
        with self._lock:
            self._reserved.pop(key, None)
            self._active.pop(key, None)
            self._save_state()

    def _write(self, handle, block, key):
        with self._lock:
            if self._stop.is_set():
                raise RuntimeError('Source acquisition cancelled')
            if len(block) > self._reserved[key]:
                raise ValueError('Response byte cap exceeded')
            self.budget()
            if shutil.disk_usage(self.root).free < self.floor + len(block):
                raise ValueError('Free-disk floor reached')
            handle.write(block)  # unbuffered: stat and reservation remain consistent
            self._reserved[key] -= len(block)
            self._peak_bytes = max(self._peak_bytes, source_bytes(self.sources))

    def prefetch(self, kind, start, end, rectangle):
        if self._pool is None:
            return
        key = (kind, str(start), str(end), tuple(rectangle))
        with self._lock:
            if key not in self._futures:
                if self._stop.is_set():
                    raise RuntimeError('Source acquisition cancelled')
                self._futures[key] = self._pool.submit(self._acquire, kind, start, end, rectangle)

    def acquire(self, kind, start, end, rectangle):
        if self._pool is None:
            return self._acquire(kind, start, end, rectangle)
        self.prefetch(kind, start, end, rectangle)
        key = (kind, str(start), str(end), tuple(rectangle))
        with self._lock:
            future = self._futures[key]
        try:
            return future.result()
        finally:
            with self._lock:
                self._futures.pop(key, None)

    def budget(self, extra=0):
        with self._lock:
            used = source_bytes(self.sources)
            if used+sum(self._reserved.values())+extra > self.cap or shutil.disk_usage(self.root).free < self.floor+sum(self._reserved.values())+extra:
                raise ValueError('Source-cache cap or free-disk floor reached')

    def evict(self, path, proof):
        with self._lock:
            return self._evict(path, proof)

    def _evict(self, path, proof):
        path = Path(path)
        if path.is_symlink() or path.parent.resolve() != self.sources:
            raise ValueError('Refusing eviction outside owned source cache')
        record = self.receipts/(path.stem+'.ownership.json')
        if not record.exists():
            raise ValueError('Refusing unregistered source eviction')
        owner = json.loads(record.read_text())
        if owner['path'] != str(path):
            raise ValueError('Source ownership mismatch')
        if 'checkpoint' in proof:
            replacement = Path(proof['checkpoint'])
            if not replacement.is_file() or sha(replacement) != proof['sha256']:
                raise ValueError('Verified H3 replacement required before eviction')
        elif owner.get('state') != 'partial' or proof.get('disposable') != 'Incomplete/failed attempt':
            raise ValueError('Complete sources need a verified H3 replacement')
        if path.exists():
            owner.update(eviction_proof=proof, evicted_bytes=path.stat().st_size)
            atomic_json(record, owner)
            path.unlink()
            self._save_state()

    def _acquire(self, kind, start, end, rectangle):
        dataset, var = DATASETS[kind]
        a,b,c,d = rectangle
        url = f'{BASE}/griddap/{dataset}.nc?{var}[({start}T00:30:00Z):1:({end}T23:30:00Z)][0][{a}:1:{b}][{c}:1:{d}]'
        key = hashlib.sha256(url.encode()).hexdigest()
        path = self.sources/(key+'.gz')
        receipt = self.receipts/(key+'.json')
        ownership = self.receipts/(path.stem+'.ownership.json')
        if path.exists() and receipt.exists():
            record = json.loads(receipt.read_text())
            if record['url'] != url or sha(path) != record['compressed_sha256']:
                raise ValueError('Retained source checksum/request mismatch')
            inspect_source(path, kind, start, end, rectangle)
            return path, record
        # Reuse qualified canonical archives by reference, without copying/evicting.
        for seed in self.seeds:
            for metadata in sorted(seed.glob('*.receipt.json')):
                r = json.loads(metadata.read_text())
                if not r.get('successful_complete_download') or (r.get('kind'),r.get('start'),r.get('end')) != (kind,str(start),str(end)) or dataset not in r.get('url',''):
                    continue
                candidate = metadata.with_name(metadata.name.replace('.receipt.json','.nc.http-gzip'))
                if not candidate.exists() or sha(candidate) != r.get('compressed_sha256'):
                    continue
                try:
                    inspect_source(candidate, kind, start, end, rectangle)
                except InsufficientSourceCoverage:
                    continue  # preserve the valid narrow archive; fetch full support
                r = {**r, 'external_reference':str(candidate), 'requested_url':url}
                atomic_json(receipt, r)
                return candidate, r
        if self.offline:
            raise ValueError('Offline source unavailable')
        if path.exists() and ownership.exists() and json.loads(ownership.read_text()).get('state')=='complete':
            raise ValueError('Complete source has lost its receipt; preserve for recovery')
        atomic_json(ownership, dict(path=str(path), url=url,state='partial',purpose='Transient hourly input; verified H3 checkpoint replacement required'))
        errors = []
        for attempt in range(3):
            if path.exists():
                self.evict(path, {'disposable':'Incomplete/failed attempt', 'errors':errors})
            self._reserve(key, url)
            clock = time.monotonic()
            try:
                digest = hashlib.sha256()
                decoded = compressed = 0
                decoder = zlib.decompressobj(16+zlib.MAX_WBITS)
                with requests.get(url, stream=True, timeout=(20,600), headers={'Accept-Encoding':'gzip'}) as response:
                    response.raise_for_status()
                    if response.headers.get('Content-Encoding') != 'gzip':
                        raise ValueError('Require lossless HTTP gzip source')
                    response.raw.decode_content = False
                    header_seconds = time.monotonic()-clock
                    with path.open('xb', buffering=0) as handle:
                        while True:
                            block = response.raw.read(65536)
                            if not block:
                                break
                            compressed += len(block)
                            value = decoder.decompress(block)
                            decoded += len(value)
                            if compressed > 450_000_000 or decoded > 1_250_000_000 or time.monotonic()-clock > 1200:
                                raise ValueError('Response byte/wall-time cap exceeded')
                            self._write(handle, block, key)
                            digest.update(value)
                if decoder.flush() or not decoder.eof:
                    raise ValueError('Truncated gzip source')
                header, bounds = inspect_source(path,kind,start,end,rectangle)
                if bounds != list(rectangle):
                    raise ValueError('Server returned unexpected subset bounds')
                expected = max(v['begin']+int(np.prod(v['shape']))*v['itemsize'] for v in header['variables'].values())
                if decoded != expected:
                    raise ValueError('Decoded NetCDF length mismatch')
                record = dict(url=url,kind=kind,start=str(start),end=str(end),bounds=bounds,
                              retrieved_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                              compressed_bytes=compressed,decoded_bytes=decoded,compressed_sha256=sha(path),
                              decoded_sha256=digest.hexdigest(),header_seconds=header_seconds,
                              seconds=time.monotonic()-clock,attempt=attempt+1)
                atomic_json(receipt,record)
                atomic_json(ownership,dict(path=str(path),url=url,state='complete',compressed_sha256=record['compressed_sha256']))
                return path,record
            except (requests.RequestException, OSError, ValueError) as exc:
                errors.append(repr(exc))
                atomic_json(self.receipts/(key+'.failure.json'),dict(url=url,errors=errors,status='pending'))
                if path.exists():
                    self.evict(path,{'disposable':'Incomplete/failed attempt','errors':errors})
                if attempt < 2:
                    if self._stop.wait(15*(attempt+1)):
                        raise RuntimeError('Source acquisition cancelled')
            finally:
                self._release(key)
        raise RuntimeError('Monthly/weekly acquisition remains pending: '+repr(errors))
