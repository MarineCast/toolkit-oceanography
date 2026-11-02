"""Source-separated SalishSeaCast surface pilot with geographic vectors."""
from __future__ import annotations
import argparse,datetime as dt,fcntl,json,os,uuid
from pathlib import Path
import geopandas as gpd
import h3
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pyproj import Geod
import shapely
import xarray as xr
from .daily import sha,write_json,study_inputs,recover,publish

PRODUCTS={'salishsea-salinity':['reference_salinity_g_kg'],'salishsea-currents':['current_east_m_s','current_north_m_s','current_speed_m_s']}
SPECS={'salinity':('salinity','g kg-1','sea_water_reference_salinity'),'u':('uVelocity','m s-1','sea_water_x_velocity'),'v':('vVelocity','m s-1','sea_water_y_velocity')}

def read_source(root,name):
    p=root/(name+'.nc');receipt=json.loads((root/(name+'.json')).read_text())
    if sha(p)!=receipt['sha256']:raise ValueError('Source checksum mismatch')
    return p,receipt

def rotation(lon,lat):
    """Geographic angle at midpoint between the bounding U faces, radians."""
    geod=Geod(a=6371000,b=6371000)
    az,_,distance=geod.inv(lon[1:,:-1],lat[1:,:-1],lon[1:,1:],lat[1:,1:])
    _,_,back=geod.fwd(lon[1:,:-1],lat[1:,:-1],az,distance/2)
    angle=np.deg2rad((90-(back+180)+180)%360-180)
    if not np.isfinite(angle).all() or (distance<=0).any():raise ValueError('Degenerate coordinate grid')
    return angle

def collocate_rotate(u,v,angle):
    if u.shape!=v.shape or u.shape[-2:]!=(angle.shape[0]+1,angle.shape[1]+1):raise ValueError('Vector grid shape mismatch')
    uc=(u[...,1:,:-1]+u[...,1:,1:])/2
    vc=(v[...,:-1,1:]+v[...,1:,1:])/2
    return uc*np.cos(angle)-vc*np.sin(angle),uc*np.sin(angle)+vc*np.cos(angle)

def read_day(path,kind,day):
    var,units,standard=SPECS[kind]
    with xr.open_dataset(path) as d:
        expected=pd.date_range(str(day)+'T00:30:00',periods=24,freq='h')
        if not pd.DatetimeIndex(d.time.values).equals(expected):raise ValueError('Incomplete hourly UTC intervals')
        if d.depth.size!=1 or abs(float(d.depth.values[0])-.5000003)>1e-6 or d.depth.attrs.get('positive')!='down' or d.depth.attrs.get('units')!='m':raise ValueError('Regional top-depth mismatch')
        a=d[var]
        if a.dims!=('time','depth','gridY','gridX') or (a.attrs.get('units'),a.attrs.get('standard_name'))!=(units,standard):raise ValueError('Regional variable contract mismatch')
        if d.sizes['gridY']!=898 or d.sizes['gridX']!=398 or not np.array_equal(d.gridY.values,np.arange(898)) or not np.array_equal(d.gridX.values,np.arange(398)):raise ValueError('Regional index grid mismatch')
        return a.isel(depth=0).values.astype(float)

def validate(frame,metrics,dates,cells):
    if list(frame.columns)!=['date','h3_index',*metrics] or not pd.MultiIndex.from_frame(frame[['date','h3_index']]).equals(pd.MultiIndex.from_product([dates,cells],names=['date','h3_index'])):raise ValueError('Regional schema/identity mismatch')
    for m in metrics:
        v=frame[m].dropna();lo,hi=(0,50) if m=='reference_salinity_g_kg' else ((0,15) if m.endswith('speed_m_s') else (-10,10))
        if not np.isfinite(v).all() or not v.between(lo,hi).all():raise ValueError('Regional metric range mismatch')
    if 'current_speed_m_s' in metrics:
        if not frame[metrics].isna().nunique(axis=1).eq(1).all():raise ValueError('Regional vector support mismatch')
        f=frame.dropna()
        if (np.hypot(f.current_east_m_s,f.current_north_m_s)>f.current_speed_m_s+1e-7).any():raise ValueError('Regional vector inequality')

