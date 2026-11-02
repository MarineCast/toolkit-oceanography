"""Offline, checksummed GLORYS12 surface pilot from official public ARCO chunks."""
from __future__ import annotations
import argparse,fcntl,json,os,time,uuid
from pathlib import Path
import geopandas as gpd,h3,numpy as np,pandas as pd,pyarrow as pa,pyarrow.parquet as pq,shapely
import numcodecs
from .daily import sha,write_json,study_inputs,recover,publish
PRODUCTS={'glorys12-salinity':['salinity_psu'],'glorys12-currents':['current_east_m_s','current_north_m_s','current_daily_mean_vector_speed_m_s']}
DATASET='cmems_mod_glo_phy_my_0.083deg_P1D-m_202311'

def decode_chunk(blob,spec):
    if spec['zarr_format']!=2 or spec['order']!='C' or spec.get('filters') is not None:raise ValueError('Unsupported Zarr encoding')
    count=int(np.prod(spec['chunks']));dtype=np.dtype(spec['dtype'])
    if count*dtype.itemsize>3_000_000:raise ValueError('Decoded chunk exceeds bound')
    decoded=numcodecs.get_codec(spec['compressor']).decode(blob)
    if len(decoded)!=count*dtype.itemsize:raise ValueError('Chunk shape mismatch')
    return np.frombuffer(decoded,dtype=dtype).reshape(spec['chunks'])

def unpack(packed,spec,attrs):
    valid=np.ones(packed.shape,bool) if spec['fill_value'] is None else packed!=spec['fill_value']
    return np.where(valid,packed.astype(float)*attrs.get('scale_factor',1)+attrs.get('add_offset',0),np.nan)

def surface_index(elevation):
    if len(elevation)!=50 or not np.all(np.diff(elevation)>0) or not np.all(elevation<0):raise ValueError('ARCO elevation convention changed')
    i=int(np.argmin(abs(elevation)))
    if abs(float(elevation[i])+.494024992)>1e-6:raise ValueError('Unexpected shallowest depth')
    return i

