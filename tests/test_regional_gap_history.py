import datetime as dt
import gzip
import json
import io
from pathlib import Path

import h3
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest
import xarray as xr

from oceanography import regional_gap_history as history
from oceanography.regional import SPECS
from oceanography.regional_transport import Transport, atomic_json, inspect_source


def context():
    cells=sorted([h3.latlng_to_cell(y,x,6) for y,x in [(48,-123),(49,-124),(50,-125)]])
    return dict(cells=cells,selected=cells[:2],core=[10,11,20,21],angle=np.zeros((2,2)),
                weight=np.array([1.,2.,3.,4.]),ids=np.array([cells[0],cells[0],cells[1],cells[1]]),inside=np.ones(4,bool))


def source(tmp_path,kind,start,end,missing=False,hours=None):
    times=pd.date_range(str(start)+'T00:30:00Z',str(end)+'T23:30:00Z',freq='h')
    if hours is not None:
        times=times[:hours]
    values=np.zeros((len(times),1,3,3),dtype='float32')
    if kind=='u':
        values[:]=np.where(np.arange(len(times))%24<12,1,-1)[:,None,None,None]
    if kind=='salinity':
        values[:]=5
        if missing:
            values[0,0,1,1:]=np.nan
            values[:,0,2,1:]=0  # valid freshwater is not missing
    name,units,standard=SPECS[kind]
    dataset=xr.Dataset({name:(('time','depth','gridY','gridX'),values,{'units':units,'standard_name':standard})},
                       coords={'time':('time',times.as_unit('s').asi8.astype(float),{'units':'seconds since 1970-01-01T00:00:00Z','calendar':'gregorian'}),
                               'depth':('depth',np.array([.5000003],dtype='float32'),{'units':'m','positive':'down'}),
                               'gridY':np.arange(9,12,dtype='int32'),'gridX':np.arange(19,22,dtype='int32')})
    path=tmp_path/f'{kind}-{start}-{end}-{missing}-{hours}.nc'
    dataset.to_netcdf(path,engine='scipy',format='NETCDF3_64BIT')
    compressed=path.with_suffix('.gz')
    compressed.write_bytes(gzip.compress(path.read_bytes()))
    return compressed


class OfflineSources:
    def __init__(self,root,missing=False,weekly=False):
        self.root=root;self.sources=root/'owned';self.sources.mkdir(exist_ok=True)
        self.missing=missing;self.weekly=weekly;self.calls=[];self.cap=2_000_000_000
    def acquire(self,kind,start,end,rectangle):
        self.calls.append((kind,start,end))
        if self.weekly and (end-start).days>=7:
            raise RuntimeError('Monthly source unavailable')
        path=source(self.root,kind,start,end,self.missing)
        return path,dict(kind=kind,start=str(start),end=str(end),compressed_sha256=history.sha(path),external_reference=str(path))


def setup(root):
    (root/'months').mkdir();(root/'receipts').mkdir()


def test_leap_and_partial_months():
    result=list(history.months('2024-01-31','2024-03-01'))
    assert result==[(dt.date(2024,1,31),dt.date(2024,1,31)),(dt.date(2024,2,1),dt.date(2024,2,29)),(dt.date(2024,3,1),dt.date(2024,3,1))]


def test_reversing_currents_and_independent_salinity_missingness(tmp_path):
    first,last='2024-01-31','2024-02-01'
    paths={k:source(tmp_path,k,first,last,missing=True) for k in SPECS}
    c=context()
    currents=list(history.interval_frames(paths,first,last,c,'currents'))
    salinity=list(history.interval_frames(paths,first,last,c,'salinity'))
    assert len(currents)==len(salinity)==2
    for frame in currents:
        selected=frame.h3_index.isin(c['selected'])
        assert frame.loc[selected,'current_speed_m_s'].eq(1).all()
        assert frame.loc[selected,['current_east_m_s','current_north_m_s']].eq(0).all().all()
        assert frame.loc[~selected,history.FAMILIES['currents']].isna().all().all()
    assert pd.isna(salinity[0].reference_salinity_g_kg.iloc[0])
    assert salinity[0].reference_salinity_g_kg.iloc[1]==0
    assert currents[0].current_speed_m_s.iloc[0]==1


