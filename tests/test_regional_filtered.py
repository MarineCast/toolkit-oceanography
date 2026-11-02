import datetime as dt
import json
import gzip
import numpy as np
import pandas as pd
import pytest
from oceanography import regional_filtered as rf
from oceanography.daily import sha
from oceanography.history import atomic_json


def fixture():
    times=pd.date_range('2012-12-30T00:30Z','2013-01-02T23:30Z',freq='h')
    days=[dt.date(2012,12,31),dt.date(2013,1,1)]
    ctx={'cells':['a','b','c'],'ids':np.array(['a','b']),'weights':np.array([1.,2.]),
         'masks':{n:np.ones(2,bool) for n in rf.FIELDS}}
    return times,days,ctx


def test_godin_polynomial_equivalence_symmetry_and_tidal_rejection():
    w=rf.godin_weights();k=np.arange(12);p=np.full(71,np.nan)
    p[35:47]=(.5/(24*24*25))*(1200-(12-k)*(13-k)-(12+k)*(13+k))
    k=np.arange(12,36);p[47:71]=(.5/(24*24*25))*(36-k)*(37-k);p[:35]=p[:35:-1]
    assert len(w)==71 and np.all(w>0) and abs(w.sum()-1)<1e-15
    np.testing.assert_allclose(w,p,atol=1e-16,rtol=0)
    np.testing.assert_allclose(w,w[::-1],atol=1e-16,rtol=0)
    for period in [12,24,25]:assert abs(np.sum(w*np.exp(2j*np.pi*np.arange(-35,36)/period)))<1e-14


def test_half_hour_centres_and_effective_72_sample_noon_rule():
    times,days,_=fixture();w=rf.window_weights(times,days)
    for i,day in enumerate(days):
        hours=(times-pd.Timestamp(f'{day}T12:00Z')).total_seconds().to_numpy()/3600
        assert np.count_nonzero(w[i,0])==np.count_nonzero(w[i,1])==71
        assert np.count_nonzero(w[i,2])==72
        np.testing.assert_allclose(w[i]@hours,[-.5,.5,0],atol=1e-14)
        np.testing.assert_allclose(w[i].sum(axis=1),1.,atol=1e-15)
        assert len(times)==96


def test_missing_duplicated_or_shifted_hours_fail():
    times,days,_=fixture()
    with pytest.raises(ValueError,match='Missing'):rf.window_weights(times.delete(40),days)
    with pytest.raises(ValueError,match='Missing'):rf.window_weights(times.insert(1,times[0]),days)
    with pytest.raises(ValueError,match='HH:30'):rf.window_weights(times+pd.Timedelta(minutes=30),days)
    with pytest.raises(ValueError,match='padded'):rf.window_weights(times[1:],days)


def test_streaming_ramp_reference_year_boundary_exact_timing():
    times,days,ctx=fixture();hours=(times-times[0]).total_seconds().to_numpy()/3600
    arrays=[np.array([[100+h,0.]],dtype='>f4') for h in hours]
    frames,diag=rf.reduce_hourly(iter(arrays),times,days,ctx,'oxygen',True)
    for phase,offset in [('native1130',35),('native1230',36),('noon_interpolated',35.5)]:
        np.testing.assert_allclose(frames[phase].loc[frames[phase].h3_index=='a','dissolved_oxygen_mmol_m3'],[100+offset,124+offset],atol=1e-12)
        assert (frames[phase].loc[frames[phase].h3_index=='b','dissolved_oxygen_mmol_m3']==0).all()
        assert frames[phase].loc[frames[phase].h3_index=='c','dissolved_oxygen_mmol_m3'].isna().all()
    assert diag['reference_max_absolute_difference']<1e-10
    assert len(diag['days'])==2


