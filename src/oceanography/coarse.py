"""Qualified HYCOM surface subsets. Source-specific pilot, no implicit mosaics."""
from __future__ import annotations
import argparse
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import shutil
import uuid
import geopandas as gpd
import h3
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests
import shapely
import xarray as xr
from .daily import Cache, sha, write_json, study_inputs, recover, publish

BASE='https://ncss.hycom.org/thredds/ncss/grid/GLBy0.08/expt_93.0'
SPECS={'salinity':('psu','sea_water_salinity'), 'water_u':('m/s','eastward_sea_water_velocity'),'water_v':('m/s','northward_sea_water_velocity')}
PRODUCTS={'hycom-salinity':['salinity_psu'], 'hycom-currents':['current_east_m_s','current_north_m_s','current_speed_m_s']}

def subset_url(group,start,end,bbox):
    if start.year!=end.year: raise ValueError('Subset must stay in one source year')
    west,south,east,north=bbox
    variables=['salinity'] if group=='ts3z' else ['water_u','water_v']
    params=[('var',v) for v in variables]+list(dict(north=north,south=south,west=west,east=east,horizStride=1,time_start=f'{start}T00:00:00Z',time_end=f'{end}T21:00:00Z',timeStride=1,vertCoord=0,accept='netcdf4').items())
    return requests.Request('GET',f'{BASE}/{group}/{start.year}',params=params).prepare().url

def request_sources(cache,start,end,bbox):
    if start!=end and not cache.offline:
        raise ValueError('HYCOM NCSS permits at most one day per network request')
    # Deliberately sequential: at most one NCSS connection per IP.
    return [cache.get(subset_url(group,start,end,bbox),'.nc') for group in ['ts3z','uv3z']]


def qualify(ds,variables,start,end,bbox):
    expected=pd.date_range(str(start),str(end)+'T21:00:00',freq='3h')
    if not pd.DatetimeIndex(ds.time.values).equals(expected): raise ValueError('Incomplete/unexpected native time axis')
    if ds.depth.size!=1 or float(ds.depth.values[0])!=0 or ds.depth.attrs.get('units')!='m' or ds.depth.attrs.get('positive')!='down': raise ValueError('Surface depth contract mismatch')
    for v in variables:
        a=ds[v]
        if a.dims!=('time','depth','lat','lon') or (a.attrs.get('units'),a.attrs.get('standard_name'))!=SPECS[v]: raise ValueError('Variable dimensions/units/orientation mismatch: '+v)
    lat=np.asarray(ds.lat.values,float);lon=(np.asarray(ds.lon.values,float)+180)%360-180
    if len(lat)<2 or len(lon)<2 or not np.allclose(np.diff(lat),.04,atol=1e-4) or not np.allclose(np.diff(lon),.08,atol=1e-4): raise ValueError('Unexpected native spacing')
    west,south,east,north=bbox
    if max(abs(lon[0]-west),abs(lon[-1]-east))>.081 or max(abs(lat[0]-south),abs(lat[-1]-north))>.041: raise ValueError('Unexpected regional bounds')
    return lat,lon

def daily_samples(salinity,u,v):
    """All eight samples required per native point; shared vector support."""
    if salinity.shape!=u.shape or u.shape!=v.shape or u.shape[0]!=8: raise ValueError('Expected aligned eight-sample arrays')
    sg=np.isfinite(salinity).all(axis=0)&((salinity>=0)&(salinity<=50)).all(axis=0)
    vg=np.isfinite(u).all(axis=0)&np.isfinite(v).all(axis=0)&(np.abs(u)<=10).all(axis=0)&(np.abs(v)<=10).all(axis=0)
    return {'salinity_psu':np.where(sg,salinity.mean(axis=0),np.nan),'current_east_m_s':np.where(vg,u.mean(axis=0),np.nan),'current_north_m_s':np.where(vg,v.mean(axis=0),np.nan),'current_speed_m_s':np.where(vg,np.hypot(u,v).mean(axis=0),np.nan)}

