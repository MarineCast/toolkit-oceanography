import datetime as dt
import pytest
from oceanography.tide_events import events,daily_events

def test_multiplicity_utc_local_day_and_dst_fold():
    p={'predictions':[{'t':'2024-11-03 08:30','type':'H'},{'t':'2024-11-03 09:30','type':'H'},{'t':'2024-11-03 12:30','type':'L'}]}
    p['predictions'].insert(0,{'t':'2024-11-02 23:00','type':'L'});p['predictions'].append({'t':'2024-11-04 01:00','type':'H'})
    r=events(p,'noaa','2024-11-03','2024-11-03');v=daily_events(r,dt.date(2024,11,3),'America/Los_Angeles')
    assert len(v[0])==2 and v[2]==['2024-11-03T01:30:00-07:00','2024-11-03T01:30:00-08:00']
    assert daily_events(r,dt.date(2024,11,4),'America/Los_Angeles')==[[],[],[],[]]

def test_chs_requires_brackets_and_strict_extrema():
    p=[{'eventDate':t,'value':v} for t,v in [('2024-06-30T20:00Z',0),('2024-07-01T06:00Z',2),('2024-07-01T18:00Z',0),('2024-07-02T06:00Z',2)]]
    assert [k for _,k in events(p,'chs','2024-07-01','2024-07-01')]==['H','L']
    with pytest.raises(ValueError):events(p[1:],'chs','2024-07-01','2024-07-01')
    p[1]['value']=0
    with pytest.raises(ValueError):events(p,'chs','2024-07-01','2024-07-01')

def test_source_failure_and_duplicate():
    with pytest.raises(ValueError):events({'error':'unavailable'},'noaa','2024-07-01','2024-07-01')
    p={'predictions':[{'t':'2024-07-01 10:00','type':'H'}]*2}
    with pytest.raises(ValueError):events(p,'noaa','2024-07-01','2024-07-01')

def test_seascape_checksum_binds_filename_and_bytes(tmp_path):
    import hashlib
    from oceanography.tide_events import support_checksum
    p=tmp_path/'support.parquet';p.write_bytes(b'fixture')
    assert support_checksum(p)==hashlib.sha256(b'support.parquetfixture').hexdigest()
