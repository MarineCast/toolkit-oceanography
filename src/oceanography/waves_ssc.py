"""SalishSeaCast canonical wave nowcasts; whole-file transfers, no range bypass."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import re
import time
from urllib.parse import urlparse
import zlib

import h5py
import numpy as np
import pandas as pd
import requests

from .daily import sha, study_inputs
from .history import atomic_json
from . import waves_regional as common

HOST = 'https://salishsea.eos.ubc.ca'
BASE = HOST+'/erddap/files/ubcSSWaveWatch3-SoGFilesV17-02/nowcast/'
INVENTORY = HOST+'/erddap/tabledap/ubcSSWaveWatch3-SoGFilesV17-02.csv?name,url,size&url=~".*/nowcast/.*"&name=~"SoG_ww3_fields_.*[.]nc"&orderBy("name")'
VARIABLES = {'hs':('m','sea_surface_wave_significant_height'),
             't02':('s','sea_surface_wind_wave_mean_period_from_variance_spectral_density_second_frequency_moment'),
             'dir':('degree','sea_surface_wave_from_direction')}
MAX_FILE = 350_000_000
MONTHS = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec']


def canonical(day):
    return f'{day.day:02d}{MONTHS[day.month-1]}{str(day.year)[2:]}'


def parse_inventory(raw):
    rows = list(csv.DictReader(raw.decode().splitlines()))
    selected, excluded = {}, []
    for row in rows:
        if not row.get('name'):
            continue
        match = re.fullmatch(r'SoG_ww3_fields_(\d{8})_(\d{8})\.nc',row['name'])
        if not match:
            raise ValueError('Unexpected wave inventory filename')
        day = dt.datetime.strptime(match[1],'%Y%m%d').date()
        url = row['url'];parsed=urlparse(url)
        if parsed.scheme!='https' or parsed.netloc!='salishsea.eos.ubc.ca' or parsed.query or parsed.fragment:
            raise ValueError('Untrusted wave inventory URL')
        expected=BASE+canonical(day)+'/'+row['name']
        if url!=expected or match[1]!=match[2]:
            excluded.append(dict(**row,reason='noncanonical directory or multiday run'));continue
        size=int(float(row['size']))
        if not 0<size<=MAX_FILE:raise ValueError('Wave inventory source file outside bound')
        if str(day) in selected:raise ValueError('Conflicting canonical wave date')
        selected[str(day)]=dict(url=url,bytes=size,name=row['name'])
    if not selected:raise ValueError('No canonical wave nowcasts')
    return dict(sorted(selected.items())),excluded


def inventory():
    with requests.Session() as session:
        session.trust_env=False
        with session.get(INVENTORY,stream=True,timeout=(15,90),allow_redirects=False) as response:
            if response.status_code!=200:raise RuntimeError('Wave inventory retrieval failed')
            raw=bytearray()
            for b in response.iter_content(65536):
                raw.extend(b)
                if len(raw)>2_000_000:raise ValueError('Wave inventory byte bound')
    selected,excluded=parse_inventory(bytes(raw))
    return selected,dict(url=INVENTORY,sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw),
                         retrieved_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),excluded=excluded)


def download(entry):
    parsed=urlparse(entry['url'])
    if parsed.query or parsed.fragment or '..' in parsed.path or not entry['url'].startswith(BASE):raise ValueError('Wave source must be the canonical official archive')
    started=time.monotonic();buffer=io.BytesIO();digest=hashlib.sha256();wire=decoded=0
    with requests.Session() as session:
        session.trust_env=False
        with session.get(entry['url'],stream=True,timeout=(15,90),allow_redirects=False,
                         headers={'Accept-Encoding':'gzip'}) as response:
            if response.status_code!=200:raise RuntimeError(f'Wave source HTTP {response.status_code}')
            encoding=response.headers.get('Content-Encoding','identity')
            if encoding not in ('identity','gzip'):raise ValueError('Unexpected wave transfer encoding')
            decoder=zlib.decompressobj(16+zlib.MAX_WBITS) if encoding=='gzip' else None
            while True:
                block=response.raw.read(65536,decode_content=False)
                if not block:break
                wire+=len(block)
                value=decoder.decompress(block,MAX_FILE-decoded+1) if decoder else block
                decoded+=len(value)
                if wire>MAX_FILE or decoded>MAX_FILE or time.monotonic()-started>240:
                    raise ValueError('Wave source byte/wall-time bound exceeded')
                digest.update(value);buffer.write(value)
            if decoder and (not decoder.eof or decoder.unused_data or decoder.flush()):
                raise ValueError('Truncated/noncanonical wave gzip response')
    if decoded!=entry['bytes']:raise ValueError('Wave file length differs from frozen inventory')
    buffer.seek(0)
    return buffer,dict(url=entry['url'],sha256=digest.hexdigest(),bytes=decoded,wire_bytes=wire,
                       seconds=time.monotonic()-started,retrieved_at_utc=dt.datetime.now(dt.timezone.utc).isoformat())


def clean_attr(value):
    if isinstance(value,bytes):return value.decode()
    if isinstance(value,np.ndarray):return value.tolist()
    if isinstance(value,np.generic):return value.item()
    return value


def grid(file):
    lat,lon=file['latitude'][:].astype('f8'),file['longitude'][:].astype('f8')
    if (lat.ndim!=1 or lon.ndim!=1 or len(lat)>2000 or len(lon)>2000
            or len(lat)<2 or len(lon)<2 or not np.isfinite(lat).all() or not np.isfinite(lon).all()
            or not np.allclose(np.diff(lat),.0045,atol=1e-5,rtol=0)
            or not np.allclose(np.diff(lon),.007,atol=2e-5,rtol=0)):
        raise ValueError('Unsupported wave grid')
    lon=(lon+180)%360-180
    return lat,lon


def times(file,day):
    v=file['time'];units=clean_attr(v.attrs.get('units'))
    if units!='days since 1990-01-01 00:00:00':raise ValueError('Wave native CF time units changed')
    raw=v[:]
    if raw.ndim!=1 or not len(raw) or not np.isfinite(raw).all():raise ValueError('Invalid native wave time axis')
    seconds=raw*86400+(pd.Timestamp('1990-01-01',tz='UTC')-pd.Timestamp(day,tz='UTC')).total_seconds()
    slots=np.rint(seconds/1800).astype(int)
    error=np.abs(seconds-slots*1800)
    if len(set(slots.tolist()))!=len(slots) or (slots<0).any() or (slots>=48).any() or (error>.001).any():
        raise ValueError('Wave native time does not match its canonical UTC day')
    return slots,dict(time_sha256=hashlib.sha256(raw.tobytes()).hexdigest(),samples=len(raw),
                      max_schedule_rounding_error_seconds=float(error.max(initial=0)),units=units)


def decode(file,name,selected):
    obj=file[name];units,standard=VARIABLES[name]
    if clean_attr(obj.attrs.get('units'))!=units or clean_attr(obj.attrs.get('standard_name'))!=standard:
        raise ValueError('Wave native variable identity/units changed: '+name)
    if obj.shape!=(len(file['time']),len(file['latitude']),len(file['longitude'])):
        raise ValueError('Wave native variable dimensions changed')
    raw=obj[:].reshape(len(file['time']),-1)[:,selected]
    missing=~np.isfinite(raw)
    for key in ('_FillValue','missing_value'):
        if key in obj.attrs:
            for fill in np.asarray(obj.attrs[key]).ravel():missing|=raw==fill
    result=raw.astype('f8')*float(np.asarray(obj.attrs.get('scale_factor',1)).item())+float(np.asarray(obj.attrs.get('add_offset',0)).item())
    result[missing]=np.nan
    return result


def native(buffer,day,selected,expected_grid):
    with h5py.File(buffer,'r') as file:
        lat,lon=grid(file)
        if not np.array_equal(lat,expected_grid['latitude']) or not np.array_equal(lon,expected_grid['longitude']):
            raise ValueError('Wave native grid changed; separate qualification required')
        slots,timing=times(file,day)
        raw=np.full((3,48,len(selected)),np.nan)
        metadata={}
        for k,name in enumerate(VARIABLES):
            raw[k,slots]=decode(file,name,selected)
            metadata[name]={key:clean_attr(file[name].attrs[key]) for key in
                ('units','standard_name','_FillValue','scale_factor','add_offset') if key in file[name].attrs}
    return raw,dict(**timing,metadata=metadata)


def source_day(entry,day,selected,expected_grid,groups,weights,ncell,fetcher=download):
    attempts=[]
    for attempt in range(3):
        try:
            buffer,receipt=fetcher(entry)
            with buffer:raw,meta=native(buffer,day,selected,expected_grid)
            values,counts=common.aggregate(raw,groups,weights,ncell)
            return values,counts,dict(status='available',**receipt,**meta)
        except (requests.RequestException,RuntimeError) as error:
            attempts.append(type(error).__name__)
            if attempt==2:raise RuntimeError('Wave retrieval pending after bounded attempts: '+','.join(attempts)) from None
            time.sleep((attempt+1)*5)
    raise AssertionError('unreachable')


def prepare(study_path,start,end,root,*,inventory_fetcher=inventory,fetcher=download):
    study,members,evidence=study_inputs(study_path);selected,receipt=inventory_fetcher()
    first=dt.date.fromisoformat(start or study['time']['start']);last=dt.date.fromisoformat(end or max(selected))
    limit=dt.date.fromisoformat(study['time']['end_exclusive'])-dt.timedelta(days=1)
    if not dt.date.fromisoformat(study['time']['start'])<=first<=last<=min(limit,dt.date.fromisoformat(max(selected))):
        raise ValueError('Regional wave dates outside study/source support')
    anchor=max(d for d in selected if d<=str(last))
    buffer,source=fetcher(selected[anchor])
    with buffer,h5py.File(buffer,'r') as file:
        lat,lon=grid(file);slots,timing=times(file,dt.date.fromisoformat(anchor))
        if not np.array_equal(slots,np.arange(48)):raise ValueError('Final wave source day is not complete')
        yy,xx=np.meshgrid(lat,lon,indexing='ij')
        cells,indices,groups,weights,_=common.mapping(study_path,yy,xx)
        for name in VARIABLES:decode(file,name,indices)
    plan=dict(provider='salishseacast',start=str(first),end=str(last),cells=cells,study=evidence,
        inventory=selected,inventory_receipt=receipt,native_grid=dict(latitude=lat.tolist(),longitude=lon.tolist()),
        mapping=dict(selected=indices.tolist(),groups=groups.tolist(),weights=weights.tolist()),
        final_native_qualification=dict(**source,**timing),code_sha256=code_hashes(),
        created_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),rights='Apache 2.0; SalishSeaCast Project Contributors / UBC / DFO IOS')
    atomic_json(root/'plan.json',plan)
    return plan


def code_hashes():
    return {n:sha(Path(__file__).parent/n) for n in ('waves_ssc.py','waves_regional.py','waves.py','daily.py','history.py')}


def run(study_path,start=None,end=None,*,output=None,work=None,requests_in_flight=2,
        inventory_fetcher=inventory,fetcher=download):
    import fcntl
    import shutil
    study,_,evidence=study_inputs(study_path)
    data=(Path(study_path).resolve().parent/study['storage']['data_root']).resolve()
    output=Path(output).absolute() if output else data/'Oceanography/waves-salishseacast'
    if output.is_symlink():raise ValueError('Symlink wave output refused')
    output=output.resolve()
    common.delivery_target(output,'salishseacast',evidence)
    root=Path(work).absolute() if work else data.parent/'.marinecast-work/oceanography'/('waves-ssc-'+hashlib.sha256(str(output).encode()).hexdigest()[:16])
    if root.is_symlink():raise ValueError('Symlink wave work refused')
    root=root.resolve()
    if data==root or data in root.parents or root==output or root in output.parents or output in root.parents:
        raise ValueError('Wave work must be outside Data and separate from delivery')
    if requests_in_flight not in (1,2):raise ValueError('Require one or two source requests')
    root.mkdir(parents=True,exist_ok=True)
    marker=root/'ownership.json';owner=dict(pipeline='waves-salishseacast',output=str(output))
    if marker.exists() and json.loads(marker.read_text())!=owner:raise ValueError('Wave work ownership mismatch')
    if not marker.exists():
        if any(root.iterdir()):raise ValueError('Unowned wave work preserved')
        atomic_json(marker,owner)
    with (root/'run.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if shutil.disk_usage(root).free<26_000_000_000:raise ValueError('Wave staging requires 6 GB headroom above 20 GB floor')
        if (root/'plan.json').exists():
            plan=json.loads((root/'plan.json').read_text())
            if plan['code_sha256']!=code_hashes() or plan['study']!=evidence or (start and str(start)!=plan['start']) or (end and str(end)!=plan['end']):
                raise ValueError('Frozen wave plan differs; preserve it and use a new owned work/output for revised scope')
        else:plan=prepare(study_path,start,end,root,inventory_fetcher=inventory_fetcher,fetcher=fetcher)
        cells=plan['cells'];m=plan['mapping'];groups=np.asarray(m['groups'],dtype=int);weights=np.asarray(m['weights'],dtype=float);indices=np.asarray(m['selected'],dtype=int);days=[s.date() for s in pd.date_range(plan['start'],plan['end'])]
        n=48;checkpoints=root/'checkpoints';checkpoints.mkdir(exist_ok=True)
        atomic_json(root/'staging-manifest.json',dict(owner=owner,exact_paths=[str(checkpoints),str(output)],purpose='Final H3 checkpoints and one atomic final delivery; source bytes held only in RAM',expected_peak_output_bytes=2_000_000_000))
        completed=[];pending=[]
        for day in days:
            p=checkpoints/str(day)
            if p.exists():
                record,_=common.read_checkpoint(p,'salishseacast',day,cells);common.validate_source(plan,day,record['source']);completed.append(str(day))
            else:pending.append(day)
        if not pending and (output/'catalog.json').exists():
            cat=json.loads((output/'catalog.json').read_text())
            if cat.get('source_plan_sha256')!=sha(root/'plan.json'):
                raise ValueError('Existing SSC delivery belongs to another frozen plan')
            common.check(output/'catalog.json',study_path=study_path)
            atomic_json(root/'progress.json',dict(status='complete',catalog_path=str(output/'catalog.json'),unchanged=True))
            return dict(catalog_path=str(output/'catalog.json'),unchanged=True)
        def work_day(day):
            if shutil.disk_usage(root).free<20_100_000_000:raise ValueError('Wave disk floor reached')
            entry=plan['inventory'].get(str(day))
            if entry is None:
                values=np.full((3,n,len(cells)),np.nan);counts=np.zeros((4,n,len(cells)),dtype='i4')
                source=dict(status='unavailable',reason='before_first_archive_date' if str(day)<min(plan['inventory']) else 'missing_inventory_day')
            else:values,counts,source=source_day(entry,day,indices,plan['native_grid'],groups,weights,len(cells),fetcher)
            tables=common.day_tables('salishseacast',day,values,counts,cells)
            common.checkpoint(checkpoints,'salishseacast',day,tables,cells,source)
            return day,source
        atomic_json(root/'progress.json',dict(status='running',completed_days=len(completed),expected_days=len(days),source_date_start=min(plan['inventory']),source_date_end=max(plan['inventory'])))
        try:
            # Queue only two tasks; completed payloads are reduced before a new
            # response is started. Native files are never accumulated on disk.
            with ThreadPoolExecutor(max_workers=requests_in_flight) as pool:
                futures={};iterator=iter(pending)
                for _ in range(requests_in_flight):
                    day=next(iterator,None)
                    if day is not None:futures[day]=pool.submit(work_day,day)
                while futures:
                    day=min(futures);_,source=futures.pop(day).result();completed.append(str(day))
                    atomic_json(root/'progress.json',dict(status='running',completed_days=len(completed),expected_days=len(days),last_completed_date=str(day),last_source_status=source['status'],last_source_seconds=source.get('seconds'),updated_at_utc=dt.datetime.now(dt.timezone.utc).isoformat()))
                    if len(completed)%25==0 or source['status']=='available':print(json.dumps(dict(provider='salishseacast',completed=len(completed),total=len(days),day=str(day),source=source['status'])),flush=True)
                    following=next(iterator,None)
                    if following is not None:futures[following]=pool.submit(work_day,following)
            return common.finalize(root,output,plan,study_path)
        except BaseException as error:
            atomic_json(root/'progress.json',dict(status='failed',completed_days=len(completed),expected_days=len(days),error=type(error).__name__,detail=str(error)[:250],updated_at_utc=dt.datetime.now(dt.timezone.utc).isoformat()))
            raise


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--study',required=True);p.add_argument('--start');p.add_argument('--end');p.add_argument('--output');p.add_argument('--work');p.add_argument('--requests-in-flight',type=int,default=2);p.add_argument('--check')
    a=p.parse_args(argv)
    result=common.check(a.check,study_path=a.study) if a.check else run(a.study,a.start,a.end,output=a.output,work=a.work,requests_in_flight=a.requests_in_flight)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
