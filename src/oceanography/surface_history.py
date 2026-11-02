"""Resumable regional fast/complete scalar history with final monthly H3 partitions."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import fcntl
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import shutil

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests

from . import regional_filtered as rf
from .daily import sha
from .history import atomic_json
from .liveocean import Budget, require
from .regional_gap_history import months
from .regional_tiles import partitions


def emit(root, status, **values):
    record={'status':status,'updated_utc':dt.datetime.now(dt.timezone.utc).isoformat(),**values}
    atomic_json(root/'progress.json',record)
    print(json.dumps(record,sort_keys=True),flush=True)


def source_availability(start, requested_end):
    """Validate every required hourly centre, retaining small receipts only."""
    axes={};receipts={};end=requested_end
    for name,(dataset,*_) in rf.FIELDS.items():
        url=f'{rf.BASE}/griddap/{dataset}.csv?time'
        with requests.get(url,timeout=(20,180),stream=True) as response:
            response.raise_for_status();parts=[];size=0
            for part in response.iter_content(65536):
                size+=len(part);require(size<=8_000_000,'Time metadata byte cap');parts.append(part)
        raw=b''.join(parts)
        axis=pd.DatetimeIndex(pd.to_datetime(pd.read_csv(io.BytesIO(raw),skiprows=[1])['time'],utc=True))
        require(len(axis)>0 and axis.is_unique and axis.is_monotonic_increasing,'Invalid source axis')
        complete=axis[-1].date()-(dt.timedelta(days=1) if axis[-1].time()!=dt.time(23,30) else dt.timedelta())
        end=min(end,complete-dt.timedelta(days=1))
        axes[name]=axis
        receipts[name]={'url':url,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'first':str(axis[0]),
                        'last':str(axis[-1]),'samples':len(axis),'retrieved_utc':dt.datetime.now(dt.timezone.utc).isoformat()}
    require(end>=start,'No complete padded source window')
    expected=pd.date_range(f'{start-dt.timedelta(days=1)}T00:30Z',f'{end+dt.timedelta(days=1)}T23:30Z',freq='h')
    for axis in axes.values():
        require(axis[(axis>=expected[0])&(axis<=expected[-1])].equals(expected),'Missing historical padded source hours')
    return end,receipts


def target_context(ctx,name,selected):
    """Shrink transport only; retain every native point of selected reporting cells."""
    mask=ctx['masks'][name]&np.isin(ctx['ids'],selected)
    if not mask.any():return None
    yy,xx=np.where(mask.reshape(ctx['shape']));a,b,c,d=map(int,[yy.min(),yy.max(),xx.min(),xx.max()])
    index=np.s_[a:b+1,c:d+1];shape=(b-a+1,d-c+1)
    bounds=[ctx['bounds'][0]+a,ctx['bounds'][0]+b,ctx['bounds'][2]+c,ctx['bounds'][2]+d]
    return {**ctx,'bounds':bounds,'shape':shape,
        'ids':ctx['ids'].reshape(ctx['shape'])[index].ravel(),
        'weights':ctx['weights'].reshape(ctx['shape'])[index].ravel(),
        'masks':{n:(mask if n==name else ctx['masks'][n]).reshape(ctx['shape'])[index].ravel() for n in rf.FIELDS}}


def blank(days,cells,name):
    return pd.DataFrame({'date':np.repeat(days,len(cells)),'h3_index':list(cells)*len(days),rf.FIELDS[name][4]:np.nan})


def validate(frame,days,cells,columns):
    expected=pd.MultiIndex.from_product([days,cells],names=['date','h3_index'])
    require(frame.columns.tolist()==['date','h3_index']+columns,'Unexpected final schema')
    require(pd.MultiIndex.from_frame(frame[['date','h3_index']]).equals(expected),'Final date/H3 identity mismatch')


def existing_bindings(existing,mode,lo_extension=None):
    catalog=json.loads((existing/'catalog.json').read_text());records={}
    ids=([f'liveocean-{n}' for n in rf.FIELDS] if mode=='fast' else [])+['glorys12-salinity','glorys12-currents']
    for key in ids:
        record=next((p for p in catalog['products'] if p['id']==key),None)
        require(record is not None,'Missing existing product '+key)
        if key.startswith('liveocean-'):
            name=key.removeprefix('liveocean-')
            expected_units={'salinity':'g kg-1','oxygen':'mmol oxygen m-3','nitrate':'mmol nitrogen m-3'}[name]
            q=record.get('qualification',{})
            require(record.get('h3_resolution')==6 and record.get('metrics')==[rf.FIELDS[name][4]] and
                    record.get('units')==expected_units and q.get('source_model')=='LiveOcean cas7_t0_x4b' and
                    q.get('temporal_support')=='71-hour Godin low-pass centred on daily noon label' and
                    record.get('date_start')=='2013-01-01' and record.get('date_end')=='2024-12-31',
                    'Unqualified existing LO units/source/support')
        path=existing/record['path'];require(sha(path)==record['sha256'],'Existing product checksum mismatch')
        lineage=record.get('qualification',{}).get('lineage_path')
        record={**record,'absolute_path':str(path.resolve())}
        if lineage:
            path=existing/lineage;expected=record['qualification']['lineage_sha256']
            require(sha(path)==expected,'Existing required lineage mismatch')
            record['absolute_lineage_path']=str(path.resolve())
        records[key]=record
    if lo_extension is not None:
        p=Path(lo_extension).resolve()/'manifest.json';extension=json.loads(p.read_text())
        require(mode=='fast' and extension['status']=='complete' and extension['source_model']=='LiveOcean cas7_t0_x4b' and
                extension['metric']=='reference_salinity_g_kg' and extension['units']=='g kg-1' and extension['h3_resolution']==6 and
                extension['temporal_support']=='71-hour Godin low-pass centred on daily noon label' and
                extension['date_start']=='2013-01-01' and extension['date_end']=='2024-12-31','Unqualified LO salinity extension')
        require(len(extension['products'])==144 and len(extension['provenance'])==144,'Incomplete LO extension history')
        require({v['path'] for v in extension['products']}=={d.strftime('%Y-%m')+'.parquet' for d in pd.date_range('2013-01-01','2024-12-01',freq='MS')},'LO extension month identity')
        for product in extension['products']+extension['provenance']:
            require(sha(p.parent/product['path'])==product['sha256'],'LO extension output/provenance checksum mismatch')
        records['liveocean-regional-salinity']={'manifest_path':str(p),'manifest_sha256':sha(p),'extension':extension}
    return records


def lo_values(bindings,mode,name,days,ctx):
    frame=blank(days,ctx['cells'],name)
    if mode=='complete':return frame
    record=bindings['liveocean-'+name];metric=rf.FIELDS[name][4]
    # Daily row-group statistics avoid reading the complete multi-year product.
    file=pq.ParquetFile(record['absolute_path']);groups=[]
    date_index=file.schema_arrow.names.index('date')
    for i in range(file.num_row_groups):
        stats=file.metadata.row_group(i).column(date_index).statistics
        require(stats is not None and stats.has_min_max,'Existing date statistics required')
        if stats.max>=days[0] and stats.min<=days[-1]:groups.append(i)
    if groups:
        source=file.read_row_groups(groups).to_pandas();source=source[source.date.isin(days)]
        require(not source.duplicated(['date','h3_index']).any(),'Duplicate LO identity')
        indexed=source.set_index(['date','h3_index'])[metric]
        frame[metric]=indexed.reindex(pd.MultiIndex.from_frame(frame[['date','h3_index']])).to_numpy()
    if name=='salinity' and 'liveocean-regional-salinity' in bindings:
        extension=bindings['liveocean-regional-salinity'];parent=Path(extension['manifest_path']).parent
        for month in sorted({str(d)[:7] for d in days}):
            path=parent/(month+'.parquet')
            if not path.exists():continue  # Dates outside the extension period use SSC.
            extra=pd.read_parquet(path);extra=extra[extra.date.isin(days)]
            require(not extra.duplicated(['date','h3_index']).any(),'Duplicate extended LO salinity')
            values=extra.set_index(['date','h3_index'])[metric].reindex(pd.MultiIndex.from_frame(frame[['date','h3_index']])).to_numpy()
            overlap=frame[metric].notna()&np.isfinite(values)
            require(np.array_equal(frame.loc[overlap,metric],values[overlap]),'Extended LO salinity changed retained values')
            take=frame[metric].isna()&np.isfinite(values);frame.loc[take,metric]=values[take]
    target=set(ctx['ids'][ctx['masks'][name]])
    good=frame.h3_index.isin(target)&np.isfinite(frame[metric])&(frame[metric]>=0)&(frame[metric]<1e19)
    if name=='salinity':good &=frame[metric]<=50
    frame.loc[~good,metric]=np.nan
    return frame


def combine(lo,ssc,name):
    pd.testing.assert_frame_equal(lo[['date','h3_index']],ssc[['date','h3_index']],check_exact=True)
    metric=rf.FIELDS[name][4];frame=lo.copy();use_lo=lo[metric].notna();use_ssc=~use_lo&ssc[metric].notna()
    frame.loc[use_ssc,metric]=ssc.loc[use_ssc,metric]
    source=np.full(len(frame),'unavailable',dtype=object);source[use_lo]='liveocean';source[use_ssc]='salishseacast'
    return frame,source


def verify_record(output,record):
    for product in record['products']:
        require(sha(output/product['path'])==product['sha256'],'Accepted final product changed')


def finish_publication(root,output,month,prepared):
    require(prepared['plan_sha256']==sha(root/'plan.json'),'Prepared plan mismatch')
    record=prepared['record']
    for product in record['products']:
        target=output/product['path'];target.parent.mkdir(parents=True,exist_ok=True)
        # Stage names include field to avoid collisions between final directories.
        stage=root/'staging'/(Path(product['path']).parent.name+'-'+Path(product['path']).name+'.part')
        if target.exists():
            require(sha(target)==product['sha256'],'Conflicting final partition')
            if stage.exists():require(sha(stage)==product['sha256'],'Changed stage');stage.unlink()
        else:
            require(stage.exists() and sha(stage)==product['sha256'],'Missing/changed publication stage')
            os.replace(stage,target)
    verify_record(output,record)
    provenance=output/'provenance'/(month+'.json');provenance.parent.mkdir(exist_ok=True)
    if provenance.exists():require(json.loads(provenance.read_text())==record,'Conflicting month provenance')
    else:atomic_json(provenance,record)
    checkpoint={'month':month,'provenance_path':str(provenance.relative_to(output)),
                'provenance_sha256':sha(provenance),'plan_sha256':prepared['plan_sha256']}
    atomic_json(root/'checkpoints'/(month+'.json'),checkpoint)
    return record


def accepted(root,output,month):
    checkpoint=root/'checkpoints'/(month+'.json')
    if checkpoint.exists():
        c=json.loads(checkpoint.read_text());require(c['plan_sha256']==sha(root/'plan.json'),'Checkpoint plan mismatch')
        p=output/c['provenance_path'];require(sha(p)==c['provenance_sha256'],'Accepted provenance changed')
        record=json.loads(p.read_text());verify_record(output,record);return record
    prepared=root/'prepared'/(month+'.json')
    if prepared.exists():return finish_publication(root,output,month,json.loads(prepared.read_text()))
    return None


def evict(root,output,record):
    """Evict only request-addressed payloads bound to this accepted final month."""
    verify_record(output,record)
    checkpoint=json.loads((root/'checkpoints'/(record['month']+'.json')).read_text())
    require(sha(output/checkpoint['provenance_path'])==checkpoint['provenance_sha256'],'Provenance changed before eviction')
    removed=[]
    for receipt in record['sources']:
        key=hashlib.sha256(receipt['url'].encode()).hexdigest();path=root/'sources'/(key+'.gz')
        if 'reused_source_path' in receipt:
            path=Path(receipt['reused_source_path']);plan=json.loads((root/'plan.json').read_text())
            require(str(path.parent) in plan['shared_source_roots'] and path.name==key+'.gz','Reused cache cleanup outside budget')
            owner=path.parent.parent/'ownership.json'
            require(owner.exists() and json.loads(owner.read_text()).get('pipeline')=='surface-history','Reused cache owner changed')
        if path.exists():require(sha(path)==receipt['compressed_sha256'],'Generated source changed before eviction')
        removed.append({'path':str(path),'sha256':receipt['compressed_sha256'],'bytes':receipt['compressed_bytes']})
    ledger=root/'cleanup'/(record['month']+'.json')
    atomic_json(ledger,{'state':'prepared','verified_checkpoint':checkpoint,'removed':removed})
    for item in removed:(Path(item['path'])).unlink(missing_ok=True)
    atomic_json(ledger,{'state':'complete','verified_checkpoint':checkpoint,'removed':removed})


def process_month(root,output,ctx,bindings,mode,start,end,budget,offline=False,reference=False,retain_sources=False,max_tiles=1,reuse_sources=()):
    month=start.strftime('%Y-%m');record=accepted(root,output,month)
    if record is not None:
        if not retain_sources:evict(root,output,record)
        return record
    require(shutil.disk_usage(root).free>=20_000_000_000+1_500_000_000,'Insufficient staging/free floor')
    days=[d.date() for d in pd.date_range(start,end)]
    require(not reference or len(days)<=7,'Reference memory bound')
    lo={};contexts={};needed={}
    for name in rf.FIELDS:
        lo[name]=lo_values(bindings,mode,name,days,ctx);metric=rf.FIELDS[name][4]
        target=set(ctx['ids'][ctx['masks'][name]])
        needed[name]=sorted(set(lo[name].loc[lo[name][metric].isna(),'h3_index'])&target)
        tiles=partitions(ctx,name,needed[name],max_tiles)
        contexts[name]=[(tile,target_context(ctx,name,tile['cells'])) for tile in tiles]
    padded_start=start-dt.timedelta(days=1);padded_end=end+dt.timedelta(days=1)
    emit(root,'acquiring',month=month,mode=mode,completed_months=len(list((root/'checkpoints').glob('*.json'))),
         fallback_cells={n:len(v) for n,v in needed.items()},shared_source_bytes=budget.used())
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures={(n,i):pool.submit(rf.acquire,root,budget,n,padded_start,padded_end,c['bounds'],offline,read_timeout=600,reuse_sources=reuse_sources)
                 for n,tiles in contexts.items() for i,(_,c) in enumerate(tiles)}
        sources={key:f.result() for key,f in futures.items()}
    emit(root,'processing',month=month,mode=mode,shared_source_bytes=budget.used())
    frames={};diagnostics={};source_frame=blank(days,ctx['cells'],'salinity')[['date','h3_index']]
    for name in rf.FIELDS:
        ssc=blank(days,ctx['cells'],name);diags=[]
        for i,(tile,c) in enumerate(contexts[name]):
            phases,diag=rf.filter_source(sources[name,i][0],name,padded_start,padded_end,days,c,reference)
            take=ssc.h3_index.isin(tile['cells']);metric=rf.FIELDS[name][4]
            ssc.loc[take,metric]=phases['native1230'].loc[take,metric];diags.append(diag)
        diagnostics[name]={'tiles':diags,'reference_max_absolute_difference':max((v['reference_max_absolute_difference'] for v in diags),default=0.)}
        frames[name],source_frame[name+'_source']=combine(lo[name],ssc,name)
        validate(frames[name],days,ctx['cells'],[rf.FIELDS[name][4]])
    validate(source_frame,days,ctx['cells'],[n+'_source' for n in rf.FIELDS]);frames['sources']=source_frame
    products=[]
    for name,frame in frames.items():
        relative=f'{name}/{month}.parquet';stage=root/'staging'/(name+'-'+month+'.parquet.part')
        columns=[('date',pa.date32()),('h3_index',pa.string())]+[(n,pa.string() if name=='sources' else pa.float64()) for n in frame.columns[2:]]
        schema=pa.schema(columns)
        with pq.ParquetWriter(stage,schema,compression='zstd') as writer:
            for _,day in frame.groupby('date',sort=False):writer.write_table(pa.Table.from_pandas(day,schema=schema,preserve_index=False))
        file=pq.ParquetFile(stage)
        require(file.num_row_groups==len(days),'Final daily partition count')
        for i,(_,day) in enumerate(frame.groupby('date',sort=False)):
            pd.testing.assert_frame_equal(file.read_row_group(i).to_pandas(),day.reset_index(drop=True),check_exact=True)
        products.append({'path':relative,'sha256':sha(stage),'bytes':stage.stat().st_size,'rows':len(frame),'columns':frame.columns.tolist()})
    record={'month':month,'start':str(start),'end':str(end),'mode':mode,'plan_sha256':sha(root/'plan.json'),
        'products':products,'sources':[r for _,r in sources.values()],'native_validation':diagnostics,
        'ssc_requests':{n:[{'bounds':c['bounds'],'target_cells':tile['cells']} for tile,c in tiles] for n,tiles in contexts.items()},
        'source_counts':{n:{str(k):int(v) for k,v in source_frame[n+'_source'].value_counts().items()} for n in rf.FIELDS},
        'peak_shared_source_budget_bytes':budget.peak,'shared_source_bytes_before_eviction':budget.used(),
        'source_retention':'Generated hourly payloads evicted after checksum-bound final H3 and required provenance; raw replay requires reacquisition.'}
    prepared={'plan_sha256':sha(root/'plan.json'),'record':record}
    atomic_json(root/'prepared'/(month+'.json'),prepared)
    record=finish_publication(root,output,month,prepared)
    if not retain_sources:evict(root,output,record)
    emit(root,'month_complete',month=month,mode=mode,completed_months=len(list((root/'checkpoints').glob('*.json'))),
         source_counts=record['source_counts'],shared_source_bytes=budget.used(),peak_shared_source_budget_bytes=budget.peak)
    return record


def manifest(root,output,plan,records,status):
    value={'schema_version':1,'mode':plan['mode'],'status':status,'plan':plan,'plan_sha256':sha(root/'plan.json'),
           'completed_months':[{k:r[k] for k in ['month','start','end','products','source_counts']} for r in records],
           'completed_provenance':[{'path':'provenance/'+r['month']+'.json','sha256':sha(output/'provenance'/(r['month']+'.json'))} for r in records],
           'forecast_eligible':False,'model_eligible':False}
    atomic_json(output/'manifest.json',value)


def run(study,pilot,mask,support,existing,output,root,mode,start,end,shared=(),offline=False,reference=False,retain_sources=False,limit_months=None,max_tiles=1,lo_extension=None,reuse_sources=()):
    require(mode in ['fast','complete'],'Unknown source mode')
    require(1<=max_tiles<=16,'Tile count must be 1..16')
    root=Path(root).resolve();output=Path(output).resolve();existing=Path(existing).resolve()
    require(output!=existing and output!=root and root not in output.parents and output not in root.parents,'Separate source/work/delivery roots required')
    root.mkdir(parents=True,exist_ok=True)
    marker=root/'ownership.json';owner={'pipeline':'surface-history','output':str(output)}
    if marker.exists():require(json.loads(marker.read_text())==owner,'Work root ownership mismatch')
    else:require(not any(root.iterdir()),'New owned work root required');atomic_json(marker,owner)
    for n in ['sources','receipts','staging','prepared','checkpoints','cleanup']:(root/n).mkdir(exist_ok=True)
    output.mkdir(parents=True,exist_ok=True)
    require((root/'plan.json').exists() or not any(output.iterdir()),'New delivery root must be empty')
    start=dt.date.fromisoformat(str(start));requested_end=dt.date.fromisoformat(str(end));require(start<=requested_end,'Date order')
    with (root/'run.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        ctx=rf.context(study,pilot,mask,support)
        bindings=existing_bindings(existing,mode,lo_extension)
        for key,record in bindings.items():
            if key=='liveocean-regional-salinity':
                require(record['extension']['plan']['study']['study_sha256']==ctx['evidence']['study']['study_sha256'],'LO extension study mismatch')
            elif key.startswith('liveocean-'):
                require(record['qualification']['study']['study_sha256']==ctx['evidence']['study']['study_sha256'],
                        'Existing LO study mismatch')
        here=Path(__file__).parent
        binding={'mode':mode,'requested_start':str(start),'requested_end':str(requested_end),'output':str(output),
            'spatial':ctx['evidence'],'existing_products':bindings,'source_cap_bytes':2_000_000_000,'requests_in_flight':2,
            'shared_source_roots':sorted(set(str(Path(p).resolve()) for p in shared)),
            'reuse_source_roots':sorted(str(Path(p).resolve()) for p in reuse_sources),
            'code':{n:sha(here/n) for n in ['surface_history.py','regional_tiles.py','regional_filtered.py','regional_history.py','regional_transport.py','regional.py','regional_gap_history.py','liveocean.py','daily.py','history.py']},
            'versions':{n:importlib.metadata.version(n) for n in ['numpy','pandas','pyarrow','h3','xarray']},
            'source_read_timeout_seconds':600,
            'max_whole_cell_tiles_per_field':max_tiles,
            'method':{'salishseacast':'Exact hourly 71-tap Godin; native hourly means, 12:30 UTC centre, surface T layer ~0.5 m',
                      'liveocean':'Existing native 71-input Godin, noon UTC centre, ROMS surface rho layer',
                      'kernel':rf.godin_weights().tolist(),'phase':'No interpolation; SSC +30-minute phase retained in source provenance',
                      'scope':'SSC-supported regional study envelope, not a geographic inner/outer boundary; external outer GLORYS remains separate'},
            'field_definitions':rf.FIELDS,'reference_requested':reference}
        plan_path=root/'plan.json'
        if plan_path.exists():
            plan=json.loads(plan_path.read_text())
            # JSON serializes field tuples as lists.
            require({k:plan[k] for k in binding}==json.loads(json.dumps(binding)),'Frozen history plan changed')
            end=dt.date.fromisoformat(plan['end'])
        else:
            require(not offline,'Offline run requires frozen availability')
            end,axes=source_availability(start,requested_end)
            plan={**binding,'start':str(start),'end':str(end),'availability':axes};atomic_json(plan_path,plan)
        budget=Budget(root/'sources',shared);records=[]
        try:
            for first,last in months(start,end):
                saved=accepted(root,output,first.strftime('%Y-%m'))
                if saved is not None:
                    if not retain_sources:evict(root,output,saved)
                    records.append(saved)
                    continue
                if (root/'PAUSE').exists():
                    manifest(root,output,plan,records,'paused');emit(root,'paused',mode=mode,completed_months=len(records));return {'status':'paused','completed_months':len(records)}
                record=process_month(root,output,ctx,bindings,mode,first,last,budget,offline,reference,retain_sources,max_tiles,reuse_sources)
                records.append(record);manifest(root,output,plan,records,'running')
                if limit_months is not None and len(records)>=limit_months:
                    return {'status':'bounded','completed_months':len(records)}
            manifest(root,output,plan,records,'complete');emit(root,'complete',mode=mode,completed_months=len(records))
            result={'status':'complete','completed_months':len(records),'start':str(start),'end':str(end),'output':str(output)}
            atomic_json(root/'complete.json',result);return result
        except BaseException as error:
            emit(root,'failed',mode=mode,error=repr(error),completed_months=len(records));raise


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for n in ['study','pilot','mask','support','existing','output','root','start','end']:p.add_argument('--'+n,required=True)
    p.add_argument('--mode',choices=['fast','complete'],default='fast');p.add_argument('--shared-cache',action='append',default=[])
    p.add_argument('--offline',action='store_true');p.add_argument('--reference',action='store_true')
    p.add_argument('--max-tiles',type=int,default=1);p.add_argument('--lo-salinity-extension')
    p.add_argument('--reuse-source',action='append',default=[])
    a=p.parse_args(argv)
    result=run(a.study,a.pilot,a.mask,a.support,a.existing,a.output,a.root,a.mode,a.start,a.end,a.shared_cache,a.offline,a.reference,
               max_tiles=a.max_tiles,lo_extension=a.lo_salinity_extension,reuse_sources=a.reuse_source)
    print(json.dumps(result,indent=2));return 0


if __name__=='__main__':main()
