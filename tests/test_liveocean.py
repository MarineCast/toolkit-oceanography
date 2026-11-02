import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest
pytest.importorskip('h5py')
from oceanography import liveocean as lo
from oceanography.daily import sha
from oceanography.history import atomic_json


def binding():
    return {'url':lo.URLS[0],'etag':'"v1"','object_bytes':1000,'last_modified':'date'}


def test_concentrations_weights_units_missing_and_true_zero():
    arrays={'salt':np.array([[30.,0.,np.nan]]),'oxygen':np.array([[0.,6.,-1.]]),'NO3':np.array([[2.,4.,1e20]])}
    ids=np.array([['a','a','b']]);w=np.array([[1.,3.,1.]]);m={n:np.ones((1,3),bool) for n in arrays}
    frame,diag=lo.aggregate(dt.date(2013,1,1),arrays,['a','b','c'],ids,w,m)
    assert frame.loc[0,'reference_salinity_g_kg']==7.5*lo.FACTOR
    assert frame.loc[0,'dissolved_oxygen_mmol_m3']==4.5
    assert frame.loc[0,'nitrate_mmol_m3']==3.5
    assert frame.iloc[1:,2:].isna().all().all()
    assert diag['oxygen']['excluded_native_points']==1
    lo.validate(frame,[dt.date(2013,1,1)],['a','b','c'])
    with pytest.raises(ValueError,match='identity'):lo.validate(frame.iloc[::-1],[dt.date(2013,1,1)],['a','b','c'])


def test_empty_source_day_is_failure():
    with pytest.raises(ValueError,match='Wholly missing'):
        lo.aggregate(dt.date(2013,1,1),{'salt':np.array([[np.nan]])},['a'],np.array([['a']]),np.ones((1,1)),{'salt':np.ones((1,1),bool)})


def test_native_daily_axis_is_days_since_noon_not_unix_seconds(tmp_path):
    import h5py
    p=tmp_path/'native.nc'
    with h5py.File(p,'w') as f:
        f.attrs['history']='ncks -d s_rho,29 source/lowpassed.nc'
        axis=f.create_dataset('ocean_time',data=np.arange(2556,dtype='int64'))
        axis.attrs['units']='days since 2013-01-01T12:00:00'
        for name in lo.FIELDS:
            d=f.create_dataset(name,shape=(2556,1302,663),dtype='float32',chunks=(1,1302,663),compression='gzip',fillvalue=1e20)
            if name=='oxygen':d.attrs['units']='millimole_oxygen meter-3'
            if name=='NO3':d.attrs['units']='millimole_nitrogen meter-3'
        dates=lo.native_metadata(f,0)
        assert str(dates[0])=='2013-01-01 12:00:00+00:00' and len(dates)==2556
        axis[3]=2
        with pytest.raises(ValueError,match='axis'):lo.native_metadata(f,0)


def test_budget_counts_shared_payload_and_reservations(tmp_path,monkeypatch):
    monkeypatch.setattr(lo,'CAP',20);monkeypatch.setattr(lo,'FLOOR',0)
    other=tmp_path/'other';other.mkdir();(other/'raw').write_bytes(b'12345')
    b=lo.Budget(tmp_path/'own',[other]);b.reserve(10)
    with pytest.raises(ValueError,match='cap'):b.reserve(6)
    assert b.peak==15;b.release(10);assert b.reserved==0
    with pytest.raises(ValueError,match='Overlapping'):lo.Budget(tmp_path,[other])


def test_verified_external_range_reuse_and_corruption(tmp_path):
    own=tmp_path/'own';seed=tmp_path/'seed';seed.mkdir()
    p=seed/'object-0-10-3.bin';p.write_bytes(b'abc')
    r={'url':lo.URLS[0],'etag':'"v1"','start':10,'bytes':3,'sha256':sha(p)}
    atomic_json(p.with_suffix('.json'),r)
    a=lo.Archive(0,own,lo.Budget(own),seed,binding(),True)
    assert a.fetch(10,3)[0]==p and not (own/p.name).exists()
    p.write_bytes(b'abd')
    with pytest.raises(ValueError,match='checksum'):a.fetch(10,3)
    with pytest.raises(ValueError,match='offline'):a.fetch(11,3)


class Response:
    status_code=206
    headers={'Content-Range':'bytes 10-12/1000'}
    def raise_for_status(self):pass
    def __enter__(self):return self
    def __exit__(self,*a):pass
    def iter_content(self,n):yield b'abc'


def test_range_honors_etag_length_and_releases_budget(tmp_path,monkeypatch):
    b=lo.Budget(tmp_path);a=lo.Archive(0,tmp_path,b,binding=binding(),offline=True);a.offline=False
    class Session:
        def get(self,url,**kw):
            assert kw['headers']['If-Match']=='"v1"';assert kw['headers']['Range']=='bytes=10-12'
            return Response()
    a.local.session=Session()
    p,r=a.fetch(10,3)
    assert p.read_bytes()==b'abc' and r['sha256']==hashlib.sha256(b'abc').hexdigest() and b.reserved==0
    a.ranges=[(10,13,p)];a.seek(11);assert a.read(2)==b'bc'


def test_ignored_range_is_rejected_without_unbounded_download(tmp_path):
    b=lo.Budget(tmp_path);a=lo.Archive(0,tmp_path,b,binding=binding(),offline=True);a.offline=False
    class Bad(Response):status_code=200
    class Session:
        def get(self,*a,**kw):return Bad()
    a.local.session=Session()
    with pytest.raises(ValueError,match='honor'):a.fetch(10,3)
    assert b.reserved==0 and not list(tmp_path.glob('*.bin')) and not list(tmp_path.glob('*.part'))


