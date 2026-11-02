"""Resumable bounded 2024 regional history with retained compressed sources."""
from __future__ import annotations
import argparse,datetime as dt,fcntl,gzip,hashlib,json,os,shutil,time,uuid
from pathlib import Path
import geopandas as gpd,h3,numpy as np,pandas as pd,pyarrow as pa,pyarrow.parquet as pq,requests,shapely,xarray as xr
from .daily import sha,write_json,study_inputs,recover,publish
from .regional import PRODUCTS,rotation,validate,read_source
from .regional_streaming import temporal_means
DATASETS={'salinity':('ubcSSg3DPhysicsFields1hV21-11','salinity'),'u':('ubcSSg3DuGridFields1hV21-11','uVelocity'),'v':('ubcSSg3DvGridFields1hV21-11','vVelocity')}
CAP=10_000_000_000; FLOOR=20_000_000_000; RESPONSE=40_000_000

def cache_size(root):return sum(p.stat().st_size for p in Path(root).rglob('*') if p.is_file())
def budget(root,extra=0):
    if cache_size(root)+extra>CAP:raise ValueError('10 GB retained-cache cap reached')
    if shutil.disk_usage(root).free<FLOOR+extra:raise ValueError('20 GB free-space floor reached')
def url(kind,day):
    ds,var=DATASETS[kind]
    return f'https://salishsea.eos.ubc.ca/erddap/griddap/{ds}.nc?{var}[({day}T00:30:00Z):1:({day}T23:30:00Z)][0][0:1:897][0:1:397]'

def checked_source(path,receipt):
    r=json.loads(receipt.read_text())
    if sha(path)!=r['compressed_sha256']:raise ValueError('Compressed source checksum mismatch')
    digest=hashlib.sha256();n=0
    with gzip.open(path,'rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):
            n+=len(block)
            if n>RESPONSE:raise ValueError('Decoded source budget exceeded')
            digest.update(block)
    if n!=r['bytes'] or digest.hexdigest()!=r['sha256']:raise ValueError('Decoded source checksum mismatch')
    return r

def acquire(root,kind,day,pilot,offline=False):
    name=f'{kind}-{day}';path=root/'sources'/(name+'.nc.gz');receipt=path.with_suffix('.json');request=url(kind,day)
    if path.exists() and receipt.exists():
        r=checked_source(path,receipt)
        if r['url']!=request:raise ValueError('Source request mismatch')
        return path,r
    if path.exists():raise ValueError('Uncertain source state: file without receipt')
    old=pilot/(name+'.nc');oldreceipt=pilot/(name+'.json')
    if offline and not (old.exists() and oldreceipt.exists()):raise ValueError('Offline source unavailable')
    errors=[]
    for attempt in range(2):
        budget(root,RESPONSE);part=path.with_suffix('.part-'+uuid.uuid4().hex);digest=hashlib.sha256();n=0;t=time.monotonic()
        try:
            if old.exists() and oldreceipt.exists():
                oldmeta=json.loads(oldreceipt.read_text())
                if sha(old)!=oldmeta['sha256']:raise ValueError('Pilot source checksum mismatch')
                blocks=iter(lambda:handle.read(1024*1024),b'')
                handle=old.open('rb');response=None
            else:
                response=requests.get(request,stream=True,timeout=(15,45));response.raise_for_status();handle=None;blocks=response.iter_content(1024*1024)
            try:
                with gzip.open(part,'wb',compresslevel=6) as out:
                    for block in blocks:
                        if time.monotonic()-t>120:raise TimeoutError('Source wall-time budget exceeded')
                        n+=len(block)
                        if n>RESPONSE:raise ValueError('Source exceeds decoded response cap')
                        digest.update(block);out.write(block)
            finally:
                if response is not None:response.close()
                if handle is not None:handle.close()
            budget(root)
            r=dict(url=request,sha256=digest.hexdigest(),bytes=n,compressed_sha256=sha(part),compressed_bytes=part.stat().st_size,retrieved_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),seconds=time.monotonic()-t,reused_pilot=old.exists(),compression='gzip',attempt=attempt+1)
            if old.exists() and r['sha256']!=oldmeta['sha256']:raise ValueError('Pilot source transfer mismatch')
            os.replace(part,path);write_json(receipt,r);checked_source(path,receipt);return path,r
        except Exception as exc:
            errors.append(str(exc));write_json(root/(name+'-failure.json'),dict(errors=errors,status='pending',retained_partial=str(part)))
            if offline or isinstance(exc,ValueError) or attempt==1:raise
            time.sleep(15)
    raise RuntimeError('Unreachable acquisition state')

