import datetime,json
import numpy as np
import pytest
pytest.importorskip('numcodecs')
from oceanography.glorys_history import Cache,aggregate
from oceanography.daily import sha

def test_offline_cache_validates_bytes_key_url_and_digest(tmp_path):
    path=tmp_path/'so-2.49.96.41';path.write_bytes(b'abc');rec={'key':'so/2.49.96.41','url':'https://example.test/so/2.49.96.41','bytes':3,'sha256':sha(path)}
    (tmp_path/(path.name+'.receipt.json')).write_text(json.dumps(rec));cache=Cache(tmp_path,'https://example.test',True)
    assert cache.fetch(rec['key'])==b'abc';assert cache.network_requests==0;assert cache.reused_objects==1
    path.write_bytes(b'abd')
    with pytest.raises(ValueError,match='mismatch'):cache.fetch(rec['key'])
    with pytest.raises(FileNotFoundError):cache.fetch('uo/2.49.96.41')

def test_spatial_vector_magnitude_and_pairwise_missingness():
    frame=aggregate(datetime.date(2024,7,1),['a','b','c'],np.array(['a','a','b']),np.ones(3),np.array([30.,32.,np.nan]),np.array([1.,-1.,1.]),np.array([0.,0.,np.nan]))
    assert frame.loc[0,'salinity_psu']==31
    assert frame.loc[0,'current_east_m_s']==0
    assert frame.loc[0,'current_daily_mean_vector_speed_m_s']==1
    assert frame.iloc[1,2:].isna().all();assert frame.iloc[2,2:].isna().all()
