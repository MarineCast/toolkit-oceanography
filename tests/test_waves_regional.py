"""Offline source qualification, native scientific semantics and additive publication."""
import datetime as dt
import hashlib
import io
import json
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from tests.test_waves import study
from oceanography import waves_regional as c, waves_ssc as s, waves_usgs as u


def blob(day=dt.date(2009,1,2),slots=48,unit='s'):
    b=io.BytesIO()
    with h5py.File(b,'w') as f:
        f['latitude']=[48.,48.0045];f['longitude']=[237.,237.007]
        f['time']=(pd.Timestamp(day)-pd.Timestamp('1990-01-01')).days+np.arange(slots)/48
        f['time'].attrs['units']='days since 1990-01-01 00:00:00'
        for name,(units,standard) in s.VARIABLES.items():
            a=np.full((slots,2,2),{'hs':1.5,'t02':6.,'dir':359.}[name],dtype='f4')
            if name=='dir':a[slots//2:]=1.
            obj=f.create_dataset(name,data=a)
            obj.attrs.update(units=unit if name=='t02' else units,standard_name=standard,_FillValue=np.float32(9.969209968386869e36))
    return b.getvalue()


def fake_source(raw):
    def fetch(entry):
        return io.BytesIO(raw),dict(url=entry['url'],bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    return fetch


def inv(raw,day='2009-01-02'):
    date=dt.date.fromisoformat(day);name=f'SoG_ww3_fields_{date:%Y%m%d}_{date:%Y%m%d}.nc'
    return {day:dict(url=s.BASE+s.canonical(date)+'/'+name,bytes=len(raw),name=name)},dict(sha256='0'*64)


def test_inventory_canonical_runs_and_forecast_exclusion():
    name='SoG_ww3_fields_20200426_20200426.nc';url=s.BASE+'26apr20/'+name
    raw=('name,url,size\n,,bytes\n'+f'{name},{url},200\n{name},{url.replace("26apr20/","26apr20.aside/")},201\n').encode()
    selected,excluded=s.parse_inventory(raw)
    assert list(selected)==['2020-04-26'] and len(excluded)==1
    with pytest.raises(ValueError,match='Conflicting'):
        s.parse_inventory(raw+f'{name},{url},200\n'.encode())
    with pytest.raises(ValueError,match='Untrusted'):
        s.parse_inventory(raw.replace(b'https://salishsea.eos.ubc.ca',b'https://other.example'))


def test_native_units_time_partial_and_grid_identity():
    raw=blob(slots=47);grid=dict(latitude=[48.,48.0045],longitude=[-123.,-122.993])
    # Longitude normalization is tested against the exact source numeric grid.
    with h5py.File(io.BytesIO(raw),'r') as f:
        lat,lon=s.grid(f);grid=dict(latitude=lat.tolist(),longitude=lon.tolist())
    values,meta=s.native(io.BytesIO(raw),dt.date(2009,1,2),np.array([0]),grid)
    assert meta['samples']==47 and np.isnan(values[:,-1]).all()
    with pytest.raises(ValueError,match='units'):
        s.native(io.BytesIO(blob(unit='minutes')),dt.date(2009,1,2),np.array([0]),grid)
    with pytest.raises(ValueError,match='canonical UTC'):
        s.native(io.BytesIO(raw),dt.date(2009,1,3),np.array([0]),grid)
    with pytest.raises(ValueError,match='grid changed'):
        s.native(io.BytesIO(raw),dt.date(2009,1,2),np.array([0]),dict(latitude=[48.,49.],longitude=grid['longitude']))


def test_spatial_circular_per_quantity_counts_and_complete_daily():
    a=np.ones((3,48,4));a[0]=[1,3,0,np.nan];a[1]=[6,np.nan,0,8];a[2]=[359,1,90,270]
    values,counts=c.aggregate(a,np.array([0,0,1,1]),np.ones(4),3)
    assert values[0,0,0]==2 and values[1,0,0]==6
    assert values[2,0,0]==pytest.approx(0,abs=1e-9)
    assert counts[:,0,0].tolist()==[2,2,1,2]
    assert values[0,0,1]==0 and np.isnan(values[2,0,2])
    values[0,0,0]=np.nan
    tables=c.day_tables('salishseacast',dt.date(2009,1,1),values,counts,['a','b','c'])
    c.validate_day('salishseacast',dt.date(2009,1,1),tables,['a','b','c'])
    assert tables['daily'][c.DAILY[0]][0].as_py() is None
    assert tables['daily'][c.DAILY[2]][0].as_py()==6
    assert tables['daily'][c.DAILY[4]][1].as_py()==0


def test_ssc_full_keys_null_gaps_resume_source_receipts_and_preservation(study,tmp_path):
    raw=blob();inventory=lambda:inv(raw)
    work=tmp_path/'ssc-work';output=tmp_path/'Data/Oceanography/waves-salishseacast'
    era=tmp_path/'Data/Oceanography/waves';era.mkdir(parents=True);(era/'sentinel').write_text('ERA5')
    result=s.run(study,'2009-01-01','2009-01-02',output=output,work=work,requests_in_flight=1,inventory_fetcher=inventory,fetcher=fake_source(raw))
    check=c.check(result['catalog_path'],study_path=study);assert check['valid']
    cat=json.loads((output/'catalog.json').read_text())
    assert cat['ever_complete_daily_height_cells']==1
    table=pq.ParquetFile(output/'waves-native.parquet').read_row_group(0)
    assert table[c.FIELDS[0]].null_count==len(table)
    assert (era/'sentinel').read_text()=='ERA5'
    def fail(*args):raise AssertionError('No source access on resume')
    assert s.run(study,'2009-01-01','2009-01-02',output=output,work=work,requests_in_flight=1,inventory_fetcher=fail,fetcher=fail)
    checkpoint=work/'checkpoints/2009-01-02/native.parquet';checkpoint.write_bytes(b'corrupt')
    with pytest.raises(ValueError,match='hash mismatch'):
        s.run(study,output=output,work=work,requests_in_flight=1,inventory_fetcher=fail,fetcher=fail)


def test_missing_quantity_fill_masked_before_scaling():
    b=io.BytesIO(blob())
    with h5py.File(b,'r+') as f:
        obj=f['hs'];obj[0,0,0]=obj.attrs['_FillValue'];obj.attrs['scale_factor']=.1
        result=s.decode(f,'hs',np.array([0]))
        assert np.isnan(result[0,0]) and result[1,0]==pytest.approx(.15)


def test_incomplete_final_day_and_acquisition_error_not_synthetic_gap(study,tmp_path):
    raw=blob(slots=47)
    with pytest.raises(ValueError,match='not complete'):
        s.run(study,'2009-01-02',work=tmp_path/'partial',inventory_fetcher=lambda:inv(raw),fetcher=fake_source(raw))
    raw=blob();calls=[]
    def fetch(entry):
        calls.append(1)
        if len(calls)>1:raise ValueError('corrupt native payload')
        return fake_source(raw)(entry)
    with pytest.raises(ValueError,match='corrupt'):
        s.run(study,'2009-01-02',work=tmp_path/'failed',inventory_fetcher=lambda:inv(raw),fetcher=fetch,requests_in_flight=1)
    assert not (tmp_path/'failed/checkpoints/2009-01-02').exists()
    assert json.loads((tmp_path/'failed/progress.json').read_text())['status']=='failed'


def usgs_blob():
    b=io.BytesIO();offset=int((pd.Timestamp('2009-01-01')-pd.Timestamp('1941-01-01')).total_seconds()/3600)
    with h5py.File(b,'w') as f:
        f.attrs['General']='Values are at lat_10mIso/lon_10mIso; supplied lat/lon are original reference points.'
        f['lat']=[48.];f['lon']=[-123.];f['station']=[1]
        f['time']=np.arange(offset+25,dtype='f8');f['time'].attrs['units']='hours since 1941-01-01'
        for name,units,value in [('Hs','meters',15000),('Tm','seconds',60000),('Dm','degrees',2700000)]:
            obj=f.create_dataset(name,shape=(offset+25,1),dtype='i4',chunks=(24,1),fillvalue=-9999)
            obj[offset:]=value;obj.attrs.update(units=units,scale_factor=.0001,add_offset=0.,_FillValue=-9999)
        f['Hs'][offset,0]=100 # 1 cm: Tm/Dm suppressed even if original source omitted masking.
    return b.getvalue()


USGS_URL='https://cmgds.marine.usgs.gov/data-releases/media/test/Reanalysis_and_Projected_CoSMoSwaves_SanJuan_sealevel000m.nc'


def test_usgs_rejects_reference_coordinates_without_publishing(study,tmp_path):
    raw=usgs_blob();files={USGS_URL.rsplit('/',1)[-1]:USGS_URL}
    with pytest.raises(u.QualificationError,match='effective 10 m'):
        u.run(study,work=tmp_path/'usgs',files=files,opener=lambda url:io.BytesIO(raw))
    assert not (tmp_path/'Data/Oceanography/waves-usgs-nearshore').exists()
    report=json.loads((tmp_path/'usgs/qualification.json').read_text())
    assert not report['qualified'] and report['reasons']


def test_qualified_usgs_source_tm_partial_frontier_and_unknown_direction_null(study,tmp_path):
    raw=usgs_blob();name=USGS_URL.rsplit('/',1)[-1];files={name:USGS_URL};opener=lambda url:io.BytesIO(raw)
    report,_=u.qualify(files,opener=opener)
    mapping=dict(release_doi=u.DOI,effective_coordinate_evidence_url='https://authority.example/verified-effective-grid',
                 files={name:dict(source_header_sha256=report['files'][name]['header_sha256'],latitude=[48.],longitude=[-123.],station_index=[0])})
    path=tmp_path/'mapping.json';path.write_text(json.dumps(mapping))
    result=u.run(study,work=tmp_path/'usgs',files=files,mapping_path=path,opener=opener)
    cat=json.loads(Path(result['catalog_path']).read_text());assert cat['date_end']=='2009-01-02'
    q=pq.ParquetFile(Path(result['catalog_path']).parent/'waves-native.parquet')
    assert q.read_row_group(0)['mean_wave_period_source_tm_s'].null_count==25 # 24 unsupported + one low-height sample
    assert q.read_row_group(0)['mean_wave_direction_from_deg'].null_count==48
    daily=pq.ParquetFile(Path(result['catalog_path']).parent/'waves-daily.parquet')
    assert daily.read_row_group(1)['significant_wave_height_mean_m'].null_count==2
    assert c.check(result['catalog_path'],study_path=study)['valid']
    # Qualification mapping is hash-bound, not accepted solely by point count.
    mapping['files'][name]['source_header_sha256']='f'*64;path.write_text(json.dumps(mapping))
    with pytest.raises(u.QualificationError):u.run(study,work=tmp_path/'other',files=files,mapping_path=path,opener=opener)


def test_regional_reader_rejects_fabricated_spatial_support_and_arrow_nan(study,tmp_path):
    raw=blob();result=s.run(study,'2009-01-02',work=tmp_path/'owned',inventory_fetcher=lambda:inv(raw),fetcher=fake_source(raw),requests_in_flight=1)
    output=Path(result['catalog_path']).parent;path=output/'waves-support.parquet';table=pq.read_table(path)
    values=table[c.COUNTS[0]].to_numpy().copy();values[values==0]=1
    table=table.set_column(table.schema.get_field_index(c.COUNTS[0]),table.schema.field(c.COUNTS[0]),pa.array(values))
    pq.write_table(table,path)
    cat=json.loads((output/'catalog.json').read_text());cat['products']['support'].update(sha256=c.sha(path),bytes=path.stat().st_size)
    (output/'catalog.json').write_text(json.dumps(cat))
    with pytest.raises(ValueError,match='geometric support'):
        c.check(output/'catalog.json',study_path=study)
    tables=c.day_tables('salishseacast',dt.date(2009,1,1),np.full((3,48,1),np.nan),np.zeros((4,48,1),dtype='i4'),['cell'])
    field=tables['native'].schema.field(c.FIELDS[0]);tables['native']=tables['native'].set_column(2,field,pa.array([np.nan]*48,from_pandas=False))
    with pytest.raises(ValueError,match='Arrow null'):
        c.validate_day('salishseacast',dt.date(2009,1,1),tables,['cell'])


def test_failed_publication_preserves_delivery_and_unrelated_entries(study,tmp_path,monkeypatch):
    raw=blob();work=tmp_path/'work';result=s.run(study,'2009-01-02',work=work,inventory_fetcher=lambda:inv(raw),fetcher=fake_source(raw),requests_in_flight=1)
    output=Path(result['catalog_path']).parent;old={p.name:c.sha(p) for p in output.iterdir()}
    # Direct finalizer checks publication rollback; a completed run is a no-op.
    plan=json.loads((work/'plan.json').read_text())
    def fail(*args):raise OSError('publication failed')
    monkeypatch.setattr(c,'publish',fail)
    with pytest.raises(OSError,match='publication failed'):
        c.finalize(work,output,plan,study)
    assert old=={p.name:c.sha(p) for p in output.iterdir()}
    (output/'user.txt').write_text('preserve')
    with pytest.raises(ValueError,match='Unrelated'):
        c.finalize(work,output,plan,study)
    assert (output/'user.txt').read_text()=='preserve'


def test_available_source_with_no_geometric_overlap_stays_all_null(study,tmp_path):
    buffer=io.BytesIO(blob())
    with h5py.File(buffer,'r+') as f:f['latitude'][:]=[49.,49.0045]
    raw=buffer.getvalue()
    result=s.run(study,'2009-01-02',work=tmp_path/'outside',inventory_fetcher=lambda:inv(raw),fetcher=fake_source(raw),requests_in_flight=1)
    output=Path(result['catalog_path']).parent
    table=pq.read_table(output/'waves-native.parquet')
    assert table[c.FIELDS[0]].null_count==len(table)
    assert all(v==0 for v in pq.read_table(output/'waves-support.parquet')[c.COUNTS[0]].to_pylist())
    assert c.check(result['catalog_path'],study_path=study)['valid']