def test_invalid_extra_endpoint_only_affects_windows_that_use_it():
    times,days,ctx=fixture();arrays=[np.array([[5.,0.]],dtype='>f4') for _ in times];arrays[0][0,0]=np.nan
    frames,diag=rf.reduce_hourly(iter(arrays),times,days,ctx,'oxygen',True)
    assert np.isnan(frames['native1130'].iloc[0].dissolved_oxygen_mmol_m3)
    assert frames['native1230'].iloc[0].dissolved_oxygen_mmol_m3==pytest.approx(5.)
    assert np.isnan(frames['noon_interpolated'].iloc[0].dissolved_oxygen_mmol_m3)
    assert diag['days'][0]['native_complete_points']['native1230']==2
    assert diag['days'][0]['native_complete_points']['noon_interpolated']==1


def test_month_boundary_streaming_same_as_independent_reference():
    times=pd.date_range('2013-01-30T00:30Z','2013-02-02T23:30Z',freq='h')
    _,_,ctx=fixture();days=[dt.date(2013,1,31),dt.date(2013,2,1)]
    rng=np.random.default_rng(4);arrays=[v.reshape(1,2).astype('>f4') for v in rng.uniform(2,30,(96,2))]
    frames,d=rf.reduce_hourly(iter(arrays),times,days,ctx,'salinity',True)
    assert frames['native1230'].date.unique().tolist()==days
    assert d['reference_max_absolute_difference']<1e-12


def test_incomplete_stream_never_emits_success():
    times,days,ctx=fixture();arrays=[np.ones((1,2)) for _ in times[:-1]]
    with pytest.raises(ValueError,match='Incomplete'):rf.reduce_hourly(iter(arrays),times,days,ctx,'nitrate')


def test_cleanup_requires_products_and_provenance_and_preserves_external(tmp_path):
    root=tmp_path/'work';out=tmp_path/'out';(root/'sources').mkdir(parents=True);(root/'receipts').mkdir();out.mkdir()
    source=root/'sources/input.gz';source.write_bytes(b'owned input');atomic_json(root/'receipts/input.json',{'compressed_sha256':sha(source)})
    final=out/'final.parquet';final.write_bytes(b'final H3');products=[{'path':final.name,'sha256':sha(final)}]
    prov=out/'provenance.json';prov.write_text('{}');atomic_json(root/'complete.json',{'provenance_sha256':sha(prov)})
    external=tmp_path/'external.nc';external.write_bytes(b'unique geometry')
    prov.write_text('{"changed":true}')
    with pytest.raises(ValueError,match='provenance'):rf.cleanup(root,out,products)
    assert source.exists()
    prov.write_text('{}');rf.cleanup(root,out,products)
    assert not source.exists() and external.exists() and final.exists()
    rf.cleanup(root,out,products)
    assert json.loads((root/'cleanup.json').read_text())['state']=='complete'


def test_cleanup_rejects_unregistered_source(tmp_path):
    root=tmp_path/'work';out=tmp_path/'out';(root/'sources').mkdir(parents=True);(root/'receipts').mkdir();out.mkdir()
    (root/'sources/user.gz').write_bytes(b'keep');(out/'provenance.json').write_text('{}')
    atomic_json(root/'complete.json',{'provenance_sha256':sha(out/'provenance.json')})
    with pytest.raises(ValueError,match='Unregistered'):rf.cleanup(root,out,[])
    assert (root/'sources/user.gz').exists()


def test_foreign_work_root_is_not_overwritten(tmp_path):
    (tmp_path/'user.txt').write_text('keep')
    with pytest.raises(ValueError,match='empty'):rf.run('','','','','',tmp_path,'2013-01-01','2013-01-02')
    assert (tmp_path/'user.txt').read_text()=='keep'