def spatial(study_path,pilot):
    study,members,evidence=study_inputs(study_path);cells=members[6]
    gp,gr=read_source(pilot,'geometry');cp,cr=read_source(pilot,'coordinates')
    water=gpd.read_parquet((Path(study_path).resolve().parent/study['grid_registry']['mask_relative_path']).resolve())
    if water.crs.to_epsg()!=4326:raise ValueError('Study CRS mismatch')
    water=water.geometry.union_all()
    with xr.open_dataset(gp) as g,xr.open_dataset(cp,decode_times=False) as c:
        lon=g.longitude.values;lat=g.latitude.values
        if not np.array_equal(c.glamt.values.squeeze().astype('float32'),lon.astype('float32')) or not np.array_equal(c.gphit.values.squeeze().astype('float32'),lat.astype('float32')):raise ValueError('Coordinate grid mismatch')
        angle=rotation(c.glamu.values.squeeze(),c.gphiu.values.squeeze());weight=(c.e1t.values.squeeze()*c.e2t.values.squeeze())[1:,1:].ravel()
        wet=(g.bathymetry.values[1:,1:]>0).ravel();xx=lon[1:,1:].ravel();yy=lat[1:,1:].ravel();ids=np.array([h3.latlng_to_cell(float(y),float(x),6) for y,x in zip(yy,xx)])
        inside=wet&shapely.intersects_xy(water,xx,yy)&np.isin(ids,cells)&np.isfinite(weight)&(weight>0)
    return cells,evidence,angle,weight,ids,inside,[gr,cr]

def aggregate(day,values,cells,weight,ids,inside):
    frame=pd.DataFrame({'date':day,'h3_index':cells})
    for m,arr in values.items():
        a=arr.ravel();good=inside&np.isfinite(a);p=pd.DataFrame({'h3_index':ids[good],'weighted':a[good]*weight[good],'weight':weight[good]});s=p.groupby('h3_index')[['weighted','weight']].sum();frame[m]=frame.h3_index.map(s.weighted/s.weight)
    for name,metrics in PRODUCTS.items():validate(frame[['date','h3_index',*metrics]],metrics,[day],cells)
    return frame

def binding(study,pilot,output):
    _,_,evidence=study_inputs(study)
    return dict(study=evidence,geometry=[sha(pilot/'geometry.nc'),sha(pilot/'coordinates.nc')],code={p:sha(Path(__file__).with_name(p)) for p in ['regional_history.py','regional_streaming.py','regional.py','daily.py']},baseline={p['id']:p['sha256'] for p in json.loads((output/'catalog.json').read_text())['products'] if p['id'].startswith('salishsea-')},year=2024,cache_cap=CAP,free_floor=FLOOR)

def run(study,pilot,output,root,start,end,offline=False):
    root=Path(root);pilot=Path(pilot);output=Path(output);root.mkdir(parents=True,exist_ok=True)
    for sub in ['sources','days']:(root/sub).mkdir(exist_ok=True)
    dates=[x.date() for x in pd.date_range(start,end)]
    if not dates or any(x.year!=2024 for x in dates):raise ValueError('Authorized runner is bounded to 2024')
    with (root/'run.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);plan=binding(study,pilot,output);planpath=root/'plan.json'
        if planpath.exists():
            if json.loads(planpath.read_text())!=plan:raise ValueError('Frozen history plan changed')
        else:write_json(planpath,plan)
        cells,evidence,angle,weight,ids,inside,geometry=spatial(study,pilot)
        for day in dates:
            p=root/'days'/(str(day)+'.parquet');done=p.with_suffix('.json')
            if p.exists() and done.exists():
                meta=json.loads(done.read_text())
                if sha(p)!=meta['sha256']:raise ValueError('Checkpoint checksum mismatch')
                frame=pq.read_table(p).to_pandas()
                for name,metrics in PRODUCTS.items():validate(frame[['date','h3_index',*metrics]],metrics,[day],cells)
                continue
            paths={};receipts=[]
            for kind in DATASETS:
                paths[kind],r=acquire(root,kind,day,pilot,offline);receipts.append(r)
            frame=aggregate(day,temporal_means(paths,day,angle),cells,weight,ids,inside)
            if dt.date(2024,7,1)<=day<=dt.date(2024,7,3):
                for name,metrics in PRODUCTS.items():
                    accepted=pq.read_table(output/(name+'-r6-daily.parquet'),filters=[('date','=',day)]).to_pandas()
                    pd.testing.assert_frame_equal(frame[['date','h3_index',*metrics]],accepted,check_exact=True)
            tmp=p.with_suffix('.part');frame.to_parquet(tmp,index=False,compression='zstd');os.replace(tmp,p)
            write_json(done,dict(date=str(day),sha256=sha(p),rows=len(frame),sources=receipts))
            completed=sorted(x.stem for x in (root/'days').glob('*.parquet'));size=cache_size(root);budget(root)
            progress=dict(completed_days=len(completed),latest_completed=str(day),cache_bytes=size,source_compressed_bytes=sum(x.stat().st_size for x in (root/'sources').glob('*.nc.gz')),completed_dates=completed,updated_at_utc=dt.datetime.now(dt.timezone.utc).isoformat())
            write_json(root/'progress.json',progress);print(json.dumps({k:v for k,v in progress.items() if k!='completed_dates'}),flush=True)
        return json.loads((root/'progress.json').read_text())

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['study','pilot','output','root','start','end']:p.add_argument('--'+name,required=True)
    p.add_argument('--offline',action='store_true');a=p.parse_args();run(a.study,a.pilot,a.output,a.root,a.start,a.end,a.offline)
if __name__=='__main__':main()
