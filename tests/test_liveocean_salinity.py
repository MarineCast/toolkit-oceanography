import datetime as dt
import json
import pandas as pd
import numpy as np
import pytest
from oceanography import liveocean_salinity as ls
from oceanography.daily import sha
from oceanography.history import atomic_json


def frame():
    return pd.DataFrame({'date':[dt.date(2013,1,1)]*3,'h3_index':['a','b','c'],'reference_salinity_g_kg':[0.,30.,31.]})


def test_extension_overlap_preserves_zero_and_checks_all_retained_values():
    old=frame();old.loc[2,'reference_salinity_g_kg']=np.nan
    assert ls.overlap_check(frame(),old)==2
    changed=frame();changed.loc[0,'reference_salinity_g_kg']=1.
    with pytest.raises(ValueError,match='changed retained'):ls.overlap_check(changed,old)
    with pytest.raises(ValueError,match='Duplicate'):ls.overlap_check(frame(),pd.concat([old,old]))


def test_native_old_partition_dates_and_checkpoint_provenance(tmp_path):
    out=tmp_path/'out';out.mkdir();(out/'provenance').mkdir();path=out/'2013-01.parquet';frame().to_parquet(path,index=False)
    assert len(ls.old_month(path,[dt.date(2013,1,1)]))==3
    assert ls.old_month(path,[dt.date(2014,1,1)]).empty
    record={'month':'2013-01','plan_sha256':'plan','product':{'path':path.name,'sha256':sha(path)}}
    atomic_json(out/'provenance/2013-01.json',record)
    assert ls.accept(out,'2013-01','plan')==record
    with pytest.raises(ValueError,match='plan changed'):ls.accept(out,'2013-01','different')
    path.write_bytes(b'changed')
    with pytest.raises(ValueError,match='partition changed'):ls.accept(out,'2013-01','plan')


def test_extension_cleanup_requires_manifest_and_final_products(tmp_path):
    root=tmp_path/'work';out=tmp_path/'out'
    root.mkdir();out.mkdir()
    for name in ['sources','cleanup']:(root/name).mkdir()
    (out/'provenance').mkdir();atomic_json(root/'plan.json',{'test':True})
    path=out/'2013-01.parquet';frame().to_parquet(path,index=False)
    record={'month':'2013-01','plan_sha256':sha(root/'plan.json'),'product':{'path':path.name,'sha256':sha(path)}}
    atomic_json(out/'provenance/2013-01.json',record)
    manifest={'products':[record['product']],'provenance':[{'path':'provenance/2013-01.json','sha256':sha(out/'provenance/2013-01.json')}]}
    atomic_json(out/'manifest.json',manifest)
    atomic_json(root/'complete.json',{'manifest_sha256':sha(out/'manifest.json')})
    raw=root/'sources/object-0-100-4.bin';raw.write_bytes(b'data')
    (out/'manifest.json').write_text('changed')
    with pytest.raises(ValueError,match='manifest changed'):ls.cleanup(root,out,[record])
    assert raw.exists()
    atomic_json(out/'manifest.json',manifest);ls.cleanup(root,out,[record]);assert not raw.exists()
    ls.cleanup(root,out,[record]);assert json.loads((root/'cleanup/final.json').read_text())['state']=='complete'
