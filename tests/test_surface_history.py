import datetime as dt
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from oceanography import surface_history as sh
from oceanography.daily import sha
from oceanography.history import atomic_json


def context():
    return {'cells':['a','b','c','x'],'bounds':[5,6,8,9],'shape':(2,2),
            'ids':np.array(['a','a','b','c']),'weights':np.array([1.,2.,1.,1.]),
            'masks':{n:np.ones(4,bool) for n in sh.rf.FIELDS},'evidence':{'test':'synthetic'}}


def test_narrow_request_preserves_every_native_point_of_selected_cell():
    ctx=context();narrow=sh.target_context(ctx,'salinity',['a'])
    assert narrow['bounds']==[5,5,8,9]
    assert narrow['ids'].tolist()==['a','a']
    assert narrow['weights'].tolist()==[1.,2.]
    assert narrow['masks']['salinity'].sum()==2
    assert sh.target_context(ctx,'salinity',['x']) is None


def test_fast_selection_preserves_zero_and_uses_ssc_only_for_missing():
    lo=sh.blank([dt.date(2013,1,1)],['a','b','c','x'],'salinity');ssc=lo.copy()
    lo.iloc[:,2]=[0.,np.nan,5.,np.nan];ssc.iloc[:,2]=[9.,3.,8.,np.nan]
    result,source=sh.combine(lo,ssc,'salinity')
    np.testing.assert_allclose(result.iloc[:,2],[0,3,5,np.nan],equal_nan=True)
    assert source.tolist()==['liveocean','salishseacast','liveocean','unavailable']
    with pytest.raises(AssertionError):sh.combine(lo,ssc.iloc[::-1],'salinity')


def test_existing_daily_lo_read_preserves_targets_and_invalid_values(tmp_path):
    name='salinity';metric=sh.rf.FIELDS[name][4];ctx=context()
    days=[dt.date(2013,1,1),dt.date(2013,1,2)]
    path=tmp_path/'lo.parquet';frame=sh.blank(days,ctx['cells'],name)
    frame[metric]=[0,-1,30,20,51,2,3,9]
    with pq.ParquetWriter(path,pa.Schema.from_pandas(frame,preserve_index=False)) as w:
        for _,g in frame.groupby('date'):w.write_table(pa.Table.from_pandas(g,preserve_index=False))
    bindings={'liveocean-salinity':{'absolute_path':str(path)}}
    result=sh.lo_values(bindings,'fast',name,days,ctx)
    np.testing.assert_allclose(result[metric],[0,np.nan,30,np.nan,np.nan,2,3,np.nan],equal_nan=True)
    assert sh.lo_values({},'complete',name,days,ctx)[metric].isna().all()
    assert sh.lo_values(bindings,'fast',name,[dt.date(2009,1,1)],ctx)[metric].isna().all()


def test_validate_rejects_duplicate_or_reordered_h3_identity():
    days=[dt.date(2013,1,1)];frame=sh.blank(days,['a','b'],'oxygen')
    sh.validate(frame,days,['a','b'],[sh.rf.FIELDS['oxygen'][4]])
    with pytest.raises(ValueError,match='identity'):sh.validate(frame.iloc[::-1],days,['a','b'],[sh.rf.FIELDS['oxygen'][4]])


def test_salinity_extension_fills_retention_omissions_without_changing_old_values(tmp_path):
    days=[dt.date(2013,1,1)];ctx=context();old=sh.blank(days,ctx['cells'],'salinity');old.iloc[:,2]=[0.,np.nan,30.,np.nan]
    old_path=tmp_path/'old.parquet';old.to_parquet(old_path,index=False)
    extra=old.copy();extra.iloc[:,2]=[0.,25.,30.,20.];extra.to_parquet(tmp_path/'2013-01.parquet',index=False)
    bindings={'liveocean-salinity':{'absolute_path':str(old_path)},'liveocean-regional-salinity':{'manifest_path':str(tmp_path/'manifest.json')}}
    result=sh.lo_values(bindings,'fast','salinity',days,ctx)
    np.testing.assert_allclose(result.reference_salinity_g_kg,[0.,25.,30.,np.nan],equal_nan=True)
    extra.loc[0,'reference_salinity_g_kg']=1.;extra.to_parquet(tmp_path/'2013-01.parquet',index=False)
    with pytest.raises(ValueError,match='changed retained'):sh.lo_values(bindings,'fast','salinity',days,ctx)


def prepared_fixture(tmp_path):
    root=tmp_path/'work';output=tmp_path/'output';root.mkdir();output.mkdir()
    for name in ['staging','prepared','checkpoints','cleanup','sources']:(root/name).mkdir()
    atomic_json(root/'plan.json',{'mode':'fast'})
    payload=b'owned hourly';url='https://example.test/field';key=hashlib.sha256(url.encode()).hexdigest()
    path=root/'sources'/(key+'.gz');path.write_bytes(payload)
    stage=root/'staging/salinity-2013-01.parquet.part';stage.write_bytes(b'checked final H3')
    product={'path':'salinity/2013-01.parquet','sha256':sha(stage)}
    receipt={'url':url,'compressed_sha256':sha(path),'compressed_bytes':len(payload)}
    record={'month':'2013-01','products':[product],'sources':[receipt]}
    prepared={'plan_sha256':sha(root/'plan.json'),'record':record}
    atomic_json(root/'prepared/2013-01.json',prepared)
    return root,output,path,prepared