def test_response_receipt_headroom_is_reserved_before_network(tmp_path,monkeypatch):
    monkeypatch.setattr(lo,'CAP',4098);monkeypatch.setattr(lo,'FLOOR',0)
    b=lo.Budget(tmp_path);a=lo.Archive(0,tmp_path,b,binding=binding(),offline=True);a.offline=False
    with pytest.raises(ValueError,match='cap'):a.fetch(10,3)
    assert b.reserved==0 and a.stats['requests']==0


def test_eviction_requires_h3_readback_and_never_deletes_external_seed(tmp_path):
    own=tmp_path/'sources';own.mkdir();external=tmp_path/'seed';external.mkdir()
    a=lo.Archive(0,own,lo.Budget(own),binding=binding(),offline=True)
    p=own/'object-0-10-3.bin';p.write_bytes(b'abc');r={'bytes':3,'sha256':sha(p)};atomic_json(p.with_suffix('.json'),r)
    with pytest.raises(ValueError,match='replacement'):lo.evict_payloads(a,[(p,r)],{'path':str(tmp_path/'missing'),'sha256':'bad'})
    h3file=tmp_path/'month.parquet';h3file.write_bytes(b'verified');proof={'path':str(h3file),'sha256':sha(h3file)}
    seed=external/p.name;seed.write_bytes(b'abc')
    result=lo.evict_payloads(a,[(p,r),(seed,r)],proof)
    assert len(result)==1 and not p.exists() and seed.exists()


def prepare_month(tmp_path):
    root=tmp_path/'work';root.mkdir();(root/'sources').mkdir();(root/'months').mkdir()
    out=tmp_path/'out';out.mkdir()
    days=[dt.date(2013,1,1),dt.date(2013,1,2)];cells=['a','b']
    frames=[]
    for d in days:
        f=pd.DataFrame({'date':[d,d],'h3_index':cells,'reference_salinity_g_kg':[30.,np.nan],
            'dissolved_oxygen_mmol_m3':[1.,0.],'nitrate_mmol_m3':[np.nan,2.]});frames.append(f)
    frame=pd.concat(frames,ignore_index=True);p=root/'months/2013-01.parquet';frame.to_parquet(p,index=False)
    atomic_json(p.with_suffix('.json'),{'start':str(days[0]),'end':str(days[-1]),'sha256':sha(p),'sources':[]})
    plan={'start':str(days[0]),'end':str(days[-1]),'study':{'study_sha256':'study'}}
    atomic_json(root/'plan.json',plan);atomic_json(out/'catalog.json',{'study':plan['study'],'products':[]})
    return root,out,plan,cells,frame


def test_full_daily_assembly_additive_publish_and_exact_cleanup(tmp_path):
    root,out,plan,cells,frame=prepare_month(tmp_path)
    products=lo.assemble(root,out,plan,cells,['2013-01'])
    assert len(products)==3 and all(pq.ParquetFile(out/p['path']).num_row_groups==2 for p in products)
    assert len(json.loads((out/'catalog.json').read_text())['products'])==3
    lo.cleanup_intermediates(root,out,products)
    assert not list((root/'months').iterdir()) and not list((root/'sources').iterdir())
    assert json.loads((root/'cleanup.json').read_text())['state']=='complete'
    lo.cleanup_intermediates(root,out,products)  # recovery/idempotence
    assert len(json.loads((root/'cleanup.json').read_text())['removed'])==2


def test_incomplete_publication_recovers_from_frozen_prepared_records(tmp_path,monkeypatch):
    root,out,plan,cells,frame=prepare_month(tmp_path)
    original=lo.os.replace;counter=0
    def fail(source,target):
        nonlocal counter
        if str(target).endswith('liveocean-oxygen-r6-daily.parquet'):
            raise OSError('publication interruption')
        return original(source,target)
    monkeypatch.setattr(lo.os,'replace',fail)
    with pytest.raises(OSError,match='interruption'):lo.assemble(root,out,plan,cells,['2013-01'])
    assert (root/'publication-prepared.json').exists() and (root/'months/2013-01.parquet').exists()
    monkeypatch.setattr(lo.os,'replace',original)
    products=lo.assemble(root,out,plan,cells,['2013-01'])
    assert all(sha(out/p['path'])==p['sha256'] for p in products)


def test_cleanup_rejects_unverified_output_and_unregistered_files(tmp_path):
    root,out,plan,cells,frame=prepare_month(tmp_path);products=lo.assemble(root,out,plan,cells,['2013-01'])
    unknown=root/'sources/user.txt';unknown.write_text('unique user source')
    with pytest.raises(ValueError,match='Unexpected'):lo.cleanup_intermediates(root,out,products)
    assert unknown.exists() and (root/'months/2013-01.parquet').exists()
    (out/products[0]['path']).write_bytes(b'bad')
    with pytest.raises(ValueError,match='Published'):lo.cleanup_intermediates(root,out,products)


def test_wrong_work_root_is_never_repurposed(tmp_path):
    (tmp_path/'precious').write_text('keep')
    with pytest.raises(ValueError,match='empty'):
        lo.run('missing','missing','missing',tmp_path,'2013-01-01','2013-01-02')
    assert (tmp_path/'precious').read_text()=='keep'
