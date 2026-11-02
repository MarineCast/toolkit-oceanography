"""Bounded LiveOcean low-pass surface scalars; monthly checkpoints, final H3 only."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import fcntl
import hashlib
import io
import importlib.metadata
import json
import os
import re
from pathlib import Path
import shutil
import threading
import time

import h3
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests
import shapely
import geopandas as gpd

from .daily import sha, study_inputs
from .history import atomic_json

URLS = [f'https://s3.kopah.uw.edu/cas7-t0-x4b/for_kopah/surface2_surf_lowpass_{a}_{b}.nc'
        for a,b in [('2013.01.01','2019.12.31'),('2020.01.01','2024.12.31')]]
FIELDS = {'salt': ('salinity','reference_salinity_g_kg','g kg-1'),
          'oxygen': ('oxygen','dissolved_oxygen_mmol_m3','mmol oxygen m-3'),
          'NO3': ('nitrate','nitrate_mmol_m3','mmol nitrogen m-3')}
CAP = 2_000_000_000
FLOOR = 20_000_000_000
MAX_RANGE = 450_000_000
FACTOR = 35.16504 / 35
METHOD = ('Daily noon-labelled 71-hour Godin low-pass surface model estimate; '
          'not a midnight-to-midnight UTC mean. Native wet centres inside approved '
          'study water, assigned directly to R6, weighted by 1/(pm*pn); no filling.')


def require(condition, message):
    if not condition:
        raise ValueError(message)


class Budget:
    def __init__(self, root, shared=()):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.shared = sorted(set(Path(p).resolve() for p in shared) | {self.root})
        for a in self.shared:
            for b in self.shared:
                require(a == b or a not in b.parents, 'Overlapping source-cache roots')
        self.lock = threading.Lock()
        self.reserved = 0
        self.peak = 0

    def used(self):
        return sum(p.stat().st_size for r in self.shared if r.exists()
                   for p in r.rglob('*') if p.is_file())

    def reserve(self, size):
        require(0 < size <= MAX_RANGE+4096, 'Range exceeds bounded response reservation')
        with self.lock:
            used = self.used()
            require(used + self.reserved + size <= CAP, 'Shared 2 GB source cap')
            require(shutil.disk_usage(self.root).free >= FLOOR + size, '20 GB free-space floor')
            self.reserved += size
            self.peak = max(self.peak, used + self.reserved)

    def release(self, size):
        with self.lock:
            self.reserved -= size
            require(self.reserved >= 0, 'Invalid reservation accounting')


class Archive(io.RawIOBase):
    """Seekable HDF5 reader over exact verified ranges; no whole-object staging."""
    def __init__(self, index, root, budget, seed=None, binding=None, offline=False):
        super().__init__()
        self.index = index
        self.url = URLS[index]
        self.root = Path(root)
        self.seed = Path(seed) if seed else None
        self.budget = budget
        self.offline = offline
        self.pos = 0
        self.session = requests.Session()
        self.local = threading.local()
        self.ranges = []
        self.receipts = {}
        self.stats_lock = threading.Lock()
        self.stats = {'requests': 0, 'wire_bytes': 0, 'http_seconds': 0., 'reused_ranges': 0}
        if offline:
            require(binding is not None, 'Offline archive binding required')
            self.binding = binding
        else:
            with self.session.head(self.url, timeout=(15,45)) as r:
                r.raise_for_status()
                self.binding = {'url': self.url, 'etag': r.headers['ETag'],
                                'object_bytes': int(r.headers['Content-Length']),
                                'last_modified': r.headers.get('Last-Modified')}
            if binding is not None:
                require(self.binding == binding, 'Frozen source object changed')
        self.length = self.binding['object_bytes']

    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.pos

    def seek(self, offset, whence=0):
        value = offset if whence == 0 else self.pos + offset if whence == 1 else self.length + offset
        require(0 <= value <= self.length, 'Invalid archive seek')
        self.pos = value
        return value

    def fetch(self, start, size):
        require(0 <= start < self.length and 0 < size <= min(MAX_RANGE,self.length-start), 'Invalid byte range')
        name = f'object-{self.index}-{start}-{size}.bin'
        target = self.root/name
        receipt = target.with_suffix('.json')
        for base in [self.root, self.seed]:
            if base is None: continue
            p = base/name
            if not p.exists(): continue
            r = json.loads(p.with_suffix('.json').read_text())
            require(r['url'] == self.url and r['etag'] == self.binding['etag'] and
                    r['start'] == start and r['bytes'] == size and p.stat().st_size == size and
                    sha(p) == r['sha256'], 'Range cache binding/checksum mismatch')
            with self.stats_lock:
                self.receipts[name] = r
                self.stats['reused_ranges'] += 1
            return p,r
        require(not self.offline, 'Missing offline range: '+name)
        reservation=size+4096  # Bounded JSON receipt and atomic receipt scratch.
        self.budget.reserve(reservation)
        part = target.with_suffix('.part')
        try:
            clock = time.monotonic()
            if not hasattr(self.local,'session'): self.local.session = requests.Session()
            for attempt in range(3):
                try:
                    digest = hashlib.sha256()
                    count = 0
                    with self.local.session.get(self.url, headers={'Range':f'bytes={start}-{start+size-1}',
                         'If-Match':self.binding['etag'],'Accept-Encoding':'identity'},
                         stream=True,timeout=(15,60)) as response:
                        response.raise_for_status()
                        require(response.status_code == 206 and
                                response.headers.get('Content-Range') == f'bytes {start}-{start+size-1}/{self.length}',
                                'Server did not honor exact bounded range')
                        with part.open('wb') as handle:
                            for block in response.iter_content(262144):
                                count += len(block)
                                require(count <= size and time.monotonic()-clock < 600, 'Range length/wall limit')
                                handle.write(block); digest.update(block)
                            handle.flush(); os.fsync(handle.fileno())
                    require(count == size, 'Truncated range')
                    break
                except requests.RequestException:
                    if attempt == 2: raise
                    time.sleep(attempt+1)
            r = {'url':self.url,'etag':self.binding['etag'],'start':start,'bytes':size,
                 'sha256':digest.hexdigest(),'seconds':time.monotonic()-clock,
                 'retrieved_utc':dt.datetime.now(dt.timezone.utc).isoformat()}
            # Reservation remains held until the new on-disk bytes become visible.
            with self.budget.lock:
                os.replace(part,target)
                atomic_json(receipt,r)
                self.budget.reserved -= reservation
            with self.stats_lock:
                self.receipts[name] = r
                self.stats['requests'] += 1
                self.stats['wire_bytes'] += size
                self.stats['http_seconds'] += r['seconds']
            return target,r
        except BaseException:
            # Own incomplete response only; completed sources/checkpoints are preserved.
            part.unlink(missing_ok=True)
            self.budget.release(reservation)
            raise

    def read(self, size=-1):
        size = self.length-self.pos if size < 0 else min(size,self.length-self.pos)
        if size == 0: return b''
        start = self.pos
        for lo,hi,path in self.ranges:
            if lo <= start and start+size <= hi:
                with path.open('rb') as f:
                    f.seek(start-lo); data = f.read(size)
                require(len(data) == size, 'Short local range')
                self.pos += size
                return data
        # All actual field reads must be supplied by registered month payloads.
        require(size <= 16_000_000, 'Unplanned large read outside monthly payload')
        lo = start if size > 131072 else start//65536*65536
        hi = start+size if size > 131072 else min(self.length, ((start+size+65535)//65536)*65536)
        path,_ = self.fetch(lo,hi-lo)
        self.ranges.append((lo,hi,path))
        return self.read(size)

    def readinto(self,b):
        data = self.read(len(b)); b[:len(data)] = data; return len(data)


def native_metadata(handle, index):
    history=handle.attrs.get('history','')
    if isinstance(history,bytes):history=history.decode()
    require('lowpassed.nc' in history and '-d s_rho,29' in history, 'Unqualified source processing/depth')
    expected = pd.date_range('2013-01-01T12:00Z' if index == 0 else '2020-01-01T12:00Z',
                             '2019-12-31T12:00Z' if index == 0 else '2024-12-31T12:00Z',freq='D')
    axis = handle['ocean_time']
    units = axis.attrs['units']
    if isinstance(units,bytes): units = units.decode()
    require(units.startswith('days since '), 'Unexpected source time units')
    dates = pd.DatetimeIndex(pd.Timestamp(units.removeprefix('days since '),tz='UTC')+
                             pd.to_timedelta(axis[:],unit='D'))
    require(dates.equals(expected), 'Incomplete or changed daily noon axis')
    for name in FIELDS:
        d = handle[name]
        require(d.shape == (len(dates),1302,663) and d.chunks == (1,1302,663) and
                d.dtype == np.dtype('float32') and d.compression == 'gzip', 'Native field layout changed')
    for name,unit in [('oxygen','millimole_oxygen meter-3'),('NO3','millimole_nitrogen meter-3')]:
        actual = handle[name].attrs['units']
        require((actual.decode() if isinstance(actual,bytes) else actual) == unit, 'Source units changed')
    return dates


def spatial(handle, study_path, support):
    study,members,evidence = study_inputs(study_path)
    require(evidence['study_sha256'] == support['study_sha256'], 'Support study mismatch')
    water = gpd.read_parquet((Path(study_path).resolve().parent/study['grid_registry']['mask_relative_path']).resolve())
    require(water.crs.to_epsg() == 4326, 'Water geometry CRS mismatch')
    lon,lat = handle['lon_rho'][:],handle['lat_rho'][:]
    require(lon.shape == lat.shape == (1302,663), 'Unexpected coordinate shape')
    weights = 1/(handle['pm'][:]*handle['pn'][:])
    inside = (handle['mask_rho'][:] == 1)&np.isfinite(lon)&np.isfinite(lat)&np.isfinite(weights)&(weights>0)
    inside &= shapely.intersects_xy(water.geometry.union_all(),lon,lat)
    ids = np.full(lon.shape,'',dtype='U15')
    ids[inside] = [h3.latlng_to_cell(float(y),float(x),6) for y,x in zip(lat[inside],lon[inside])]
    inside &= np.isin(ids,members[6]); ids[~inside] = ''
    masks = {}
    for name in FIELDS:
        selected = support['salinity_r6'] if name == 'salt' else support['scalar_r6']
        require(len(selected) == len(set(selected)) and set(selected) <= set(members[6]), 'Invalid target support')
        masks[name] = inside&np.isin(ids,selected)
    fingerprints = {n:hashlib.sha256(handle[n][:].tobytes()).hexdigest()
                    for n in ['lon_rho','lat_rho','mask_rho','pm','pn','h']}
    return members[6],evidence,ids,weights,masks,fingerprints


def aggregate(day, arrays, cells, ids, weights, masks):
    frame = pd.DataFrame({'date':[day]*len(cells),'h3_index':cells})
    details = {}
    for name,arr in arrays.items():
        _,metric,_ = FIELDS[name]
        good = masks[name]&np.isfinite(arr)&(arr>=0)&(arr<1e19)
        if name == 'salt': good &= arr<=50
        samples = pd.DataFrame({'h3_index':ids[good],'wv':arr[good]*weights[good],'weight':weights[good]})
        sums = samples.groupby('h3_index')[['wv','weight']].sum()
        values = sums.wv/sums.weight
        if name == 'salt': values = values*FACTOR
        frame[metric] = frame.h3_index.map(values).astype(float)
        require(len(values)>0, 'Wholly missing source day/field')
        details[name] = {'native_sha256':hashlib.sha256(arr.tobytes()).hexdigest(),
                         'finite_r6':len(values),'accepted_native_points':int(good.sum()),
                         'excluded_native_points':int((masks[name]&~good).sum())}
    return frame,details


def validate(frame, days, cells):
    require(list(frame.columns) == ['date','h3_index',*[v[1] for v in FIELDS.values()]], 'H3 schema mismatch')
    require(pd.MultiIndex.from_frame(frame[['date','h3_index']]).equals(
        pd.MultiIndex.from_product([days,cells],names=['date','h3_index'])), 'H3 identity/order mismatch')
    for _,metric,_ in FIELDS.values():
        a=frame[metric].dropna().to_numpy()
        require(np.isfinite(a).all() and (a>=0).all(), 'Invalid output concentration')


def chunks(handle, names, indices):
    ranges=[]
    for name in names:
        for index in indices:
            info=handle[name].id.get_chunk_info_by_coord((index,0,0))
            require(info.byte_offset is not None and info.size>0 and info.filter_mask == 0, 'Missing/changed native chunk')
            ranges.append((info.byte_offset,info.size))
    return sorted(set(ranges))


def evict_payloads(archive, payloads, proof):
    require(Path(proof['path']).exists() and sha(proof['path']) == proof['sha256'], 'H3 replacement not verified')
    removed=[]
    for path,receipt in payloads:
        if path.parent != archive.root: continue  # External seeds are not disposable here.
        require(sha(path) == receipt['sha256'], 'Source checksum changed before eviction')
        path.unlink(); path.with_suffix('.json').unlink()
        removed.append({'name':path.name,'bytes':receipt['bytes'],'sha256':receipt['sha256']})
    payload_paths={p for p,_ in payloads}
    archive.ranges=[r for r in archive.ranges if r[2] not in payload_paths]
    return removed


def assemble(root, output, plan, cells, months):
    output.mkdir(parents=True,exist_ok=True)
    prepared=root/'publication-prepared.json'
    if prepared.exists():
        record=json.loads(prepared.read_text())
        require(record['plan_sha256']==sha(root/'plan.json'),'Publication plan mismatch')
        return publish_products(root,output,plan,record['products'])
    lineage_name='liveocean-lineage.json'
    lineage=root/lineage_name
    atomic_json(lineage,{'plan':plan,'fields':FIELDS,'method':METHOD,
        'source_retention':'Generated payloads/checkpoints removed after verified final H3 readback; replay requires source reacquisition.',
        'salinity_convention':'Practical salinity inferred from provider model-analysis code; explicit SR=SP*35.16504/35 conversion. File salt units absent.',
        'depth':'ROMS terrain-following surface rho layer, native index 29; not fixed 0.5 m.',
        'forecast_eligible':False,'model_eligible':False,
        'metadata_range_receipts':[json.loads(p.read_text()) for p in sorted((root/'sources').glob('*.json'))],
        'months':[json.loads((root/'months'/(m+'.json')).read_text()) for m in months]})
    products=[]
    for name,(family,metric,units) in FIELDS.items():
        filename=f'liveocean-{family}-r6-daily.parquet'
        stage=root/(filename+'.part')
        schema=pa.schema([('date',pa.date32()),('h3_index',pa.string()),(metric,pa.float64())])
        with pq.ParquetWriter(stage,schema,compression='zstd') as writer:
            for month in months:
                p=root/'months'/(month+'.parquet');r=json.loads(p.with_suffix('.json').read_text())
                require(sha(p) == r['sha256'], 'Checkpoint checksum changed during assembly')
                frame=pq.read_table(p).to_pandas()
                validate(frame,[x.date() for x in pd.date_range(r['start'],r['end'])],cells)
                for _,day in frame.groupby('date',sort=False):
                    writer.write_table(pa.Table.from_pandas(day[['date','h3_index',metric]],schema=schema,preserve_index=False))
        # Every final day is independently read back against its source checkpoint.
        final=pq.ParquetFile(stage);group=0
        for month in months:
            expected=pq.read_table(root/'months'/(month+'.parquet')).to_pandas()
            for _,day in expected.groupby('date',sort=False):
                pd.testing.assert_frame_equal(final.read_row_group(group).to_pandas(),
                    day[['date','h3_index',metric]].reset_index(drop=True),check_exact=True)
                group+=1
        require(group == final.num_row_groups, 'Unexpected final day count')
        products.append({'id':f'liveocean-{family}','path':filename,'sha256':sha(stage),
            'columns':['date','h3_index',metric],'metric':metric,'metrics':[metric],'units':units,
            'h3_resolution':6,'row_count':final.metadata.num_rows,'date_start':plan['start'],'date_end':plan['end'],
            'description':METHOD,'qualification':{'study':plan['study'],'lineage_path':lineage_name,
                'lineage_sha256':sha(lineage),'source_model':'LiveOcean cas7_t0_x4b','temporal_support':'71-hour Godin low-pass centred on daily noon label',
                'forecast_eligible':False,'model_eligible':False}})
    atomic_json(prepared,{'plan_sha256':sha(root/'plan.json'),'products':products})
    return publish_products(root,output,plan,products)


def publish_products(root,output,plan,products):
    # Additive publication; conflicting prior products are never overwritten.
    with (output/'publication.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        catalog_path=output/'catalog.json';catalog=json.loads(catalog_path.read_text())
        require(catalog['study']['study_sha256'] == plan['study']['study_sha256'], 'Catalog study mismatch')
        for p in products:
            prior=next((x for x in catalog['products'] if x['id']==p['id']),None)
            require(prior is None or prior == p, 'Conflicting accepted LiveOcean product')
            for source,target,digest in [(root/(p['path']+'.part'),output/p['path'],p['sha256']),
                 (root/p['qualification']['lineage_path'],output/p['qualification']['lineage_path'],p['qualification']['lineage_sha256'])]:
                if target.exists(): require(sha(target)==digest,'Conflicting output path')
                else: os.replace(source,target)
            if prior is None: catalog['products'].append(p)
        atomic_json(catalog_path,catalog)
    return products


def cleanup_intermediates(root,output,products):
    for p in products:
        require(sha(output/p['path'])==p['sha256'] and
                sha(output/p['qualification']['lineage_path'])==p['qualification']['lineage_sha256'],
                'Published output changed before cleanup')
    path=root/'cleanup.json'
    record=json.loads(path.read_text()) if path.exists() else {'removed':[]}
    registered={p['path']:p for p in record['removed']}
    for directory in [root/'months',root/'sources']:
        for p in sorted(directory.iterdir()):
            pattern=r'\d{4}-\d{2}\.(parquet|json|part)' if directory.name=='months' else r'object-[01]-\d+-\d+\.(bin|json|part)'
            require(p.is_file() and not p.is_symlink() and re.fullmatch(pattern,p.name),'Unexpected intermediate path')
            registered[str(p)]={'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
    # Freeze the exact task-owned deletion list before removing anything.
    record.update(state='prepared',removed=list(registered.values()),verified_final_products=products,
        authorization='User requested removal of source and processing intermediates after final Parquet creation.')
    atomic_json(path,record)
    for item in record['removed']:
        p=Path(item['path'])
        require(p.parent in [root/'months',root/'sources'],'Cleanup escaped task roots')
        if p.exists():
            require(not p.is_symlink() and sha(p)==item['sha256'],'Intermediate changed before cleanup')
            p.unlink()
    # Own idempotent staging copies, if publication reused an identical target.
    for product in products:
        for p,digest in [(root/(product['path']+'.part'),product['sha256']),
                         (root/product['qualification']['lineage_path'],product['qualification']['lineage_sha256'])]:
            if p.exists():
                require(sha(p)==digest,'Unverified final staging copy');p.unlink()
    record.update(state='complete',bytes_removed=sum(p['bytes'] for p in record['removed']))
    atomic_json(path,record)


def run(study_path,support_path,output,root,start,end,shared=(),seed=None,offline=False,
        transport='chunks',limit_months=None,cleanup=True):
    import h5py
    root=Path(root).resolve();output=Path(output).resolve()
    root.mkdir(parents=True,exist_ok=True)
    marker=root/'ownership.json'
    if marker.exists():require(json.loads(marker.read_text())=={'pipeline':'liveocean-history'},'Work root ownership mismatch')
    else:
        require(not any(root.iterdir()),'Require a new empty task work root')
        atomic_json(marker,{'pipeline':'liveocean-history'})
    (root/'months').mkdir(exist_ok=True);(root/'sources').mkdir(exist_ok=True)
    require(transport in ['chunks','bulk'], 'Unknown transport')
    dates=pd.date_range(start,end)
    require(len(dates)>0 and dates[0]>=pd.Timestamp('2013-01-01') and dates[-1]<=pd.Timestamp('2024-12-31'), 'Dates outside LiveOcean archive')
    support=json.loads(Path(support_path).read_text())
    _,members,evidence=study_inputs(study_path)
    plan={'start':start,'end':end,'study':evidence,'support':support,'support_sha256':sha(support_path),
          'method':METHOD,'source_cap_bytes':CAP,'free_floor_bytes':FLOOR,'transport':transport,
          'code':{n:sha(Path(__file__).with_name(n)) for n in ['liveocean.py','daily.py','history.py']},
          'versions':{n:importlib.metadata.version(n) for n in ['h5py','numpy','pandas','pyarrow','h3','shapely']},
          'sources':[]}
    with (root/'run.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        prior=json.loads((root/'plan.json').read_text()) if (root/'plan.json').exists() else None
        if (root/'complete.json').exists():
            require(prior is not None and all(prior[k]==plan[k] for k in plan if k!='sources'), 'Completed plan changed')
            result=json.loads((root/'complete.json').read_text())
            for p in result['products']:
                require(sha(output/p['path'])==p['sha256'] and sha(output/p['qualification']['lineage_path'])==p['qualification']['lineage_sha256'], 'Completed output changed')
            if cleanup:cleanup_intermediates(root,output,result['products'])
            return result
        budget=Budget(root/'sources',shared)
        archives=[];handles=[];spatial_state=None;fingerprints=None
        try:
            for i in [0,1]:
                a=Archive(i,root/'sources',budget,seed,prior['sources'][i] if prior else None,offline)
                archives.append(a);f=h5py.File(a,'r');handles.append(f)
                axis=native_metadata(f,i);plan['sources'].append(a.binding)
                cells,ev,ids,weights,masks,fp=spatial(f,study_path,support)
                if fingerprints is not None: require(fp==fingerprints,'Archive geometry differs')
                else: fingerprints=fp;spatial_state=(cells,ids,weights,masks)
            plan['grid_sha256']=fingerprints
            if prior is not None: require(prior==plan,'Frozen LiveOcean plan changed')
            else: atomic_json(root/'plan.json',plan)
            cells,ids,weights,masks=spatial_state
            months=sorted(set(dates.strftime('%Y-%m')));done=[];processed=0
            for month in months:
                target=root/'months'/(month+'.parquet');receipt=target.with_suffix('.json')
                cohort=dates[dates.strftime('%Y-%m')==month];days=[d.date() for d in cohort]
                if target.exists() and receipt.exists():
                    record=json.loads(receipt.read_text());require(sha(target)==record['sha256'],'Checkpoint digest mismatch')
                    validate(pq.read_table(target).to_pandas(),days,cells);done.append(month);continue
                if limit_months is not None and processed>=limit_months: break
                started=time.monotonic();i=0 if cohort[0].year<=2019 else 1;a=archives[i];f=handles[i]
                origin=pd.Timestamp('2013-01-01' if i==0 else '2020-01-01')
                indices=[(d-origin).days for d in cohort]
                ranges=chunks(f,FIELDS,indices)
                if transport=='bulk': ranges=[(min(s for s,n in ranges),max(s+n for s,n in ranges)-min(s for s,n in ranges))]
                with ThreadPoolExecutor(max_workers=2) as pool:
                    payloads=list(pool.map(lambda pair:a.fetch(*pair),ranges))
                a.ranges.extend((r['start'],r['start']+r['bytes'],p) for p,r in payloads)
                frames=[];details=[]
                for day,ti in zip(days,indices):
                    frame,diag=aggregate(day,{n:f[n][ti,:,:] for n in FIELDS},cells,ids,weights,masks)
                    frames.append(frame);details.append({'date':str(day),**diag})
                frame=pd.concat(frames,ignore_index=True);validate(frame,days,cells)
                stage=target.with_suffix('.part');frame.to_parquet(stage,index=False,compression='zstd')
                pd.testing.assert_frame_equal(pq.read_table(stage).to_pandas(),frame,check_exact=True)
                os.replace(stage,target)
                record={'start':str(days[0]),'end':str(days[-1]),'sha256':sha(target),'path':str(target),
                        'sources':[r for p,r in payloads],'native_days':details,'seconds':time.monotonic()-started}
                atomic_json(receipt,record)
                record['evicted_payloads']=evict_payloads(a,payloads,record);atomic_json(receipt,record)
                done.append(month);processed+=1
                progress={'completed_months':len(done),'total_months':len(months),'latest':month,
                    'seconds_last_month':record['seconds'],'source_bytes':budget.used(),'peak_source_budget_bytes':budget.peak,
                    'updated_utc':dt.datetime.now(dt.timezone.utc).isoformat()}
                atomic_json(root/'progress.json',progress);print(json.dumps(progress),flush=True)
            if done!=months: return {'status':'partial','completed_months':len(done),'total_months':len(months)}
            products=assemble(root,output,plan,cells,months)
            result={'status':'complete','products':products,'months':len(months),'daily_labels':len(dates),
                    'source_budget_peak_bytes':budget.peak,'source_stats':[a.stats for a in archives]}
            atomic_json(root/'complete.json',result)
        finally:
            for f in handles: f.close()
            for a in archives: a.session.close()
        if cleanup:
            cleanup_intermediates(root,output,products)
        return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for n in ['study','support','output','root','start','end']:p.add_argument('--'+n,required=True)
    p.add_argument('--shared-cache',action='append',default=[])
    p.add_argument('--reuse-cache');p.add_argument('--offline',action='store_true')
    p.add_argument('--transport',choices=['chunks','bulk'],default='chunks')
    p.add_argument('--limit-months',type=int)
    a=p.parse_args(argv)
    result=run(a.study,a.support,a.output,a.root,a.start,a.end,a.shared_cache,a.reuse_cache,a.offline,a.transport,a.limit_months)
    print(json.dumps(result,indent=2));return 0


if __name__=='__main__':main()