def validate(frame,metrics,dates,cells):
    if list(frame.columns)!=['date','h3_index',*metrics]: raise ValueError('Public schema mismatch')
    expected=pd.MultiIndex.from_product([dates,cells],names=['date','h3_index'])
    if not pd.MultiIndex.from_frame(frame[['date','h3_index']]).equals(expected): raise ValueError('Identity/order/membership mismatch')
    for m in metrics:
        values=frame[m].dropna()
        lo,hi=(0,50) if m=='salinity_psu' else ((0,15) if m=='current_speed_m_s' else (-10,10))
        if not np.isfinite(values).all() or not values.between(lo,hi).all(): raise ValueError('Metric range mismatch')
    if 'current_speed_m_s' in metrics:
        if not frame[metrics].isna().nunique(axis=1).eq(1).all(): raise ValueError('Inconsistent vector support')
        good=frame.dropna()
        if (np.hypot(good.current_east_m_s,good.current_north_m_s)>good.current_speed_m_s+1e-7).any(): raise ValueError('Speed violates vector inequality')

def aggregate(salinity_path,uv_path,start,end,cells,bbox,water):
    dates=[d.date() for d in pd.date_range(start,end)]
    frames=[]
    with xr.open_dataset(salinity_path) as sd,xr.open_dataset(uv_path) as ud:
        lat,lon=qualify(sd,['salinity'],start,end,bbox)
        ulat,ulon=qualify(ud,['water_u','water_v'],start,end,bbox)
        if not np.array_equal(lat,ulat) or not np.array_equal(lon,ulon): raise ValueError('Unaligned scalar/vector grid')
        xx,yy=np.meshgrid(lon,lat)
        ids=np.array([h3.latlng_to_cell(y,x,5) for y,x in zip(yy.ravel(),xx.ravel())])
        inside=shapely.intersects_xy(water,xx.ravel(),yy.ravel())&np.isin(ids,cells)
        weights=np.cos(np.deg2rad(yy.ravel()))
        for i,day in enumerate(dates):
            values=daily_samples(sd.salinity.isel(time=slice(i*8,(i+1)*8),depth=0).values.astype(float),ud.water_u.isel(time=slice(i*8,(i+1)*8),depth=0).values.astype(float),ud.water_v.isel(time=slice(i*8,(i+1)*8),depth=0).values.astype(float))
            frame=pd.DataFrame({'date':day,'h3_index':cells})
            for metric,arr in values.items():
                flat=arr.ravel();good=inside&np.isfinite(flat)
                points=pd.DataFrame({'h3_index':ids[good],'weighted':flat[good]*weights[good],'weight':weights[good]})
                sums=points.groupby('h3_index')[['weighted','weight']].sum()
                frame[metric]=frame.h3_index.map(sums.weighted/sums.weight)
            frames.append(frame)
    allrows=pd.concat(frames,ignore_index=True)
    result={key:allrows[['date','h3_index',*metrics]] for key,metrics in PRODUCTS.items()}
    for key,frame in result.items(): validate(frame,PRODUCTS[key],dates,cells)
    return result,{'grid_shape':[len(lat),len(lon)],'native_centres_inside_water_and_membership':int(inside.sum()),'surface_depth_m':0,'timestamps_per_day':8}