def test_incomplete_hours_cannot_become_successful_null_day(tmp_path):
    path=source(tmp_path,'salinity','2024-01-01','2024-01-01',hours=23)
    with pytest.raises(ValueError,match='Incomplete'):
        inspect_source(path,'salinity','2024-01-01','2024-01-01',[10,11,20,21])


def test_weekly_recovery_and_checkpoint_resume(tmp_path):
    setup(tmp_path);cache=OfflineSources(tmp_path,weekly=True)
    first,last=dt.date(2024,2,1),dt.date(2024,2,11)
    record=history.checkpoint(tmp_path,'salinity',first,last,context(),cache)
    file=tmp_path/'months'/f'salinity-{first}-{last}.parquet'
    assert pq.ParquetFile(file).num_row_groups==11
    calls=len(cache.calls)
    assert history.checkpoint(tmp_path,'salinity',first,last,context(),cache)==record
    assert len(cache.calls)==calls
    file.write_bytes(b'corrupt checkpoint')
    with pytest.raises(Exception):
        history.checkpoint(tmp_path,'salinity',first,last,context(),cache)
    assert all(Path(p['external_reference']).exists() for p in record['sources'])


def test_cache_cap_and_eviction_replacement_guard(tmp_path):
    cache=Transport(tmp_path,cap=5,floor=0)
    path=cache.sources/'a.gz';path.write_bytes(b'1234')
    atomic_json(cache.receipts/'a.ownership.json',{'path':str(path),'state':'complete'})
    with pytest.raises(ValueError,match='cap'):
        cache.budget(2)
    with pytest.raises(ValueError,match='replacement'):
        cache.evict(path,{'disposable':'Incomplete/failed attempt'})
    with pytest.raises(ValueError,match='replacement'):
        cache.evict(path,{'checkpoint':str(tmp_path/'absent'),'sha256':'wrong'})
    assert path.read_bytes()==b'1234'
    outside=tmp_path/'external.gz';outside.write_bytes(b'external')
    with pytest.raises(ValueError,match='outside'):
        cache.evict(outside,{})
    replacement=tmp_path/'checked.parquet';replacement.write_bytes(b'H3 readback')
    cache.evict(path,{'checkpoint':str(replacement),'sha256':history.sha(replacement)})
    assert not path.exists() and outside.read_bytes()==b'external'


def test_streamed_source_validation_and_truncation_recovery(tmp_path,monkeypatch):
    import oceanography.regional_transport as transport
    native=source(tmp_path,'salinity','2024-01-01','2024-01-01')
    original=native.read_bytes();calls=[]
    class Response:
        headers={'Content-Encoding':'gzip'}
        def __init__(self,blob):self.raw=io.BytesIO(blob)
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def raise_for_status(self):pass
    def get(url,**kwargs):
        calls.append(url)
        return Response(original[:-8] if len(calls)==1 else original)
    monkeypatch.setattr(transport.requests,'get',get)
    monkeypatch.setattr(transport.time,'sleep',lambda seconds:None)
    cache=Transport(tmp_path/'cache',floor=0)
    monkeypatch.setattr(cache._stop,'wait',lambda seconds:False)
    path,receipt=cache.acquire('salinity',dt.date(2024,1,1),dt.date(2024,1,1),[9,11,19,21])
    assert len(calls)==2 and receipt['attempt']==2
    assert receipt['compressed_sha256']==history.sha(path)
    assert cache.acquire('salinity',dt.date(2024,1,1),dt.date(2024,1,1),[9,11,19,21])[0]==path
    assert len(calls)==2  # verified cache avoids another request