def calculate(study_path,root,start,end):
    study,members,evidence=study_inputs(study_path);cells=members[6];dates=[d.date() for d in pd.date_range(start,end)]
    if not 1<=len(dates)<=3:raise ValueError('Regional pilot limited to three days')
    gp,gr=read_source(root,'geometry');cp,cr=read_source(root,'coordinates');receipts=[gr,cr]
    mask_path=(Path(study_path).resolve().parent/study['grid_registry']['mask_relative_path']).resolve();mask=gpd.read_parquet(mask_path)
    if mask.crs.to_epsg()!=4326:raise ValueError('Study CRS mismatch')
    water=mask.geometry.union_all()
    with xr.open_dataset(gp) as g,xr.open_dataset(cp,decode_times=False) as c:
        lon=g.longitude.values;lat=g.latitude.values
        if not np.array_equal(c.glamt.values.squeeze().astype('float32'),lon.astype('float32')) or not np.array_equal(c.gphit.values.squeeze().astype('float32'),lat.astype('float32')):raise ValueError('Coordinates do not match regional tracer grid')
        angle=rotation(c.glamu.values.squeeze(),c.gphiu.values.squeeze())
        weight=(c.e1t.values.squeeze()*c.e2t.values.squeeze())[1:,1:].ravel()
        wet=(g.bathymetry.values[1:,1:]>0).ravel();xx=lon[1:,1:].ravel();yy=lat[1:,1:].ravel()
        ids=np.array([h3.latlng_to_cell(float(y),float(x),6) for y,x in zip(yy,xx)])
        inside=wet&shapely.intersects_xy(water,xx,yy)&np.isin(ids,cells)&np.isfinite(weight)&(weight>0)
    frames=[]
    for day in dates:
        arrays={}
        for kind in SPECS:
            p,r=read_source(root,kind+'-'+str(day));receipts.append(r);arrays[kind]=read_day(p,kind,day)
        scalar=arrays['salinity'][:,1:,1:];u,v=collocate_rotate(arrays['u'],arrays['v'],angle)
        sg=np.isfinite(scalar).all(axis=0)&((scalar>=0)&(scalar<=50)).all(axis=0)
        vg=np.isfinite(u).all(axis=0)&np.isfinite(v).all(axis=0)&(np.abs(u)<=10).all(axis=0)&(np.abs(v)<=10).all(axis=0)
        values={'reference_salinity_g_kg':np.where(sg,scalar.mean(axis=0),np.nan),'current_east_m_s':np.where(vg,u.mean(axis=0),np.nan),'current_north_m_s':np.where(vg,v.mean(axis=0),np.nan),'current_speed_m_s':np.where(vg,np.hypot(u,v).mean(axis=0),np.nan)}
        frame=pd.DataFrame({'date':day,'h3_index':cells})
        for m,arr in values.items():
            a=arr.ravel();good=inside&np.isfinite(a);p=pd.DataFrame({'h3_index':ids[good],'weighted':a[good]*weight[good],'weight':weight[good]});s=p.groupby('h3_index')[['weighted','weight']].sum();frame[m]=frame.h3_index.map(s.weighted/s.weight)
        frames.append(frame)
        del arrays,scalar,u,v,values
    full=pd.concat(frames,ignore_index=True);products={name:full[['date','h3_index',*metrics]] for name,metrics in PRODUCTS.items()}
    for name,f in products.items():validate(f,PRODUCTS[name],dates,cells)
    qualification=dict(study=evidence,source_receipts=receipts,code_sha256=sha(__file__),surface_depth_m=.5000003,native_wet_centres_inside_water=int(inside.sum()),date_basis='24 complete hourly mean intervals, UTC midnight to midnight; native labels at half-hour',method='C-grid face averages to tracer centres; local U-coordinate midpoint bearing rotation to geographic vectors; native e1t*e2t area weights within study water mask and same R6 cell; no fill',salinity_definition='Reference salinity g/kg; not HYCOM practical salinity psu',speed_definition='Mean magnitude of collocated hourly-mean vectors; not instantaneous mean speed',mosaic='None; source-separated pilot')
    return products,qualification,dates,cells

def run(study,root,output,start,end,promote=False):
    frames,qual,dates,cells=calculate(study,Path(root),start,end)
    output=Path(output).resolve();work=output.parent.parent/'.marinecast-work'/'oceanography';work.mkdir(parents=True,exist_ok=True)
    with (work/'publication.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);recover(output,work)
        catalog=json.loads((output/'catalog.json').read_text())
        if catalog['study']['study_sha256']!=qual['study']['study_sha256']:raise ValueError('Study mismatch at publication')
        stage=work/('stage-'+uuid.uuid4().hex);stage.mkdir()
        for p in output.iterdir():
            if not p.is_file() or p.is_symlink():raise ValueError('Unexpected delivery entry')
            if p.name!='catalog.json':os.link(p,stage/p.name)
        for p in catalog['products']:
            if sha(stage/p['path'])!=p['sha256']:raise ValueError('Existing delivery checksum mismatch')
        added=[]
        for name,frame in frames.items():
            metrics=PRODUCTS[name];filename=name+'-r6-daily.parquet'
            if (stage/filename).exists():raise ValueError('Existing regional product requires explicit preserving update')
            schema=pa.schema([('date',pa.date32()),('h3_index',pa.string())]+[(m,pa.float64()) for m in metrics])
            with pq.ParquetWriter(stage/filename,schema,compression='zstd') as writer:
                for day in dates:writer.write_table(pa.Table.from_pandas(frame[frame.date==day],schema=schema,preserve_index=False))
            validate(pq.read_table(stage/filename).to_pandas(),metrics,dates,cells)
            stats={m:dict(nonnull=int(frame[m].notna().sum()),null=int(frame[m].isna().sum()),minimum=None if frame[m].dropna().empty else float(frame[m].min()),maximum=None if frame[m].dropna().empty else float(frame[m].max())) for m in metrics}
            product=dict(id=name,path=filename,sha256=sha(stage/filename),columns=['date','h3_index',*metrics],metric=metrics[0],metrics=metrics,units='g kg-1' if name.endswith('salinity') else 'm/s',h3_resolution=6,row_count=len(frame),date_start=str(dates[0]),date_end=str(dates[-1]),source_dataset='SalishSeaCast v21-11',source_url='https://salishsea.eos.ubc.ca/erddap/',description='Source-separated regional model surface pilot; reference salinity and rotated geographic hourly-mean currents. No HYCOM mosaic.',statistics=stats,qualification=qual)
            catalog['products'].append(product);added.append(product)
        write_json(stage/'catalog.json',catalog)
        if promote:publish(stage,output,work)
        result=dict(published=promote,stage=str(stage),products=added);write_json(Path(root)/'completed.json',result);return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['study','root','output','start','end']:p.add_argument('--'+name,required=True)
    p.add_argument('--publish',action='store_true');a=p.parse_args();print(json.dumps(run(a.study,a.root,a.output,a.start,a.end,a.publish),indent=2))
if __name__=='__main__':main()
