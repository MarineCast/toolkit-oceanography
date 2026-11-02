"""Bounded full-study daily satellite products; no routing or sibling imports."""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import uuid
import fcntl
import h3
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests
import xarray as xr

BASE = 'https://coastwatch.pfeg.noaa.gov/erddap'
SOURCES = {
 'sst': dict(dataset='jplMURSST41', variable='analysed_sst', units='degree_C', metric='sst_c', resolution=6, hour=9, ascending=True, spacing=0.01, description='MUR v4.1 daily gap-filled foundation sea surface temperature analysis; not an observation-only daily SST product.'),
 'chlorophyll': dict(dataset='erdMH1chla1day_R2022SQ', variable='chlor_a', units='mg m-3', metric='chlorophyll_mg_m3', resolution=5, hour=12, ascending=False, spacing=1/24, description='MODIS Aqua R2022 science-quality daily chlorophyll retrievals; biomass proxy, not harmful algal bloom identification. Cloud and coastal gaps remain null.'),
}
MAX_BYTES = 250_000_000

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''): h.update(block)
    return h.hexdigest()

def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True)+'\n')

def study_inputs(path):
    path = Path(path).resolve()
    study = json.loads(path.read_text())
    reg = study['grid_registry']
    if study['domain']['status'] != 'approved' or reg['status'] != 'validated':
        raise ValueError('Study/membership is not approved and validated')
    if reg['mask_revision'] != study['domain']['revision']:
        raise ValueError('Study revision mismatch')
    evidence = {'study_sha256': sha(path), 'study_path': str(path), 'memberships': {}}
    for key, expected in [('mask_relative_path', reg['mask_sha256']), ('manifest_relative_path', reg['manifest_sha256'])]:
        artifact = (path.parent / reg[key]).resolve()
        if sha(artifact) != expected: raise ValueError('Study support checksum mismatch: '+str(artifact))
    members = {}
    for resolution in (5,6):
        matches = [m for m in reg['memberships'] if m['role']=='water_reporting' and m['resolution']==resolution]
        if len(matches)!=1: raise ValueError('Ambiguous study membership')
        m = matches[0]; source = (path.parent/m['relative_path']).resolve()
        if sha(source)!=m['sha256']: raise ValueError('Membership checksum mismatch')
        cells=source.read_text().splitlines()
        if len(cells)!=m['count'] or len(set(cells))!=len(cells): raise ValueError('Membership count/duplicate mismatch')
        if any(not h3.is_valid_cell(c) or h3.get_resolution(c)!=resolution for c in cells): raise ValueError('Invalid H3 membership')
        members[resolution]=sorted(cells)
        evidence['memberships'][str(resolution)]={**m,'path':str(source)}
    return study, members, evidence

class Cache:
    def __init__(self, root, offline=False):
        self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)
        self.offline=offline; self.receipts=[]; self.downloaded=0
    def get(self,url,suffix):
        key=hashlib.sha256(url.encode()).hexdigest(); path=self.root/(key+suffix); receipt=self.root/(key+'.json')
        if path.exists() and receipt.exists():
            meta=json.loads(receipt.read_text())
            if meta['url']!=url or sha(path)!=meta['sha256']: raise ValueError('Cache checksum mismatch')
        else:
            if self.offline: raise ValueError('Missing offline source: '+url)
            temp=self.root/(key+'.part')
            with requests.get(url,stream=True,timeout=(20,90)) as response:
                response.raise_for_status()
                size=0
                with temp.open('wb') as f:
                    for block in response.iter_content(1024*1024):
                        size+=len(block)
                        if self.downloaded+size>MAX_BYTES: raise ValueError('Acquisition exceeds 250 MB budget')
                        f.write(block)
            self.downloaded+=size
            meta=dict(url=url,sha256=sha(temp),bytes=size,retrieved_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),path=str(path.resolve()))
            os.replace(temp,path); write_json(receipt,meta)
        self.receipts.append(meta)
        return path