def test_availability_never_silently_accepts_an_interior_time_gap(monkeypatch):
    import types
    axis=pd.date_range('2024-01-01T00:30:00Z','2024-01-01T23:30:00Z',freq='h').delete(12)
    text='time\nUTC\n'+'\n'.join(x.isoformat().replace('+00:00','Z') for x in axis)+'\n'
    response=types.SimpleNamespace(content=text.encode(),text=text,raise_for_status=lambda:None)
    monkeypatch.setattr(history.requests,'get',lambda *args,**kwargs:response)
    with pytest.raises(ValueError,match='time-axis gap'):
        history.availability(dt.date(2024,1,1),dt.date(2024,1,1))


def test_additive_publication_final_readback_and_checkpoint_cleanup(tmp_path):
    work=tmp_path/'work';work.mkdir();setup(work)
    output=tmp_path/'Data';output.mkdir()
    baseline=output/'accepted.parquet';baseline.write_bytes(b'accepted legacy product')
    atomic_json(output/'catalog.json',{'study':{'study_sha256':'study'},'products':[{'id':'keep','path':baseline.name,'sha256':history.sha(baseline)}]})
    c=context();cache=OfflineSources(work)
    for first,last in history.months('2024-01-31','2024-02-01'):
        history.checkpoint(work,'currents',first,last,c,cache)
    plan={'start':'2024-01-31','end':'2024-02-01','plan_sha256':'frozen','spatial':{'study':{'study_sha256':'study'}}}
    product=history.assemble(work,output,plan,c,'currents',True)
    assert baseline.read_bytes()==b'accepted legacy product'
    assert json.loads((output/'catalog.json').read_text())['products'][0]['id']=='keep'
    final=output/product['path']
    assert history.sha(final)==product['sha256']
    assert pq.ParquetFile(final).num_row_groups==2
    assert not list((work/'months').glob('*.parquet'))
    assert all(p.exists() for p in work.glob('*.gz'))


def test_frozen_spatial_plan_change_refuses_resume(tmp_path,monkeypatch):
    output=tmp_path/'delivery';output.mkdir();pilot=tmp_path/'pilot';pilot.mkdir()
    study=tmp_path/'study.json';study.write_text('{}')
    c=context();evidence={'study':{'study_sha256':'study'},'native_centres':4}
    monkeypatch.setattr(history,'spatial_target',lambda *args:({'time':{'start':'2024-01-01','end_exclusive':'2025-01-01'}},evidence,c))
    monkeypatch.setattr(history,'availability',lambda first,last:(last,{'verified':'test axes'}))
    work=tmp_path/'work'
    history.run(study,pilot,output,work,start='2024-01-01',end='2024-01-01',prepare=True)
    evidence['native_centres']=5
    with pytest.raises(ValueError,match='Frozen plan'):
        history.run(study,pilot,output,work,start='2024-01-01',end='2024-01-01',prepare=True)


def test_shared_reservations_include_both_requests_and_actual_bytes(tmp_path,monkeypatch):
    import oceanography.regional_transport as transport
    monkeypatch.setattr(transport,'RESPONSE_CAP',10)
    cache=Transport(tmp_path,cap=20,floor=0,requests_in_flight=2)
    with cache:
        cache._reserve('a','source-a');cache._reserve('b','source-b')
        assert cache.state()['reserved_remaining_bytes']==20
        with pytest.raises(ValueError,match='cap'):
            cache._reserve('c','source-c')
        path=cache.sources/'a.gz'
        with path.open('xb',buffering=0) as handle:
            cache._write(handle,b'12345','a')
        state=cache.state()
        assert state['source_cache_bytes']==5 and state['reserved_remaining_bytes']==15
        assert state['peak_request_count']==2
        cache._release('a')
        with pytest.raises(ValueError,match='cap'):
            cache._reserve('c','source-c')
        cache._release('b');cache._reserve('c','source-c');cache._release('c')
    assert path.read_bytes()==b'12345'