def stage_products(output,work,frames,metadata,dates,cells):
    """Keep every existing delivery file unchanged; caller holds publication lock."""
    catalog_path=output/'catalog.json'
    catalog=json.loads(catalog_path.read_text())
    if catalog['study']['study_sha256']!=metadata['study']['study_sha256']: raise ValueError('Existing publication has different study')
    stage=work/('stage-'+uuid.uuid4().hex);stage.mkdir()
    for p in output.iterdir():
        if not p.is_file() or p.is_symlink(): raise ValueError('Unexpected delivery entry')
        if p.name!='catalog.json': os.link(p,stage/p.name)
    for product in catalog['products']:
        if sha(stage/product['path'])!=product['sha256']: raise ValueError('Existing publication checksum failure')
    for key,frame in frames.items():
        metrics=PRODUCTS[key];filename=key+'-r5-daily.parquet'
        if (stage/filename).exists(): raise ValueError('Existing HYCOM product requires explicit history-preserving update')
        schema=pa.schema([('date',pa.date32()),('h3_index',pa.string())]+[(m,pa.float64()) for m in metrics])
        with pq.ParquetWriter(stage/filename,schema,compression='zstd') as writer:
            for day in dates: writer.write_table(pa.Table.from_pandas(frame[frame.date==day],schema=schema,preserve_index=False))
        validate(pq.read_table(stage/filename).to_pandas(),metrics,dates,cells)
        stats={m:{'nonnull':int(frame[m].notna().sum()),'null':int(frame[m].isna().sum()),'minimum':None if frame[m].dropna().empty else float(frame[m].min()),'maximum':None if frame[m].dropna().empty else float(frame[m].max())} for m in metrics}
        catalog['products'].append(dict(id=key,path=filename,sha256=sha(stage/filename),columns=['date','h3_index',*metrics],metrics=metrics,metric=metrics[0],units='psu' if key.endswith('salinity') else 'm/s',h3_resolution=5,row_count=len(frame),date_start=str(dates[0]),date_end=str(dates[-1]),source_dataset='HYCOM GLBy0.08/expt_93.0',source_url='https://www.hycom.org/dataserver/gofs-3pt1/analysis',description='HYCOM modeled surface conditions; complete eight 3-hourly samples, native wet centres within study water mask, no fill. Speed is mean of sample magnitudes.',statistics=stats,qualification=metadata))
    write_json(stage/'catalog.json',catalog)
    return stage,catalog

def run(study_path,output,cache_root,start,end,offline=False,promote=False):
    start=dt.date.fromisoformat(start);end=dt.date.fromisoformat(end)
    if not 1<=(end-start).days+1<=31 or start<dt.date(2018,12,4) or end>dt.date(2024,9,4): raise ValueError('Require bounded qualified GOFS93 period')
    study,members,evidence=study_inputs(study_path);cells=members[5];bbox=study['domain']['bbox_wgs84']
    if shutil.disk_usage(Path(cache_root).parent).free<10_000_000_000: raise ValueError('Free disk below 10GB floor')
    cache=Cache(cache_root,offline)
    mask=(Path(study_path).resolve().parent/study['grid_registry']['mask_relative_path']).resolve()
    waterframe=gpd.read_parquet(mask)
    if waterframe.crs.to_epsg()!=4326: raise ValueError('Water mask CRS mismatch')
    water=waterframe.geometry.union_all()
    # Historical pilot receipts remain replayable offline. New network requests
    # obey HYCOM's <=1 day/request and one NCSS connection/IP policy.
    windows=[(start,end)] if offline else [(d.date(),d.date()) for d in pd.date_range(start,end)]
    batches=[];diagnostics={}
    for first,last in windows:
        paths=request_sources(cache,first,last,bbox)
        batch,diag=aggregate(*paths,first,last,cells,bbox,water)
        batches.append(batch);diagnostics[str(first)]=diag
    frames={key:pd.concat([b[key] for b in batches],ignore_index=True) for key in PRODUCTS}
    metadata=dict(study=evidence,source_receipts=cache.receipts,code_sha256=sha(__file__),diagnostics=diagnostics,date_basis='UTC day; eight 3-hourly model samples',method='Complete native sample mean then cosine-latitude weighted native centres within approved water geometry and same R5 cell; no filling',salinity_definition='Source-reported psu, not reference salinity g/kg',downloaded_bytes=cache.downloaded)
    dates=[d.date() for d in pd.date_range(start,end)]
    output=Path(output).resolve();work=output.parent.parent/'.marinecast-work'/'oceanography';work.mkdir(parents=True,exist_ok=True)
    with (work/'publication.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);recover(output,work)
        stage,catalog=stage_products(output,work,frames,metadata,dates,cells)
        if promote: publish(stage,output,work)
        result={'published':promote,'stage':str(stage),'products':catalog['products'][-2:],'diagnostics':diagnostics}
        write_json(Path(cache_root)/'completed.json',result)
        return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['study','output','cache','start','end']:p.add_argument('--'+name,required=True)
    p.add_argument('--offline',action='store_true');p.add_argument('--publish',action='store_true')
    a=p.parse_args();print(json.dumps(run(a.study,a.output,a.cache,a.start,a.end,a.offline,a.publish),indent=2))
if __name__=='__main__':main()