def request_source(cache,spec,day,bbox):
    info=cache.get(f"{BASE}/info/{spec['dataset']}/index.json",'.info.json')
    rows=json.loads(info.read_text())['table']['rows']
    attrs={(r[1],r[2]):r[4] for r in rows if r[0]=='attribute'}
    if attrs.get((spec['variable'],'units'))!=spec['units']: raise ValueError('Unexpected source units')
    if not pd.Timestamp(attrs['NC_GLOBAL','time_coverage_start']).date() <= day <= pd.Timestamp(attrs['NC_GLOBAL','time_coverage_end']).date(): raise ValueError('Day outside source archive')
    west,south,east,north=bbox
    lat=f'[({south}):1:({north})]' if spec['ascending'] else f'[({north}):1:({south})]'
    subset=f'[({day.isoformat()}T{spec["hour"]:02d}:00:00Z)]'+lat+f'[({west}):1:({east})]'
    variables=[spec['variable']]+(['mask'] if spec['metric']=='sst_c' else [])
    return cache.get(f"{BASE}/griddap/{spec['dataset']}.nc?"+','.join(v+subset for v in variables),'.nc')

def aggregate(path,spec,day,cells,bbox):
    with xr.open_dataset(path) as ds:
        if ds[spec['variable']].attrs.get('units')!=spec['units']: raise ValueError('Returned units mismatch')
        times=pd.DatetimeIndex(ds.time.values)
        expected=pd.Timestamp(f'{day.isoformat()}T{spec["hour"]:02d}:00:00')
        if len(times)!=1 or times[0]!=expected: raise ValueError('Returned source date/time mismatch; no nearest-date substitution')
        if ds[spec['variable']].dims!=('time','latitude','longitude'): raise ValueError('Unexpected dimensions')
        lat=ds.latitude.values; lon=ds.longitude.values
        if len(lat)<2 or len(lon)<2 or not np.all(np.diff(lon)>0) or not np.all(np.diff(lat)*(1 if spec['ascending'] else -1)>0): raise ValueError('Unexpected coordinates')
        west,south,east,north=bbox; tol=spec['spacing']*1.1
        if abs(float(lon[0])-west)>tol or abs(float(lon[-1])-east)>tol or abs(float(min(lat))-south)>tol or abs(float(max(lat))-north)>tol: raise ValueError('Returned subset bounds mismatch')
        values=ds[spec['variable']].values[0].astype(float)
        if spec['metric']=='sst_c':
            mask=ds['mask'].values[0]
            ocean=np.isfinite(mask) & ((np.nan_to_num(mask).astype(int)&1)!=0) & ((np.nan_to_num(mask).astype(int)&2)==0)
            good=np.isfinite(values)&ocean&(values>=-3)&(values<=45)
        else: good=np.isfinite(values)&(values>0)
        iy,ix=np.where(good)
        ids=[h3.latlng_to_cell(float(lat[y]),float(lon[x]),spec['resolution']) for y,x in zip(iy,ix)]
        weights=np.cos(np.deg2rad(lat[iy]))
        samples=pd.DataFrame({'h3_index':ids,'weighted':values[iy,ix]*weights,'weight':weights})
        samples=samples[samples.h3_index.isin(cells)]
        grouped=samples.groupby('h3_index')[['weighted','weight']].sum()
        means=grouped.weighted/grouped.weight
        result=pd.DataFrame({'date':[day]*len(cells),'h3_index':cells})
        result[spec['metric']]=result.h3_index.map(means).astype(float)
        diagnostic=dict(native_shape=list(values.shape),valid_native_pixels=int(good.sum()),accepted_native_pixels=len(samples),source_bytes=Path(path).stat().st_size,nonnull=int(result[spec['metric']].notna().sum()),null=int(result[spec['metric']].isna().sum()))
        return result,diagnostic

def validate_frame(frame,spec,dates,cells):
    metric=spec['metric']
    if list(frame.columns)!=['date','h3_index',metric]: raise ValueError('Public schema mismatch')
    expected=pd.MultiIndex.from_product([dates,cells],names=['date','h3_index'])
    actual=pd.MultiIndex.from_frame(frame[['date','h3_index']])
    if not actual.equals(expected): raise ValueError('Output identity/order/membership mismatch')
    values=frame[metric].dropna()
    if not np.isfinite(values).all(): raise ValueError('Nonfinite output')
    if metric=='sst_c' and not values.between(-3,45).all(): raise ValueError('SST range')
    if metric!='sst_c' and not (values>0).all(): raise ValueError('Chlorophyll range')

def recover(output,work):
    journal=work/'publication.json'
    if journal.exists():
        record=json.loads(journal.read_text()); backup=Path(record['backup'])
        if not output.exists() and backup.exists(): os.replace(backup,output)
        if record['state']!='complete':
            record['state']='recovered'; write_json(journal,record)