def test_parallel_failed_face_drains_partner_before_weekly_recovery(tmp_path):
    class Sources(OfflineSources):
        requests_in_flight=2
        def acquire(self,kind,start,end,rectangle):
            if kind=='u' and (end-start).days>=7:
                raise RuntimeError('U monthly failed while V completed')
            return super().acquire(kind,start,end,rectangle)
    setup(tmp_path);cache=Sources(tmp_path)
    first,last=dt.date(2024,2,1),dt.date(2024,2,11)
    record=history.checkpoint(tmp_path,'currents',first,last,context(),cache)
    unused=[r for r in record['sources'] if r.get('unused_after_weekly_recovery')]
    assert len(unused)==1 and unused[0]['kind']=='v'
    assert pq.ParquetFile(tmp_path/'months'/f'currents-{first}-{last}.parquet').num_row_groups==11


def test_two_request_prefetch_deduplicates_and_releases_capacity(tmp_path,monkeypatch):
    import threading
    import oceanography.regional_transport as transport
    blobs={k:source(tmp_path,k,'2024-01-01','2024-01-01').read_bytes() for k in ['u','v']}
    barrier=threading.Barrier(2);calls=[]
    class Response:
        headers={'Content-Encoding':'gzip'}
        def __init__(self,blob):self.raw=io.BytesIO(blob)
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def raise_for_status(self):pass
    def get(url,**kwargs):
        kind=next(k for k in blobs if SPECS[k][0] in url)
        calls.append(kind);barrier.wait(timeout=5)
        return Response(blobs[kind])
    monkeypatch.setattr(transport.requests,'get',get)
    with Transport(tmp_path/'cache',floor=0,requests_in_flight=2) as cache:
        for kind in ['u','u','v']:cache.prefetch(kind,'2024-01-01','2024-01-01',[9,11,19,21])
        for kind in ['u','v']:
            path,r=cache.acquire(kind,'2024-01-01','2024-01-01',[9,11,19,21])
            assert path.read_bytes()==blobs[kind]
            assert r['compressed_sha256']==history.sha(path)
        assert cache.state()['peak_request_count']==2
        assert cache.state()['reserved_remaining_bytes']==0
    assert sorted(calls)==['u','v']


def test_explicit_producer_upgrade_preserves_checkpoints_and_prior_plan(tmp_path):
    setup(tmp_path);cache=OfflineSources(tmp_path)
    first=last=dt.date(2024,1,1)
    record=history.checkpoint(tmp_path,'salinity',first,last,context(),cache)
    path=tmp_path/'months'/f'salinity-{first}-{last}.parquet'
    binding=dict(code=history.fingerprint(),spatial={'study':'unchanged'},requested_start=str(first),requested_end=str(last),versions={'test':'same'})
    prior={**binding,'code':{'old':'producer'},'plan_sha256':'prior-scientific-plan'}
    atomic_json(tmp_path/'plan.json',prior)
    digest=history.sha(tmp_path/'plan.json')
    with pytest.raises(ValueError,match='checksum'):
        history.upgrade_plan(tmp_path,prior,binding,context(),'wrong')
    with pytest.raises(ValueError,match='spatial'):
        history.upgrade_plan(tmp_path,prior,{**binding,'spatial':{'changed':True}},context(),digest)
    updated=history.upgrade_plan(tmp_path,prior,binding,context(),digest)
    assert history.sha(path)==record['sha256']
    assert history.sha(tmp_path/f'plan-before-{digest}.json')==digest
    assert updated['producer_transitions'][0]['verified_checkpoints'][0]['sha256']==record['sha256']
    assert updated['code']==binding['code'] and updated['spatial']==prior['spatial']


def test_repeated_upgrades_preserve_original_checkpoint_producer(tmp_path):
    setup(tmp_path);cache=OfflineSources(tmp_path)
    first=last=dt.date(2024,1,1)
    record=history.checkpoint(tmp_path,'salinity',first,last,context(),cache)
    record.pop('producer_code')  # original receipts predate per-month attribution
    atomic_json(tmp_path/'receipts'/f'salinity-{first}-{last}.month.json',record)
    binding={'code':{'next':'producer'},'spatial':{'same':True},'versions':{'same':'version'}}
    prior={**binding,'code':{'original':'producer'},'plan_sha256':'prior'}
    atomic_json(tmp_path/'plan.json',prior)
    upgraded=history.upgrade_plan(tmp_path,prior,binding,context(),history.sha(tmp_path/'plan.json'))
    next_binding={**binding,'code':{'third':'producer'}}
    upgraded=history.upgrade_plan(tmp_path,upgraded,next_binding,context(),history.sha(tmp_path/'plan.json'))
    assert all(t['verified_checkpoints'][0]['producer_code']=={'original':'producer'} for t in upgraded['producer_transitions'])