def test_real_netcdf_surface_layout_units_and_gzip_replay(tmp_path):
    import xarray as xr
    times,days,ctx=fixture();ctx['shape']=(1,2);ctx['bounds']=[1,1,1,2]
    raw=tmp_path/'source.nc';compressed=tmp_path/'source.gz'
    ds=xr.Dataset({'salinity':(('time','depth','gridY','gridX'),np.full((96,1,1,2),10.,dtype='float32'))},
        coords={'time':times.as_unit('s').asi8.astype(float),'depth':np.array([.5000003],dtype='float32'),'gridY':[1],'gridX':[1,2]})
    ds.time.attrs={'units':'seconds since 1970-01-01T00:00:00Z','calendar':'gregorian'}
    ds.depth.attrs={'units':'m','positive':'down'}
    ds.salinity.attrs={'units':'g kg-1','standard_name':'sea_water_reference_salinity'}
    ds.to_netcdf(raw,engine='scipy',format='NETCDF3_64BIT')
    with gzip.open(compressed,'wb') as f:f.write(raw.read_bytes())
    frames,diag=rf.filter_source(compressed,'salinity','2012-12-30','2013-01-02',days,ctx,True)
    np.testing.assert_allclose(frames['native1230'].loc[:1,'reference_salinity_g_kg'],10.)
    assert diag['reference_max_absolute_difference']<1e-12
    ds.salinity.attrs['units']='psu';ds.to_netcdf(raw,engine='scipy',format='NETCDF3_64BIT')
    with gzip.open(compressed,'wb') as f:f.write(raw.read_bytes())
    with pytest.raises(ValueError,match='convention'):rf.inspect(compressed,'salinity','2012-12-30','2013-01-02',ctx['bounds'])


def test_preparation_timeout_does_not_poison_next_prepared_response(tmp_path,monkeypatch):
    import io
    import xarray as xr
    times,days,ctx=fixture();raw=tmp_path/'fixture.nc'
    ds=xr.Dataset({'salinity':(('time','depth','gridY','gridX'),np.ones((96,1,1,2),dtype='float32'))},coords={
        'time':times.as_unit('s').asi8.astype(float),'depth':np.array([.5000003],dtype='float32'),'gridY':[1],'gridX':[1,2]})
    ds.time.attrs={'units':'seconds since 1970-01-01T00:00:00Z','calendar':'gregorian'}
    ds.depth.attrs={'units':'m','positive':'down'};ds.salinity.attrs={'units':'g kg-1','standard_name':'sea_water_reference_salinity'}
    ds.to_netcdf(raw,engine='scipy',format='NETCDF3_64BIT');payload=gzip.compress(raw.read_bytes())
    state={'now':0.,'calls':0};monkeypatch.setattr(rf.time,'monotonic',lambda:state['now']);monkeypatch.setattr(rf.time,'sleep',lambda *a:None)
    class Response:
        headers={'Content-Encoding':'gzip'}
        def __init__(self):self.raw=io.BytesIO(payload)
        def __enter__(self):state['now']=602.;return self
        def __exit__(self,*a):pass
        def raise_for_status(self):pass
    def get(*a,**kw):
        state['calls']+=1
        if state['calls']==1:
            state['now']=601.;raise rf.requests.ReadTimeout('server still preparing')
        return Response()
    monkeypatch.setattr(rf.requests,'get',get)
    root=tmp_path/'work';(root/'sources').mkdir(parents=True);(root/'receipts').mkdir()
    path,receipt=rf.acquire(root,rf.Budget(root/'sources'),'salinity','2012-12-30','2013-01-02',[1,1,1,2],read_timeout=600)
    assert path.exists() and receipt['attempts']==2 and receipt['seconds']==602.
    assert receipt['response_seconds']==1. and receipt['decoded_bytes']==raw.stat().st_size
    atomic_json(root/'ownership.json',{'pipeline':'surface-history'})
    next_root=tmp_path/'next';(next_root/'sources').mkdir(parents=True);(next_root/'receipts').mkdir()
    def no_network(*args,**kwargs):raise AssertionError('Reused native payload attempted acquisition')
    monkeypatch.setattr(rf.requests,'get',no_network)
    reused,r=rf.acquire(next_root,rf.Budget(next_root/'sources',[root/'sources']),'salinity','2012-12-30','2013-01-02',[1,1,1,2],offline=True,reuse_sources=[root/'sources'])
    assert reused==path and r['reused_source_path']==str(path)
    assert not any((next_root/'sources').iterdir())
