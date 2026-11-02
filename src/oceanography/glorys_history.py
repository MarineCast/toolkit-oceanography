"""Bounded anonymous Time Series GLORYS history; unique-object resume and offline replay."""
from __future__ import annotations
import argparse, concurrent.futures, copy, datetime, fcntl, hashlib, json, os, shutil, threading, time, uuid
from pathlib import Path
import geopandas as gpd
import h3
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests
import shapely
from .daily import sha, write_json, study_inputs, recover, publish
from .glorys import Source, PRODUCTS, DATASET, decode_chunk, unpack, surface_index, validate
CAP=2_000_000_000
RESERVE=20_000_000_000
CHUNK_CAP=1_100_000
REGIMES=[{'start':'2009-01-01','end':'2021-06-30','regime':'documented_reanalysis'}, {'start':'2021-07-01','end':'2026-09-22','regime':'documented_interim_NRT_assimilation'}]

def size(root):
    return sum(p.stat().st_size for p in Path(root).rglob('*') if p.is_file())

def guard(root, extra=0):
    if size(root)+extra>CAP:raise RuntimeError('2 GB retained-artifact cap reached')
    if shutil.disk_usage(root).free-extra<RESERVE:raise RuntimeError('20 GB free-space reserve reached')

class Cache:
    def __init__(self, root, url, offline=False):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.url=url.rstrip('/');self.offline=offline
        self.lock=threading.Lock();self.network_bytes=0;self.network_requests=0;self.reused_bytes=0;self.reused_objects=0;self.records=[]
    def fetch(self,key,limit=CHUNK_CAP):
        if '..' in key or key.startswith('/'):raise ValueError('Invalid object key')
        path=self.root/key.replace('/','-');receipt=Path(str(path)+'.receipt.json')
        if path.exists() or receipt.exists():
            if not path.exists() or not receipt.exists():raise ValueError('Incomplete cache object; preserve for investigation')
            rec=json.loads(receipt.read_text())
            if rec['key']!=key or rec['url']!=self.url+'/'+key or path.stat().st_size!=rec['bytes'] or sha(path)!=rec['sha256']:raise ValueError('Source cache mismatch')
            with self.lock:self.reused_bytes+=rec['bytes'];self.reused_objects+=1;self.records.append(rec)
            return path.read_bytes()
        if self.offline:raise FileNotFoundError(key)
        with self.lock:guard(self.root,limit*4)
        begin=time.monotonic();session=requests.Session();session.trust_env=False
        for attempt in range(2):
            try:
                with session.get(self.url+'/'+key,timeout=(10,45),stream=True) as response:
                    with self.lock:self.network_requests+=1
                    response.raise_for_status();blob=bytearray()
                    for piece in response.iter_content(65536):
                        with self.lock:self.network_bytes+=len(piece)
                        blob.extend(piece)
                        if len(blob)>limit:raise ValueError('Response exceeds object bound')
                        if time.monotonic()-begin>110:raise TimeoutError('Object wall deadline')
                    headers={k:response.headers.get(k) for k in ['ETag','Last-Modified','Content-Length']}
                break
            except (requests.Timeout,requests.ConnectionError):
                if attempt:raise
                time.sleep(1)
        rec={'key':key,'url':self.url+'/'+key,'bytes':len(blob),'sha256':hashlib.sha256(blob).hexdigest(),'seconds':time.monotonic()-begin,'retrieved_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'headers':headers}
        temp=Path(str(path)+'.partial');temp.write_bytes(blob);os.replace(temp,path);write_json(receipt,rec)
        with self.lock:self.records.append(rec)
        return bytes(blob)

def mapping(study_path,source):
    study,members,evidence=study_inputs(study_path);cells=members[5];lat=source.coord('latitude');lon=source.coord('longitude');zi=surface_index(source.coord('elevation'))
    west,south,east,north=study['domain']['bbox_wgs84'];yi=np.flatnonzero((lat>=south)&(lat<=north));xi=np.flatnonzero((lon>=west)&(lon<=east));mask=source.field('bathy','mask',None,zi,yi,xi)
    water=gpd.read_parquet((Path(study_path).resolve().parent/study['grid_registry']['mask_relative_path']).resolve())
    if water.crs.to_epsg()!=4326:raise ValueError('Water CRS mismatch')
    xx,yy=np.meshgrid(lon[xi],lat[yi]);ids=np.array([h3.latlng_to_cell(float(y),float(x),5) for y,x in zip(yy.ravel(),xx.ravel())]).reshape(xx.shape)
    inside=(mask==1)&shapely.intersects_xy(water.geometry.union_all(),xx,yy)&np.isin(ids,cells);y,x=np.where(inside)
    return cells,evidence,yi[y],xi[x],ids[inside],np.cos(np.deg2rad(yy[inside]))

def aggregate(day,cells,ids,weights,s,u,v):
    paired=np.isfinite(u)&np.isfinite(v);values={'salinity_psu':s,'current_east_m_s':np.where(paired,u,np.nan),'current_north_m_s':np.where(paired,v,np.nan),'current_daily_mean_vector_speed_m_s':np.where(paired,np.hypot(u,v),np.nan)}
    f=pd.DataFrame({'date':day,'h3_index':cells})
    for metric,a in values.items():
        good=np.isfinite(a);g=pd.DataFrame({'h3_index':ids[good],'value':a[good]*weights[good],'weight':weights[good]}).groupby('h3_index').sum();f[metric]=f.h3_index.map(g.value/g.weight)
    return f

def read_block(cache,meta,block,gy,gx):
    fields={v:np.full((2081,len(gy)),np.nan) for v in ['so','uo','vo']}
    for j,i in sorted(set(zip(gy//16,gx//16))):
        positions=np.flatnonzero((gy//16==j)&(gx//16==i))
        for v in fields:
            key=f'{v}/{block}.49.{j}.{i}';path=cache.root/key.replace('/','-');rec=json.loads(Path(str(path)+'.receipt.json').read_text())
            if sha(path)!=rec['sha256']:raise ValueError('Replay checksum mismatch')
            raw=decode_chunk(path.read_bytes(),meta[v+'/.zarray']);fields[v][:,positions]=unpack(raw[:,0,gy[positions]%16,gx[positions]%16],meta[v+'/.zarray'],meta[v+'/.zattrs'])
    return fields

def run(study,pilot,root,output,offline=False,promote=False):
    begin=time.monotonic();root=Path(root).resolve();root.mkdir(parents=True,exist_ok=True);output=Path(output).resolve()
    with (root/'run.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);guard(root)
        source=Source(pilot);item=source.item;url=item['assets']['geoChunked']['href'];cache=Cache(root/'chunks',url,offline)
        # Refresh metadata online on each acquisition; freeze exact snapshot before data requests.
        metadata_path=root/'geo-zmetadata.json'
        if not offline:
            s=requests.Session();s.trust_env=False;r=s.get(url+'/.zmetadata',timeout=(10,30));r.raise_for_status()
            if len(r.content)>200000:raise ValueError('Oversize metadata')
            cache.network_bytes+=len(r.content);cache.network_requests+=1
            if metadata_path.exists() and metadata_path.read_bytes()!=r.content:raise ValueError('Remote metadata changed')
            metadata_path.write_bytes(r.content)
        meta=json.loads(metadata_path.read_text())['metadata']
        for v in ['so','uo','vo']:
            if meta[v+'/.zarray']['chunks']!=[2081,1,16,16] or meta[v+'/.zattrs']!=source.meta['daily'][v+'/.zattrs']:raise ValueError('Variable/layout convention changed')
        # Verify complete coordinate arrays, not merely overlapping pilot values.
        for v in ['time','latitude','longitude','elevation']:
            spec=meta[v+'/.zarray'];arrays=[decode_chunk(cache.fetch(f'{v}/{i}'),spec) for i in range((spec['shape'][0]+spec['chunks'][0]-1)//spec['chunks'][0])]
            np.testing.assert_array_equal(np.concatenate(arrays)[:spec['shape'][0]],source.coord(v))
        cells,evidence,gy,gx,ids,weights=mapping(study,source);times=pd.to_datetime(source.coord('time'),unit='h',origin='1950-01-01');ti=np.flatnonzero((times>=pd.Timestamp('2009-01-01'))&(times<=pd.Timestamp('2026-09-22')))
        dates=[d.date() for d in times[ti]]
        if len(dates)!=6474 or list(pd.date_range(dates[0],dates[-1]).date)!=dates:raise ValueError('Unexpected daily coverage')
        tiles=sorted(set(zip(gy//16,gx//16)));blocks=sorted(set(ti//2081));keys=[f'{v}/{b}.49.{j}.{i}' for b in blocks for j,i in tiles for v in ['so','uo','vo']]
        if len(keys)!=204 or len(ids)!=625:raise ValueError('Study source mapping changed')
        plan={'dataset':DATASET,'metadata_sha256':sha(metadata_path),'study':evidence,'keys':keys,'dates':[str(dates[0]),str(dates[-1])],'regimes':REGIMES,'code_sha256':sha(__file__)}
        planpath=root/'plan.json'
        if planpath.exists() and json.loads(planpath.read_text())!=plan:raise ValueError('Frozen run plan mismatch')
        write_json(planpath,plan)
        acquisition=time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            for n,_ in enumerate(pool.map(cache.fetch,keys),1):
                if n%51==0:print(json.dumps({'acquired_verified':n,'total':len(keys),'network_bytes':cache.network_bytes}),flush=True);guard(root)
        acquisition=time.monotonic()-acquisition;write_json(root/'inventory.json',sorted(cache.records,key=lambda x:x['key']))
        destination=root/('validated-'+uuid.uuid4().hex);destination.mkdir();writers={};schemas={}
        for name,metrics in PRODUCTS.items():
            schema=pa.schema([('date',pa.date32()),('h3_index',pa.string())]+[(m,pa.float64()) for m in metrics]);schemas[name]=schema;writers[name]=pq.ParquetWriter(destination/(name+'-r5-daily.parquet'),schema,compression='zstd')
        processing=time.monotonic();pilot_frames={name:pq.read_table(output/(name+'-r5-daily.parquet'),filters=[('date','>=',datetime.date(2024,7,1)),('date','<=',datetime.date(2024,7,3))]).to_pandas() for name in PRODUCTS};pilot_matches=0
        try:
            for b in blocks:
                fields=read_block(cache,meta,b,gy,gx)
                for t in ti[ti//2081==b]:
                    day=times[t].date();f=aggregate(day,cells,ids,weights,*[fields[v][t%2081] for v in ['so','uo','vo']])
                    for name,metrics in PRODUCTS.items():
                        frame=f[['date','h3_index',*metrics]];validate(frame,metrics,[day],cells)
                        if datetime.date(2024,7,1)<=day<=datetime.date(2024,7,3):pd.testing.assert_frame_equal(frame.reset_index(drop=True),pilot_frames[name][pilot_frames[name].date==day].reset_index(drop=True),check_exact=True);pilot_matches+=1
                        writers[name].write_table(pa.Table.from_pandas(frame,schema=schemas[name],preserve_index=False))
                del fields;guard(root);print(json.dumps({'processed_time_block':int(b)}),flush=True)
        finally:
            for w in writers.values():w.close()
        if pilot_matches!=6:raise ValueError('Pilot parity incomplete')
        processing=time.monotonic()-processing;verification=time.monotonic();stats={}
        for name,metrics in PRODUCTS.items():
            path=destination/(name+'-r5-daily.parquet');pf=pq.ParquetFile(path)
            if pf.num_row_groups!=len(dates) or pf.metadata.num_rows!=len(dates)*len(cells) or pf.schema_arrow!=schemas[name]:raise ValueError('Whole-product schema/rowgroups mismatch')
            stat={m:dict(nonnull=0,null=0,minimum=float('inf'),maximum=-float('inf')) for m in metrics}
            for i,day in enumerate(dates):
                frame=pf.read_row_group(i).to_pandas();validate(frame,metrics,[day],cells)
                for m in metrics:
                    a=frame[m].dropna();stat[m]['nonnull']+=len(a);stat[m]['null']+=len(frame)-len(a)
                    if len(a):stat[m]['minimum']=min(stat[m]['minimum'],float(a.min()));stat[m]['maximum']=max(stat[m]['maximum'],float(a.max()))
            stats[name]=dict(path=path.name,sha256=sha(path),bytes=path.stat().st_size,row_count=pf.metadata.num_rows,statistics=stat)
        verification=time.monotonic()-verification
        report={'published':False,'stage':str(destination),'source_date_start':str(dates[0]),'source_date_end':str(dates[-1]),'days':len(dates),'cells':len(cells),'products':stats,'network_bytes':cache.network_bytes,'network_requests':cache.network_requests,'cache_reused_bytes':cache.reused_bytes,'cache_reused_objects':cache.reused_objects,'acquisition_seconds':acquisition,'processing_seconds':processing,'readback_seconds':verification,'elapsed_seconds':time.monotonic()-begin,'retained_bytes':size(root),'free_bytes':shutil.disk_usage(root).free,'regimes':REGIMES,'pilot_exact':True,'code_sha256':sha(__file__),'inventory_sha256':sha(root/'inventory.json')}
        write_json(root/'validated.json',report)
        if promote:promote_products(output,destination,report,root,evidence)
        return report

def promote_products(output,destination,report,root,evidence):
    anchors=json.loads((root/'anchor-validation.json').read_text());replay=json.loads((root/'wheel-replay-verification.json').read_text())
    if len(anchors['comparisons'])!=24 or not all(x['exact'] for x in anchors['comparisons']):raise ValueError('Historical source anchors unqualified')
    if replay['network_requests']!=0 or replay['product_sha256']!={k:v['sha256'] for k,v in report['products'].items()}:raise ValueError('Exact installed-wheel replay missing')
    work=output.parent.parent/'.marinecast-work'/'oceanography';work.mkdir(parents=True,exist_ok=True)
    with (work/'publication.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);recover(output,work);catalog=json.loads((output/'catalog.json').read_text());stage=work/('stage-'+uuid.uuid4().hex);stage.mkdir()
        if catalog['study']['study_sha256']!=evidence['study_sha256']:raise ValueError('Publication study mismatch')
        for product in catalog['products']:
            if sha(output/product['path'])!=product['sha256']:raise ValueError('Existing output changed')
        replaced=set()
        for product in catalog['products']:
            name=product['id']
            if name in PRODUCTS:
                p=report['products'][name];os.link(destination/p['path'],stage/p['path']);product.update({k:p[k] for k in ['sha256','row_count','statistics']});product.update(date_start=report['source_date_start'],date_end=report['source_date_end']);product['qualification']=copy.deepcopy(product['qualification']);product['qualification']['pilot_source_inventory']=product['qualification'].pop('source_inventory',[]);product['qualification'].update(source_inventory=json.loads((root/'inventory.json').read_text()),source_root=str(root),source_inventory_sha256=report['inventory_sha256'],code_sha256=report['code_sha256'],production_regimes=REGIMES,regime_evidence='QUID Issue 1.6 section V page 50: interim from July 2021; no later authoritative final reprocessing established',forcing_change_date='2019-01-01',source_history_report=str(root/'completed.json'));replaced.add(name)
            else:os.link(output/product['path'],stage/product['path'])
        if replaced!=set(PRODUCTS):raise ValueError('Expected existing GLORYS products missing')
        write_json(stage/'catalog.json',catalog)
        for product in catalog['products']:
            if sha(stage/product['path'])!=product['sha256']:raise ValueError('Staged publication checksum mismatch')
        guard(root);publish(stage,output,work);report['published']=True;report['catalog']=str(output/'catalog.json');report['retained_bytes']=size(root);write_json(root/'completed.json',report)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for k in ['study','pilot','root','output']:parser.add_argument('--'+k,required=True)
    parser.add_argument('--offline',action='store_true');parser.add_argument('--publish',action='store_true');a=parser.parse_args();print(json.dumps(run(a.study,a.pilot,a.root,a.output,a.offline,a.publish),indent=2))
if __name__=='__main__':main()