def test_optional_narrow_seed_is_preserved_but_does_not_block_full_request(tmp_path,monkeypatch):
    import oceanography.regional_transport as transport
    seed=tmp_path/'seed';seed.mkdir()
    original=source(tmp_path,'u','2024-01-01','2024-01-01')
    with xr.open_dataset(original.with_suffix('.nc'),decode_times=False) as dataset:
        narrow=dataset.isel(gridX=slice(1,None)).load()
    candidate=seed/'narrow.nc.http-gzip'
    candidate.write_bytes(gzip.compress(bytes(narrow.to_netcdf(engine='scipy',format='NETCDF3_64BIT'))))
    digest=history.sha(candidate)
    atomic_json(seed/'narrow.receipt.json',dict(successful_complete_download=True,kind='u',start='2024-01-01',end='2024-01-01',
                url=transport.BASE+'/griddap/'+history.DATASETS['u'][0]+'.nc',compressed_sha256=digest))
    class Response:
        headers={'Content-Encoding':'gzip'}
        def __init__(self):self.raw=io.BytesIO(original.read_bytes())
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def raise_for_status(self):pass
    calls=[]
    def get(*args,**kwargs):calls.append(args);return Response()
    monkeypatch.setattr(transport.requests,'get',get)
    with Transport(tmp_path/'cache',seeds=[seed],floor=0) as cache:
        path,receipt=cache.acquire('u','2024-01-01','2024-01-01',[9,11,19,21])
        assert len(calls)==1 and path.parent==cache.sources
        assert receipt['bounds']==[9,11,19,21]
    assert history.sha(candidate)==digest


def test_serial_parallel_months_produce_identical_daily_h3(tmp_path,monkeypatch):
    import threading
    import oceanography.regional_transport as transport
    output=tmp_path/'delivery';output.mkdir();pilot=tmp_path/'pilot';pilot.mkdir()
    study=tmp_path/'study.json';study.write_text('{}')
    evidence={'study':{'study_sha256':'study'},'native_centres':4}
    monkeypatch.setattr(history,'spatial_target',lambda *args:({'time':{'start':'2024-01-31','end_exclusive':'2024-02-02'}},evidence,context()))
    monkeypatch.setattr(history,'availability',lambda first,last:(last,{'verified':'test axes'}))
    blobs={}
    for day in ['2024-01-31','2024-02-01']:
        native=source(tmp_path,'salinity',day,day)
        with xr.open_dataset(native.with_suffix('.nc'),decode_times=False) as dataset:
            subset=dataset.isel(gridY=slice(1,None),gridX=slice(1,None)).load()
        blobs[day]=gzip.compress(bytes(subset.to_netcdf(engine='scipy',format='NETCDF3_64BIT')))
    barrier=threading.Barrier(2)
    class Response:
        headers={'Content-Encoding':'gzip'}
        def __init__(self,blob):self.raw=io.BytesIO(blob)
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def raise_for_status(self):pass
    concurrent=False
    def get(url,**kwargs):
        if concurrent:barrier.wait(timeout=5)
        day=next(d for d in blobs if d in url)
        return Response(blobs[day])
    monkeypatch.setattr(transport.requests,'get',get)
    for workers in [1,2]:
        concurrent=workers==2
        history.run(study,pilot,output,tmp_path/f'run{workers}',families=('salinity',),requests_in_flight=workers)
    name='salishsea-gap-salinity-r6-daily.parquet'
    assert pq.read_table(tmp_path/'run1'/name).equals(pq.read_table(tmp_path/'run2'/name))
    state=json.loads((tmp_path/'run2/transport-state.json').read_text())
    assert state['peak_request_count']==2 and state['source_cache_bytes']==0
