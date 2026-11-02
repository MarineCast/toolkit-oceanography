import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
import xarray as xr
from oceanography.history import (HistoryCache, choose_sources, GridAggregator, validate_native_dates, valid_checkpoint, write_checkpoint, chunk_url)
from oceanography.daily import SOURCES, aggregate, sha
import h3

def source(tmp_path, name='sst', day='2024-07-01'):
    spec=SOURCES[name]
    lat=np.array([48.,48.01]) if name=='sst' else np.array([48.01,48.])
    values=np.array([[[10.,20.],[30.,40.]]]) if name=='sst' else np.array([[[1.,-1.],[np.nan,3.]]])
    data={spec['variable']:(('time','latitude','longitude'),values,{'units':spec['units']})}
    if name=='sst': data['mask']=(('time','latitude','longitude'),np.array([[[1,2],[1,2]]]))
    ds=xr.Dataset(data,coords={'time':[pd.Timestamp(day+f'T{spec["hour"]:02d}:00:00')],'latitude':lat,'longitude':[-123.,-122.99]})
    path=tmp_path/(name+'.nc'); ds.to_netcdf(path)
    cells=sorted({h3.latlng_to_cell(48.,-123.,spec['resolution']),h3.latlng_to_cell(49.,-124.,spec['resolution'])})
    return path,spec,cells



def test_sq_precedence_nrt_fallback_and_absent_dates():
    inventories={'sst':{'dates':['2024-01-01']},'sq':{'dates':['2024-01-01']},'nrt':{'dates':['2024-01-01','2024-01-02']}}
    selected=choose_sources(inventories,'2024-01-01','2024-01-03')
    assert selected['chlorophyll']=={'2024-01-01':'sq','2024-01-02':'nrt','2024-01-03':None}
    assert selected['sst']['2024-01-02'] is None


def test_chunk_contains_only_regional_bounds():
    url=chunk_url(SOURCES['sst'],['2009-01-01','2009-01-31'],[-129.7,45.9,-121.5,51.5])
    assert 'analysed_sst' in url and 'mask' in url
    assert '[(45.9):1:(51.5)]' in url and '[(-129.7):1:(-121.5)]' in url


def test_optimized_aggregation_exactly_matches_pilot(tmp_path):
    p,s,c=source(tmp_path)
    bbox=[-123.,48.,-122.99,48.01]; day=dt.date(2024,7,1)
    expected,_=aggregate(p,s,day,c,bbox)
    aggregator=GridAggregator(s,c,bbox)
    with xr.open_dataset(p) as ds:
        actual=aggregator.day(ds,0,str(day))
    pd.testing.assert_frame_equal(expected,actual,check_exact=True)


def test_native_axis_mismatch_is_failure_not_null(tmp_path):
    p,s,c=source(tmp_path)
    with xr.open_dataset(p) as ds:
        with pytest.raises(ValueError,match='dates'): validate_native_dates(ds,s,['2024-07-02'])


def test_checkpoint_binding_tampering_and_resume(tmp_path):
    p,s,c=source(tmp_path)
    frame,_=aggregate(p,s,dt.date(2024,7,1),c,[-123.,48.,-122.99,48.01])
    job={'id':'sst-2009-01','dates':['2024-07-01']}
    assert not valid_checkpoint(tmp_path,job,'binding')
    write_checkpoint(tmp_path,job,frame,'binding',{'url':'example'})
    assert valid_checkpoint(tmp_path,job,'binding')
    with pytest.raises(ValueError,match='binding'): valid_checkpoint(tmp_path,job,'changed')
    (tmp_path/'sst-2009-01.parquet').write_bytes(b'broken')
    with pytest.raises(ValueError,match='integrity'): valid_checkpoint(tmp_path,job,'binding')


def test_compressed_cache_expanded_integrity_and_scratch_cleanup(tmp_path):
    p,s,c=source(tmp_path); original=p.read_bytes()
    compressed=tmp_path/'cached.gz'; compressed.write_bytes(gzip.compress(original))
    receipt={'path':str(compressed),'sha256':hashlib.sha256(original).hexdigest()}
    cache=HistoryCache(tmp_path,True)
    with cache.netcdf(receipt,tmp_path/'scratch') as ds: assert ds.time.size==1
    assert list((tmp_path/'scratch').iterdir())==[]
    receipt['sha256']='bad'
    with pytest.raises(ValueError,match='Expanded'): cache.bytes(receipt)
    with pytest.raises(ValueError,match='Missing offline'): cache.fetch('https://example.test/missing')


def test_complete_history_publication_missing_days_and_exact_existing_rows(tmp_path):
    from oceanography.history import assemble
    from oceanography.daily import validate_frame
    checkpoint=tmp_path/'history'/'checkpoints'; checkpoint.mkdir(parents=True)
    output=tmp_path/'Data'/'Oceanography'; output.parent.mkdir()
    work=tmp_path/'work'; work.mkdir()
    days=['2024-07-01','2024-07-02']; jobs=[]; members={}; selections={}; specs={}
    for product in ['sst','chlorophyll']:
        spec=SOURCES[product]; cell=h3.latlng_to_cell(48.,-123.,spec['resolution'])
        members[str(spec['resolution'])]=[cell]
        source_name='sst' if product=='sst' else 'sq'
        selections[product]={days[0]:source_name,days[1]:None}
        job={'id':f'{product}-{source_name}-2024-07','product':product,'source':source_name,'dates':[days[0]]}
        frame=pd.DataFrame({'date':[dt.date(2024,7,1)],'h3_index':[cell],spec['metric']:[12. if product=='sst' else 2.]})
        write_checkpoint(checkpoint,job,frame,'binding',{'url':'fixture'})
        jobs.append(job)
    plan={'study_id':'fixture','study_revision':'v1','start':days[0],'endings':{'sst':days[1],'chlorophyll':days[1]},'study':{},'members':members,'jobs':jobs,'selections':selections}
    summaries=assemble(plan,checkpoint,output,work,'binding')
    assert summaries['sst']['row_count']==2 and summaries['sst']['null']==1
    assert summaries['chlorophyll']['source_day_counts']['native_source_date_absent']==1
    # Safe repeat verifies exact previously published rows instead of duplicating them.
    repeated=assemble(plan,checkpoint,output,work,'binding')
    assert repeated['sst']['previous_rows_verified_exact']==2
    assert repeated['sst']['sha256']==summaries['sst']['sha256']
