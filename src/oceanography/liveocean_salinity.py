"""Regional salt-only extension of retained LiveOcean H3 salinity support."""
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import fcntl
import importlib.metadata
import json
import os
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from . import liveocean as lo
from .daily import sha,study_inputs
from .history import atomic_json
from .surface_history import blank,validate

METRIC='reference_salinity_g_kg'


def overlap_check(frame,old):
    require=lo.require
    require(not old.duplicated(['date','h3_index']).any(),'Duplicate retained LO salinity')
    paired=frame.merge(old,on=['date','h3_index'],how='left',suffixes=('_new','_old'),validate='one_to_one')
    values=paired[METRIC+'_old'].notna()
    require(np.array_equal(paired.loc[values,METRIC+'_new'],paired.loc[values,METRIC+'_old']),
            'Regional extension changed retained LO salinity')
    return int(values.sum())


def old_month(path,days):
    f=pq.ParquetFile(path);groups=[]
    for i in range(f.num_row_groups):
        stats=f.metadata.row_group(i).column(0).statistics
        lo.require(stats is not None and stats.has_min_max,'Old LO date statistics missing')
        if stats.max>=days[0] and stats.min<=days[-1]:groups.append(i)
    if not groups:return pd.DataFrame(columns=['date','h3_index',METRIC])
    result=f.read_row_groups(groups).to_pandas();return result[result.date.isin(days)]


def accept(output,month,plan_sha):
    p=output/'provenance'/(month+'.json')
    if not p.exists():return None
    r=json.loads(p.read_text());lo.require(r['plan_sha256']==plan_sha,'Extension checkpoint plan changed')
    lo.require(sha(output/r['product']['path'])==r['product']['sha256'],'Extension final partition changed')
    return r


def index(output,plan,records,status):
    value={'schema_version':1,'status':status,'source_model':'LiveOcean cas7_t0_x4b','metric':METRIC,'units':'g kg-1','h3_resolution':6,
           'date_start':plan['start'],'date_end':plan['end'],'plan':plan,'temporal_support':'71-hour Godin low-pass centred on daily noon label',
           'products':[r['product'] for r in records],
           'provenance':[{'path':'provenance/'+r['month']+'.json','sha256':sha(output/'provenance'/(r['month']+'.json'))} for r in records],
           'forecast_eligible':False,'model_eligible':False}
    atomic_json(output/'manifest.json',value)
    return value