def publish(stage,output,work):
    backup=work/('previous-'+uuid.uuid4().hex)
    journal=work/'publication.json'
    write_json(journal,{'state':'prepared','backup':str(backup),'stage':str(stage),'output':str(output)})
    if output.exists(): os.replace(output,backup)
    try: os.replace(stage,output)
    except BaseException:
        if backup.exists(): os.replace(backup,output)
        raise
    write_json(journal,{'state':'complete','backup':str(backup),'output':str(output)})

def run(study_path,output,cache_root,start,end,offline=False,preflight=False):
    study,members,evidence=study_inputs(study_path)
    dates=[d.date() for d in pd.date_range(start,end)]
    if not dates or len(dates)>31: raise ValueError('Require 1..31 ordered days')
    bbox=study['domain']['bbox_wgs84']
    estimates={name:int((bbox[2]-bbox[0])/s['spacing']+2)*int((bbox[3]-bbox[1])/s['spacing']+2)*(9 if name=='sst' else 4)*len(dates) for name,s in SOURCES.items()}
    if sum(estimates.values())>MAX_BYTES: raise ValueError('Estimated source bytes exceed budget')
    if preflight: return {'bbox':bbox,'dates':[str(x) for x in dates],'memberships':{str(r):len(c) for r,c in members.items()},'estimated_uncompressed_source_bytes':estimates}
    output=Path(output).resolve(); work=output.parent.parent/'.marinecast-work'/'oceanography'; work.mkdir(parents=True,exist_ok=True)
    output.parent.mkdir(parents=True,exist_ok=True)
    with (work/'publication.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        recover(output,work)
        stage=work/('stage-'+uuid.uuid4().hex); stage.mkdir()
        cache=Cache(cache_root,offline)
        catalog={'schema_version':1,'domain':'oceanography','study_id':study['study_id'],'study_revision':study['domain']['revision'],'date_start':str(dates[0]),'date_end':str(dates[-1]),'date_basis':'Native daily UTC source date label; MUR 09:00 UTC, MODIS 12:00 UTC. Not local-day aggregation.','method':'Cos(latitude)-weighted mean of valid native pixel centres assigned to each approved H3 water-reporting cell. No spatial or temporal filling by toolkit; no exact water/pixel area integration.','study':evidence,'code_sha256':sha(__file__),'products':[]}
        diagnostics={}
        for name,spec in SOURCES.items():
            frames=[]; diagnostics[name]={}
            for day in dates:
                path=request_source(cache,spec,day,bbox)
                frame,diag=aggregate(path,spec,day,members[spec['resolution']],bbox)
                frames.append(frame); diagnostics[name][str(day)]=diag
                print(json.dumps({'product':name,'date':str(day),**diag}),flush=True)
            frame=pd.concat(frames,ignore_index=True)
            validate_frame(frame,spec,dates,members[spec['resolution']])
            filename=f'{name}-r{spec["resolution"]}-daily.parquet'
            schema=pa.schema([('date',pa.date32()),('h3_index',pa.string()),(spec['metric'],pa.float64())])
            pq.write_table(pa.Table.from_pandas(frame,schema=schema,preserve_index=False),stage/filename,compression='zstd')
            validate_frame(pq.read_table(stage/filename).to_pandas(),spec,dates,members[spec['resolution']])
            values=frame[spec['metric']].dropna()
            catalog['products'].append(dict(id=name,path=filename,sha256=sha(stage/filename),columns=['date','h3_index',spec['metric']],metric=spec['metric'],units=spec['units'],h3_resolution=spec['resolution'],row_count=len(frame),date_start=str(dates[0]),date_end=str(dates[-1]),source_dataset=spec['dataset'],source_url=f'{BASE}/griddap/{spec["dataset"]}.html',description=spec['description'],native_spacing_degrees=spec['spacing'],nonnull=int(len(values)),null=int(len(frame)-len(values)),minimum=None if values.empty else float(values.min()),maximum=None if values.empty else float(values.max())))
        catalog['source_receipts']=cache.receipts; catalog['validation']=diagnostics
        catalog['downloaded_bytes']=cache.downloaded
        write_json(stage/'catalog.json',catalog)
        publish(stage,output,work)
        return catalog

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ['study','output','cache','start','end']: p.add_argument('--'+arg,required=True)
    p.add_argument('--offline',action='store_true'); p.add_argument('--preflight',action='store_true')
    a=p.parse_args(); print(json.dumps(run(a.study,a.output,a.cache,a.start,a.end,a.offline,a.preflight),indent=2))

if __name__=='__main__': main()
