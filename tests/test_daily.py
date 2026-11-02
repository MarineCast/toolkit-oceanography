import datetime as dt
import json
from pathlib import Path
import h3
import numpy as np
import pandas as pd
import pytest
import xarray as xr
from oceanography.daily import SOURCES, Cache, aggregate, validate_frame, publish, recover, sha, study_inputs

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

def test_mur_land_exclusion_and_full_membership(tmp_path):
    p,s,c=source(tmp_path)
    f,d=aggregate(p,s,dt.date(2024,7,1),c,[-123.,48.,-122.99,48.01])
    assert list(f)==['date','h3_index','sst_c']
    assert f.sst_c.notna().sum()==1
    assert f.sst_c.dropna().iloc[0]==pytest.approx(20.,abs=.01)
    assert d['valid_native_pixels']==2
    validate_frame(f,s,[dt.date(2024,7,1)],c)

def test_chlorophyll_missing_and_positive_only(tmp_path):
    p,s,c=source(tmp_path,'chlorophyll')
    f,d=aggregate(p,s,dt.date(2024,7,1),c,[-123.,48.,-122.99,48.01])
    assert d['valid_native_pixels']==2
    assert f.chlorophyll_mg_m3.isna().sum()==1
    assert 1<=f.chlorophyll_mg_m3.dropna().iloc[0]<=3

def test_nearest_day_and_wrong_bounds_rejected(tmp_path):
    p,s,c=source(tmp_path)
    with pytest.raises(ValueError,match='date/time'): aggregate(p,s,dt.date(2024,7,2),c,[-123.,48.,-122.99,48.01])
    with pytest.raises(ValueError,match='bounds'): aggregate(p,s,dt.date(2024,7,1),c,[-124.,48.,-122.99,48.01])

def test_public_identity_and_schema_rejected(tmp_path):
    p,s,c=source(tmp_path); day=dt.date(2024,7,1)
    f,_=aggregate(p,s,day,c,[-123.,48.,-122.99,48.01])
    with pytest.raises(ValueError,match='identity'): validate_frame(f.iloc[::-1],s,[day],c)
    with pytest.raises(ValueError,match='schema'): validate_frame(f.assign(status='ok'),s,[day],c)

def test_cache_tamper_and_offline_missing(tmp_path):
    cache=Cache(tmp_path,True)
    with pytest.raises(ValueError,match='Missing offline'): cache.get('https://example.test','.nc')
    import hashlib
    key=hashlib.sha256(b'https://example.test').hexdigest()
    p=tmp_path/(key+'.nc'); p.write_bytes(b'original')
    (tmp_path/(key+'.json')).write_text(json.dumps({'url':'https://example.test','sha256':sha(p)}))
    p.write_bytes(b'tampered')
    with pytest.raises(ValueError,match='checksum'): cache.get('https://example.test','.nc')

def test_failed_publish_preserves_previous(tmp_path,monkeypatch):
    import oceanography.daily as d
    output=tmp_path/'output'; output.mkdir(); (output/'old').write_text('original')
    stage=tmp_path/'stage'; stage.mkdir(); (stage/'new').write_text('new')
    work=tmp_path/'work'; work.mkdir(); replace=d.os.replace
    def fail(src,dst):
        if Path(src)==stage: raise OSError('interrupted')
        return replace(src,dst)
    monkeypatch.setattr(d.os,'replace',fail)
    with pytest.raises(OSError): publish(stage,output,work)
    assert (output/'old').read_text()=='original'

def test_recover_interrupted_directory_swap(tmp_path):
    work=tmp_path/'work'; work.mkdir(); backup=work/'previous'; backup.mkdir(); (backup/'old').write_text('old')
    output=tmp_path/'output'
    (work/'publication.json').write_text(json.dumps({'state':'prepared','backup':str(backup)}))
    recover(output,work)
    assert (output/'old').read_text()=='old'

def test_study_membership_tamper(tmp_path):
    # A declared approved registry cannot bypass checksum qualification.
    mask=tmp_path/'mask'; mask.write_text('mask'); manifest=tmp_path/'manifest'; manifest.write_text('manifest')
    membership=tmp_path/'cells'; membership.write_text('tampered')
    config={'domain':{'status':'approved','revision':'v1'},'grid_registry':{'status':'validated','mask_revision':'v1','mask_relative_path':'mask','mask_sha256':sha(mask),'manifest_relative_path':'manifest','manifest_sha256':sha(manifest),'memberships':[{'resolution':5,'role':'water_reporting','relative_path':'cells','sha256':'bad'}]}}
    p=tmp_path/'study.json'; p.write_text(json.dumps(config))
    with pytest.raises(ValueError,match='Membership checksum'): study_inputs(p)