def cleanup(root,output,records):
    complete=json.loads((root/'complete.json').read_text())
    lo.require(sha(output/'manifest.json')==complete['manifest_sha256'],'Extension manifest changed before cleanup')
    verify_index(output)
    for r in records:accept(output,r['month'],sha(root/'plan.json'))
    ledger_path=root/'cleanup/final.json'
    old=json.loads(ledger_path.read_text()) if ledger_path.exists() else {'removed':[]}
    paths={p['path']:p for p in old['removed']}
    for p in (root/'sources').iterdir():
        lo.require(p.is_file() and not p.is_symlink() and re.fullmatch(r'object-[01]-\d+-\d+\.(json|bin)',p.name),'Unexpected extension staging source')
        paths[str(p)]={'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
    ledger={'state':'prepared','manifest_sha256':complete['manifest_sha256'],'removed':list(paths.values())};atomic_json(ledger_path,ledger)
    for p in ledger['removed']:
        path=Path(p['path']);lo.require(path.parent==root/'sources','Extension cleanup escaped sources')
        if path.exists():lo.require(sha(path)==p['sha256'],'Extension source changed');path.unlink()
    ledger['state']='complete';atomic_json(ledger_path,ledger)


def verify_index(output):
    path=output/'manifest.json'
    if not path.exists():return
    value=json.loads(path.read_text())
    for product in value['products']+value['provenance']:
        lo.require(sha(output/product['path'])==product['sha256'],'Extension indexed product/provenance changed')


def run(study,support,old,output,root,start='2013-01-01',end='2024-12-31',shared=(),offline=False):
    import h5py
    root=Path(root).resolve();output=Path(output).resolve();old=Path(old).resolve()
    lo.require(root!=output and root not in output.parents and output not in root.parents,'Separate work/output roots required')
    root.mkdir(parents=True,exist_ok=True);marker=root/'ownership.json';owner={'pipeline':'liveocean-salinity-extension','output':str(output)}
    if marker.exists():lo.require(json.loads(marker.read_text())==owner,'Extension ownership mismatch')
    else:lo.require(not any(root.iterdir()),'New extension work root required');atomic_json(marker,owner)
    for n in ['sources','staging','cleanup']:(root/n).mkdir(exist_ok=True)
    output.mkdir(parents=True,exist_ok=True)
    lo.require((root/'plan.json').exists() or not any(output.iterdir()),'New extension output root must be empty')
    (output/'provenance').mkdir(exist_ok=True)
    dates=pd.date_range(start,end)
    lo.require(len(dates)>0 and dates[0]>=pd.Timestamp('2013-01-01') and dates[-1]<=pd.Timestamp('2024-12-31'),'Extension dates outside archive')
    selected=json.loads(Path(support).read_text());_,members,evidence=study_inputs(study)
    lo.require(selected['study_sha256']==evidence['study_sha256'],'Extension study mismatch')
    old_lineage=old.with_name('liveocean-lineage.json');source_lineage=json.loads(old_lineage.read_text())
    binding={'start':start,'end':end,'study':evidence,'support':selected,'support_sha256':sha(support),
             'old_salinity':{'path':str(old),'sha256':sha(old)},'source_cache_cap_bytes':lo.CAP,'output':str(output),
             'old_lineage':{'path':str(old_lineage),'sha256':sha(old_lineage)},
             'shared_source_roots':sorted(str(Path(p).resolve()) for p in shared),
             'code':{n:sha(Path(__file__).with_name(n)) for n in ['liveocean_salinity.py','liveocean.py','surface_history.py','daily.py','history.py']},
             'versions':{n:importlib.metadata.version(n) for n in ['h5py','numpy','pandas','pyarrow','h3','shapely']}}
    with (root/'run.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        verify_index(output)
        prior=json.loads((root/'plan.json').read_text()) if (root/'plan.json').exists() else None
        if prior:lo.require(all(prior[k]==v for k,v in binding.items()),'Frozen extension plan changed')
        if (root/'complete.json').exists():
            final=json.loads((root/'complete.json').read_text());lo.require(sha(output/'manifest.json')==final['manifest_sha256'],'Extension manifest changed')
            records=[accept(output,month,sha(root/'plan.json')) for month in sorted(set(dates.strftime('%Y-%m')))];cleanup(root,output,records)
            return final
        budget=lo.Budget(root/'sources',shared);archives=[];handles=[];records=[]
        try:
            sources=[];geometry=None;state=None
            for i in [0,1]:
                a=lo.Archive(i,root/'sources',budget,None,prior['sources'][i] if prior else None,offline);archives.append(a)
                f=h5py.File(a,'r');handles.append(f);lo.native_metadata(f,i);sources.append(a.binding)
                cells,_,ids,weights,masks,fp=lo.spatial(f,study,selected)
                if geometry is None:geometry=fp;state=cells,ids,weights,masks
                else:lo.require(fp==geometry,'LO archive geometry changed')
            plan={**binding,'sources':sources,'grid_sha256':geometry,'method':lo.METHOD,'field':'salt only; no oxygen/nitrate payload acquisition'}
            lo.require(sources==source_lineage['plan']['sources'],'LO objects changed since retained products')
            if prior:lo.require(prior==plan,'Extension source binding changed')
            else:atomic_json(root/'plan.json',plan)
            digest=sha(root/'plan.json');cells,ids,weights,masks=state
            for month in sorted(set(dates.strftime('%Y-%m'))):
                cohort=dates[dates.strftime('%Y-%m')==month];days=[d.date() for d in cohort]
                record=accept(output,month,digest)
                if record is None:
                    import time
                    clock=time.monotonic();i=0 if cohort[0].year<=2019 else 1;a=archives[i];f=handles[i]
                    origin=pd.Timestamp('2013-01-01' if i==0 else '2020-01-01');indices=[(d-origin).days for d in cohort]
                    ranges=lo.chunks(f,['salt'],indices)
                    with ThreadPoolExecutor(max_workers=2) as pool:payloads=list(pool.map(lambda pair:a.fetch(*pair),ranges))
                    a.ranges.extend((r['start'],r['start']+r['bytes'],p) for p,r in payloads)
                    frames=[];details=[]
                    for day,ti in zip(days,indices):
                        frame,diag=lo.aggregate(day,{'salt':f['salt'][ti,:,:]},cells,ids,weights,masks)
                        frames.append(frame);details.append({'date':str(day),'salt':diag['salt']})
                    frame=pd.concat(frames,ignore_index=True);validate(frame,days,cells,[METRIC])
                    overlap=overlap_check(frame,old_month(old,days))
                    stage=root/'staging'/(month+'.parquet.part');schema=pa.schema([('date',pa.date32()),('h3_index',pa.string()),(METRIC,pa.float64())])
                    with pq.ParquetWriter(stage,schema,compression='zstd') as writer:
                        for _,day in frame.groupby('date',sort=False):writer.write_table(pa.Table.from_pandas(day,schema=schema,preserve_index=False))
                    pd.testing.assert_frame_equal(pd.read_parquet(stage),frame,check_exact=True)
                    target=output/(month+'.parquet')
                    if target.exists():lo.require(sha(target)==sha(stage),'Conflicting extension output');stage.unlink()
                    else:os.replace(stage,target)
                    record={'month':month,'plan_sha256':digest,'product':{'path':target.name,'sha256':sha(target),'bytes':target.stat().st_size,'rows':len(frame),'start':str(days[0]),'end':str(days[-1])},
                            'sources':[r for _,r in payloads],'native_days':details,'overlap_values_exact':overlap,'seconds':time.monotonic()-clock,'source_index':i}
                    atomic_json(output/'provenance'/(month+'.json'),record)
                    # Native chunks may be removed only after final H3 and provenance acceptance.
                    lo.require(accept(output,month,digest)==record,'Extension provenance changed before source eviction')
                    lo.evict_payloads(a,payloads,{'path':str(target),'sha256':record['product']['sha256']})
                records.append(record);index(output,plan,records,'running')
                progress={'status':'running','completed_months':len(records),'total_months':len(set(dates.strftime('%Y-%m'))),'month':month,
                          'source_bytes':budget.used(),'peak_shared_budget_bytes':budget.peak,'updated_utc':dt.datetime.now(dt.timezone.utc).isoformat()}
                atomic_json(root/'progress.json',progress);print(json.dumps(progress),flush=True)
            final=index(output,plan,records,'complete')
            result={'status':'complete','months':len(records),'manifest_sha256':sha(output/'manifest.json'),'output':str(output)}
            atomic_json(root/'complete.json',result)
        finally:
            for f in handles:f.close()
            for a in archives:a.session.close()
        cleanup(root,output,records)
        return result


def main(argv=None):
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    for n in ['study','support','old','output','root']:p.add_argument('--'+n,required=True)
    p.add_argument('--start',default='2013-01-01');p.add_argument('--end',default='2024-12-31');p.add_argument('--shared-cache',action='append',default=[])
    a=p.parse_args(argv);print(json.dumps(run(a.study,a.support,a.old,a.output,a.root,a.start,a.end,a.shared_cache),indent=2));return 0