class Source:
    def __init__(self,root):
        self.root=Path(root);self.inventory=json.loads((self.root/'inventory.json').read_text())
        for rec in self.inventory:
            path=self.root/rec['path']
            if path.stat().st_size!=rec['bytes'] or sha(path)!=rec['sha256']:raise ValueError('Source inventory mismatch: '+rec['path'])
        self.meta={family:json.loads((self.root/(family+'-zmetadata.json')).read_text())['metadata'] for family in ['daily','bathy']}
        self.item=json.loads((self.root/'daily.json').read_text())
        if self.item['id']!=DATASET:raise ValueError('Dataset/version mismatch')
    def coord(self,var):
        spec=self.meta['daily'][var+'/.zarray'];arrays=[]
        for i in range((spec['shape'][0]+spec['chunks'][0]-1)//spec['chunks'][0]):arrays.append(decode_chunk((self.root/(var+'-'+str(i)+'.chunk')).read_bytes(),spec))
        return np.concatenate(arrays)[:spec['shape'][0]]
    def field(self,family,var,ti,zi,yi,xi):
        spec=self.meta[family][var+'/.zarray'];attrs=self.meta[family][var+'/.zattrs'];expected=[1,512,2048] if ti is None else [1,1,512,2048]
        if spec['chunks']!=expected:raise ValueError('Source chunk layout changed')
        if not np.all(xi<2048):raise ValueError('Study crosses unqualified longitude chunk')
        a=np.empty((len(yi),len(xi)))
        for cy in sorted(set(yi//512)):
            indices=[zi,int(cy),0] if ti is None else [ti,zi,int(cy),0];key='.'.join(map(str,indices));raw=decode_chunk((self.root/(family+'-'+var+'-'+key+'.chunk')).read_bytes(),spec).reshape(512,2048);pos=np.flatnonzero(yi//512==cy);a[pos]=unpack(raw[np.ix_(yi[pos]%512,xi)],spec,attrs)
        return a

def validate(frame,metrics,dates,cells):
    if list(frame.columns)!=['date','h3_index',*metrics] or not pd.MultiIndex.from_frame(frame[['date','h3_index']]).equals(pd.MultiIndex.from_product([dates,cells],names=['date','h3_index'])):raise ValueError('GLORYS identity/schema mismatch')
    for metric in metrics:
        values=frame[metric].dropna();low,high=(0,50) if metric=='salinity_psu' else ((0,15) if 'speed' in metric else (-10,10))
        if not np.isfinite(values).all() or not values.between(low,high).all():raise ValueError('GLORYS physical range mismatch')
    if len(metrics)==3:
        if not frame[metrics].isna().nunique(axis=1).eq(1).all():raise ValueError('Vector missingness mismatch')
        f=frame.dropna()
        if (np.hypot(f[metrics[0]],f[metrics[1]])>f[metrics[2]]+1e-10).any():raise ValueError('Daily vector inequality violated')

def calculate(study_path,root):
    begin=time.monotonic();source=Source(root);study,members,evidence=study_inputs(study_path);cells=members[5];lat=source.coord('latitude');lon=source.coord('longitude');elev=source.coord('elevation');zi=surface_index(elev)
    attrs=source.meta['daily']['time/.zattrs']
    if attrs.get('calendar')!='gregorian' or attrs.get('units')!='hours since 1950-01-01':raise ValueError('Calendar/time units changed')
    times=pd.to_datetime(source.coord('time'),unit='h',origin='1950-01-01')
    if not times.is_unique or not times.is_monotonic_increasing or not np.all(np.diff(times.values)==np.timedelta64(1,'D')):raise ValueError('Invalid daily source time axis')
    for v,unit,std in [('so','1e-3','sea_water_salinity'),('uo','m s-1','eastward_sea_water_velocity'),('vo','m s-1','northward_sea_water_velocity')]:
        a=source.meta['daily'][v+'/.zattrs']
        if a['units']!=unit or a['standard_name']!=std or a['_ARRAY_DIMENSIONS']!=['time','elevation','latitude','longitude']:raise ValueError('Variable convention changed')
    if source.meta['daily']['so/.zattrs'].get('unit_long')!='Practical Salinity Unit':raise ValueError('Salinity definition changed')
    west,south,east,north=study['domain']['bbox_wgs84'];yi=np.flatnonzero((lat>=south)&(lat<=north));xi=np.flatnonzero((lon>=west)&(lon<=east));mask=source.field('bathy','mask',None,zi,yi,xi)
    if not np.isin(mask,[0,1]).all():raise ValueError('Nonbinary source wet mask')
    water=gpd.read_parquet((Path(study_path).resolve().parent/study['grid_registry']['mask_relative_path']).resolve())
    if water.crs.to_epsg()!=4326:raise ValueError('Study mask CRS mismatch')
    xx,yy=np.meshgrid(lon[xi],lat[yi]);ids=np.array([h3.latlng_to_cell(float(y),float(x),5) for y,x in zip(yy.ravel(),xx.ravel())]);inside=(mask.ravel()==1)&shapely.intersects_xy(water.geometry.union_all(),xx.ravel(),yy.ravel())&np.isin(ids,cells);weights=np.cos(np.deg2rad(yy.ravel()))
    dates=[d.date() for d in pd.date_range('2024-07-01','2024-07-03')];frames=[]
    for day in dates:
        matches=np.flatnonzero(times==pd.Timestamp(day))
        if len(matches)!=1:raise ValueError('Missing/duplicate pilot date')
        ti=int(matches[0]);s=source.field('daily','so',ti,zi,yi,xi);u=source.field('daily','uo',ti,zi,yi,xi);v=source.field('daily','vo',ti,zi,yi,xi);paired=np.isfinite(u)&np.isfinite(v)
        values={'salinity_psu':s,'current_east_m_s':np.where(paired,u,np.nan),'current_north_m_s':np.where(paired,v,np.nan),'current_daily_mean_vector_speed_m_s':np.where(paired,np.hypot(u,v),np.nan)};f=pd.DataFrame({'date':day,'h3_index':cells})
        for metric,a in values.items():
            a=a.ravel();good=inside&np.isfinite(a);z=pd.DataFrame({'h3_index':ids[good],'value':a[good]*weights[good],'weight':weights[good]}).groupby('h3_index').sum();f[metric]=f.h3_index.map(z.value/z.weight)
        frames.append(f)
    full=pd.concat(frames,ignore_index=True);products={name:full[['date','h3_index',*metrics]] for name,metrics in PRODUCTS.items()}
    for name,frame in products.items():validate(frame,PRODUCTS[name],dates,cells)
    qualification=dict(study=evidence,source_inventory=source.inventory,source_root=str(Path(root).resolve()),code_sha256=sha(__file__),source_dataset_version=DATASET,source_surface_depth_m=abs(float(elev[zi])),arco_elevation=float(elev[zi]),source_elevation_index=zi,elevation_caveat='Negative ARCO elevations with inherited positive=down attribute; physical depth verified against official manual',native_grid_degrees=1/12,date_basis='ARCO midnight calendar-day label; official daily mean midnight-to-midnight centred at noon',speed_definition='Spatially weighted native magnitudes of daily-mean geographic vectors, not mean hourly speed',salinity_definition='Practical salinity; provider unit 1e-3 and unit_long Practical Salinity Unit',tidal_constituents_included=False,spatial_method='Valid native wet centres inside reporting water and same R5 cell; cos(latitude) weights; no fill',wet_centres_inside_study=int(inside.sum()),authentication='Anonymous official STAC-linked Zarr data assets; no credentials',forecast_eligible=False,issue_date=None,processing_seconds=time.monotonic()-begin,source_time_start=str(times[0]),source_time_end=str(times[-1]),manual_url='https://documentation.marine.copernicus.eu/PUM/CMEMS-GLO-PUM-001-030.pdf',attribution='E.U. Copernicus Marine Service Information; DOI 10.48670/moi-00021')
    return products,qualification,dates,cells

def run(study,root,output,promote=False):
    products,qual,dates,cells=calculate(study,root);output=Path(output).resolve();work=output.parent.parent/'.marinecast-work'/'oceanography';work.mkdir(parents=True,exist_ok=True)
    with (work/'publication.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);recover(output,work);catalog=json.loads((output/'catalog.json').read_text())
        if catalog['study']['study_sha256']!=qual['study']['study_sha256']:raise ValueError('Publication study mismatch')
        stage=work/('stage-'+uuid.uuid4().hex);stage.mkdir()
        for p in output.iterdir():
            if not p.is_file() or p.is_symlink():raise ValueError('Unexpected output entry')
            if p.name!='catalog.json':os.link(p,stage/p.name)
        for p in catalog['products']:
            if sha(stage/p['path'])!=p['sha256']:raise ValueError('Existing output checksum mismatch')
        added=[]
        for name,frame in products.items():
            filename=name+'-r5-daily.parquet';metrics=PRODUCTS[name]
            if (stage/filename).exists():raise ValueError('Existing GLORYS product requires explicit preserving update')
            schema=pa.schema([('date',pa.date32()),('h3_index',pa.string())]+[(m,pa.float64()) for m in metrics])
            with pq.ParquetWriter(stage/filename,schema,compression='zstd') as writer:
                for day in dates:writer.write_table(pa.Table.from_pandas(frame[frame.date==day],schema=schema,preserve_index=False))
            readback=pq.read_table(stage/filename).to_pandas();pd.testing.assert_frame_equal(frame,readback,check_exact=True);validate(readback,metrics,dates,cells)
            stats={m:dict(nonnull=int(frame[m].notna().sum()),null=int(frame[m].isna().sum()),minimum=float(frame[m].min()),maximum=float(frame[m].max())) for m in metrics}
            product=dict(id=name,path=filename,sha256=sha(stage/filename),columns=list(frame.columns),metric=metrics[0],metrics=metrics,units='psu' if len(metrics)==1 else 'm/s',h3_resolution=5,row_count=len(frame),date_start=str(dates[0]),date_end=str(dates[-1]),source_dataset=DATASET,source_url='https://data.marine.copernicus.eu/product/GLOBAL_MULTIYEAR_PHY_001_030',description='GLORYS12 daily surface reanalysis; no tidal constituents; native wet support only.',statistics=stats,qualification=qual);catalog['products'].append(product);added.append(product)
        write_json(stage/'catalog.json',catalog)
        if promote:publish(stage,output,work)
        return dict(published=promote,stage=str(stage),products=added)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['study','root','output']:p.add_argument('--'+name,required=True)
    p.add_argument('--publish',action='store_true');a=p.parse_args();print(json.dumps(run(a.study,a.root,a.output,a.publish),indent=2))
if __name__=='__main__':main()