def test_publication_recovery_after_move_and_checksum_gated_eviction(tmp_path):
    root,out,path,prepared=prepared_fixture(tmp_path)
    (out/'salinity').mkdir();(root/'staging/salinity-2013-01.parquet.part').rename(out/'salinity/2013-01.parquet')
    record=sh.accepted(root,out,'2013-01')
    assert record==prepared['record'] and path.exists()
    provenance=out/'provenance/2013-01.json';original=provenance.read_bytes();provenance.write_bytes(b'changed')
    with pytest.raises(ValueError,match='Provenance'):sh.evict(root,out,record)
    assert path.exists()
    provenance.write_bytes(original);sh.evict(root,out,record);assert not path.exists()
    sh.evict(root,out,record)
    assert json.loads((root/'cleanup/2013-01.json').read_text())['state']=='complete'
    (out/'salinity/2013-01.parquet').write_bytes(b'corrupt')
    with pytest.raises(ValueError,match='product changed'):sh.accepted(root,out,'2013-01')


def test_source_change_blocks_eviction(tmp_path):
    root,out,path,prepared=prepared_fixture(tmp_path)
    record=sh.finish_publication(root,out,'2013-01',prepared);path.write_bytes(b'different')
    with pytest.raises(ValueError,match='source changed'):sh.evict(root,out,record)
    assert path.exists()


def test_reused_owned_cache_eviction_requires_owner_and_final_proof(tmp_path):
    root,out,path,prepared=prepared_fixture(tmp_path);prior=tmp_path/'previous';(prior/'sources').mkdir(parents=True)
    moved=prior/'sources'/path.name;path.rename(moved)
    atomic_json(prior/'ownership.json',{'pipeline':'unrelated'})
    atomic_json(root/'plan.json',{'shared_source_roots':[str(moved.parent)]})
    prepared['plan_sha256']=sha(root/'plan.json');prepared['record']['sources'][0]['reused_source_path']=str(moved)
    record=sh.finish_publication(root,out,'2013-01',prepared)
    with pytest.raises(ValueError,match='owner changed'):sh.evict(root,out,record)
    assert moved.exists()
    atomic_json(prior/'ownership.json',{'pipeline':'surface-history'});sh.evict(root,out,record)
    assert not moved.exists() and (out/'salinity/2013-01.parquet').exists()


def test_source_availability_respects_padding_and_detects_missing_hour(monkeypatch):
    axis=pd.date_range('2008-12-31T00:30Z','2009-01-04T23:30Z',freq='h')
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def raise_for_status(self):pass
        def iter_content(self,*args):yield ('time\nUTC\n'+'\n'.join(str(t) for t in axis)).encode()
    monkeypatch.setattr(sh.requests,'get',lambda *a,**k:Response())
    end,receipts=sh.source_availability(dt.date(2009,1,1),dt.date(2009,1,4))
    assert end==dt.date(2009,1,3) and len(receipts)==3
    axis=axis.delete(55)
    with pytest.raises(ValueError,match='Missing historical'):sh.source_availability(dt.date(2009,1,1),dt.date(2009,1,4))


def test_monthly_driver_resume_needs_no_sources_and_rejects_changed_mode(tmp_path,monkeypatch):
    ctx=context();root=tmp_path/'work';out=tmp_path/'out'
    monkeypatch.setattr(sh.rf,'context',lambda *a:ctx)
    monkeypatch.setattr(sh,'existing_bindings',lambda *a:{})
    monkeypatch.setattr(sh,'source_availability',lambda a,b:(b,{'test':'axis'}))
    def lo(bindings,mode,name,days,context):
        frame=sh.blank(days,ctx['cells'],name)
        if mode=='fast':frame.loc[frame.h3_index=='a',sh.rf.FIELDS[name][4]]=0.
        return frame
    monkeypatch.setattr(sh,'lo_values',lo)
    def acquire(work,budget,name,start,end,bounds,offline,read_timeout,reuse_sources):
        assert not offline
        assert read_timeout==600
        url='https://example.test/'+name;key=hashlib.sha256(url.encode()).hexdigest();path=work/'sources'/(key+'.gz')
        path.write_bytes(b'hourly-'+name.encode())
        return path,{'url':url,'field':name,'compressed_bytes':path.stat().st_size,'compressed_sha256':sha(path)}
    monkeypatch.setattr(sh.rf,'acquire',acquire)
    def filtered(path,name,start,end,days,context,reference):
        frame=sh.blank(days,context['cells'],name)
        frame.loc[frame.h3_index.isin(context['ids'][context['masks'][name]]),sh.rf.FIELDS[name][4]]=4.
        return {'native1230':frame},{'field':name,'direct_matrix_reference':False,'reference_max_absolute_difference':0.}
    monkeypatch.setattr(sh.rf,'filter_source',filtered)
    args=('', '', '', '', tmp_path/'existing',out,root,'fast','2013-01-01','2013-01-02')
    result=sh.run(*args);assert result['status']=='complete'
    source=pd.read_parquet(out/'sources/2013-01.parquet')
    assert source.loc[source.h3_index=='a','salinity_source'].eq('liveocean').all()
    assert source.loc[source.h3_index=='b','salinity_source'].eq('salishseacast').all()
    assert not any((root/'sources').iterdir())
    def network(*a,**k):raise AssertionError('Completed replay attempted acquisition')
    monkeypatch.setattr(sh.rf,'acquire',network);monkeypatch.setattr(sh,'source_availability',network)
    assert sh.run(*args,offline=True)['status']=='complete'
    (root/'PAUSE').write_text('pause')
    assert sh.run(*args,offline=True)['status']=='complete'
    assert len(json.loads((out/'manifest.json').read_text())['completed_months'])==1
    changed=list(args);changed[7]='complete'
    with pytest.raises(ValueError,match='Frozen'):sh.run(*changed,offline=True)
