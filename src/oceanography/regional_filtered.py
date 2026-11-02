"""Bounded SSC scalar Godin-filter pilot with explicit timing alternatives."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import datetime as dt
import fcntl
import gzip
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import time
import zlib

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests
import xarray as xr

from .daily import sha
from .history import atomic_json
from .liveocean import Budget, require
from .regional_history import spatial
from .regional_transport import nc_header

BASE='https://salishsea.eos.ubc.ca/erddap'
FIELDS={
 'salinity':('ubcSSg3DPhysicsFields1hV21-11','salinity','g kg-1','sea_water_reference_salinity','reference_salinity_g_kg'),
 'oxygen':('ubcSSg3DChemistryFields1hV21-11','dissolved_oxygen','mmol m-3','mole_concentration_of_dissolved_molecular_oxygen_in_sea_water','dissolved_oxygen_mmol_m3'),
 'nitrate':('ubcSSg3DBiologyFields1hV21-11','nitrate','mmol m-3','mole_concentration_of_nitrate_in_sea_water','nitrate_mmol_m3')}
PHASES=('native1130','native1230','noon_interpolated')
RESPONSE=450_000_000
DECODED=1_250_000_000


def godin_weights():
    """The standard 71-tap hourly 24–24–25 filter, not a uniform mean."""
    return np.convolve(np.convolve(np.ones(24)/24,np.ones(24)/24),np.ones(25)/25)


def window_weights(times,days):
    times=pd.DatetimeIndex(times)
    require(times.tz is not None and str(times.tz)=='UTC','Require UTC source hours')
    require(len(times)>1 and times.equals(pd.date_range(times[0],times[-1],freq='h')),
            'Missing/duplicated source hours')
    require(all(t.minute==30 and t.second==0 for t in times),'Require native HH:30 hourly means')
    weights=np.zeros((len(days),3,len(times)))
    for i,day in enumerate(days):
        for j,hour in enumerate([11,12]):
            centre=pd.Timestamp(f'{day}T{hour:02d}:30:00Z')
            desired=pd.date_range(centre-pd.Timedelta(hours=35),periods=71,freq='h')
            indices=times.get_indexer(desired)
            require((indices>=0).all(),'Incomplete padded Godin window')
            weights[i,j,indices]=godin_weights()
        weights[i,2]=(weights[i,0]+weights[i,1])/2
    return weights


def context(study,pilot,mask_path,support_path):
    cells,evidence,angle,weight,ids,inside,geometry=spatial(study,Path(pilot))
    support=json.loads(Path(support_path).read_text())
    require(evidence['study_sha256']==support['study_sha256'],'Support study mismatch')
    with xr.open_dataset(mask_path) as ds:
        require(ds.tmask.shape[-2:]==(898,398),'Surface mask shape mismatch')
        wet=(ds.tmask.values.squeeze()[1:,1:]==1).ravel()
    inside &=wet
    require(set(support['salinity_r6'])<=set(cells) and set(support['scalar_r6'])<=set(cells),'Invalid reporting support')
    masks={name:inside&np.isin(ids,support['salinity_r6'] if name=='salinity' else support['scalar_r6']) for name in FIELDS}
    union=np.logical_or.reduce(list(masks.values()))
    yy,xx=np.where(union.reshape(angle.shape));bounds=[int(yy.min()+1),int(yy.max()+1),int(xx.min()+1),int(xx.max()+1)]
    a,b,c,d=bounds;index=np.s_[a-1:b,c-1:d]
    return {'cells':cells,'bounds':bounds,'shape':(b-a+1,d-c+1),
            'ids':ids.reshape(angle.shape)[index].ravel(),
            'weights':weight.reshape(angle.shape)[index].ravel(),
            'masks':{n:m.reshape(angle.shape)[index].ravel() for n,m in masks.items()},
            'evidence':{'study':evidence,'geometry':geometry,'source_surface_mask':{'path':str(Path(mask_path).resolve()),'sha256':sha(mask_path)},
                        'support':support,'support_sha256':sha(support_path)}}


def inspect(path,name,start,end,bounds):
    with gzip.open(path,'rb') as f:prefix=f.read(262144)
    h=nc_header(prefix)
    def axis(n):
        v=h['variables'][n];size=int(np.prod(v['shape']))*v['itemsize']
        require(v['begin']+size<=len(prefix),'Axis outside bounded header')
        return np.frombuffer(prefix[v['begin']:v['begin']+size],dtype=v['dtype'])
    times=pd.date_range(f'{start}T00:30:00Z',f'{end}T23:30:00Z',freq='h')
    t=h['variables']['time']['attributes']
    require(t.get('units')=='seconds since 1970-01-01T00:00:00Z' and t.get('calendar','standard') in ['standard','gregorian','proleptic_gregorian'],'Time origin/calendar mismatch')
    require(np.array_equal(axis('time'),times.as_unit('s').asi8),'Incomplete or shifted source hours')
    depth=h['variables']['depth']['attributes']
    require(depth.get('units')=='m' and depth.get('positive')=='down' and len(axis('depth'))==1 and abs(float(axis('depth')[0])-.5000003)<1e-6,'Surface depth mismatch')
    a,b,c,d=bounds
    require(np.array_equal(axis('gridY'),np.arange(a,b+1)) and np.array_equal(axis('gridX'),np.arange(c,d+1)),'Source bounds mismatch')
    _,var,units,standard,_=FIELDS[name];v=h['variables'][var]
    require(v['dimensions']==['time','depth','gridY','gridX'] and v['shape']==[len(times),1,b-a+1,d-c+1] and v['dtype']=='>f4','Source field layout mismatch')
    require(v['attributes'].get('units')==units and v['attributes'].get('standard_name')==standard,'Source variable convention mismatch')
    return h,times


def acquire(root,budget,name,start,end,bounds,offline=False,read_timeout=180,reuse_sources=()):
    dataset,var,_,_,_=FIELDS[name];a,b,c,d=bounds
    url=f'{BASE}/griddap/{dataset}.nc?{var}[({start}T00:30:00Z):1:({end}T23:30:00Z)][0][{a}:1:{b}][{c}:1:{d}]'
    key=hashlib.sha256(url.encode()).hexdigest();path=root/'sources'/(key+'.gz');receipt=root/'receipts'/(key+'.json')
    if not path.exists():
        for directory in reuse_sources:
            directory=Path(directory).resolve();candidate=directory/(key+'.gz');record=directory.parent/'receipts'/(key+'.json')
            owner=directory.parent/'ownership.json'
            if not candidate.exists():continue
            require(owner.exists() and json.loads(owner.read_text()).get('pipeline')=='surface-history','Only owned history cache reuse is allowed')
            require(directory in budget.shared,'Reused source must be inside the shared budget')
            r=json.loads(record.read_text());require(r['url']==url and sha(candidate)==r['compressed_sha256'],'Reused source mismatch')
            inspect(candidate,name,start,end,bounds)
            return candidate,{**r,'reused_source_path':str(candidate),'reused_receipt_path':str(record)}
    if path.exists():
        r=json.loads(receipt.read_text());require(r['url']==url and sha(path)==r['compressed_sha256'],'Source checksum/request mismatch');inspect(path,name,start,end,bounds);return path,r
    require(not offline,'Missing offline source: '+name)
    reservation=RESPONSE+4096;budget.reserve(reservation)
    part=path.with_suffix('.part');clock=time.monotonic()
    try:
        for attempt in range(3):
            try:
                attempt_clock=time.monotonic()
                decoder=zlib.decompressobj(16+zlib.MAX_WBITS);dig=hashlib.sha256();decoded=compressed=0
                with requests.get(url,stream=True,timeout=(20,read_timeout),headers={'Accept-Encoding':'gzip'}) as response:
                    response.raise_for_status();require(response.headers.get('Content-Encoding')=='gzip','Require lossless gzip response')
                    response.raw.decode_content=False;header_seconds=time.monotonic()-clock
                    with part.open('wb') as handle:
                        while block:=response.raw.read(65536):
                            compressed+=len(block);value=decoder.decompress(block);decoded+=len(value);dig.update(value)
                            require(compressed<=RESPONSE,'Compressed source response byte cap exceeded')
                            require(decoded<=DECODED,'Decoded source response byte cap exceeded')
                            if time.monotonic()-attempt_clock>=600:
                                raise requests.Timeout('Source response exceeded 600 seconds; retry the prepared request')
                            handle.write(block)
                        handle.flush();os.fsync(handle.fileno())
                require(not decoder.flush() and decoder.eof,'Truncated gzip response')
                break
            except requests.RequestException:
                if attempt==2:raise
                time.sleep(attempt+1)
        h,times=inspect(part,name,start,end,bounds)
        require(decoded==max(v['begin']+int(np.prod(v['shape']))*v['itemsize'] for v in h['variables'].values()),'Decoded source length mismatch')
        r={'url':url,'field':name,'start':str(start),'end':str(end),'bounds':bounds,'compressed_bytes':compressed,
           'decoded_bytes':decoded,'compressed_sha256':sha(part),'decoded_sha256':dig.hexdigest(),
           'retrieved_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'seconds':time.monotonic()-clock,'header_seconds':header_seconds,
           'attempts':attempt+1,'response_seconds':time.monotonic()-attempt_clock}
        with budget.lock:
            os.replace(part,path);atomic_json(receipt,r);budget.reserved-=reservation
        return path,r
    except BaseException:
        part.unlink(missing_ok=True);budget.release(reservation);raise


def spatial_mean(values,valid,ctx):
    good=valid&np.isfinite(values)
    p=pd.DataFrame({'id':ctx['ids'][good],'wv':values[good]*ctx['weights'][good],'w':ctx['weights'][good]})
    sums=p.groupby('id')[['wv','w']].sum()
    means=sums.wv/sums.w
    return pd.Series(ctx['cells']).map(means).to_numpy(dtype=float)


def reduce_hourly(arrays,times,days,ctx,name,reference=False):
    """At most three active daily windows; never store a decoded month."""
    w=window_weights(times,days);active={};results={phase:[] for phase in PHASES};details=[]
    mask=ctx['masks'][name];samples=[];ref_max=0.
    ends=np.max(np.where(w>0,np.arange(len(times))[None,None,:],-1),axis=(1,2))
    raw_dig=hashlib.sha256()
    for j,source in enumerate(arrays):
        require(j<len(times),'Extra source hour')
        raw_dig.update(source.tobytes());arr=source.ravel().astype(float)
        valid=mask&np.isfinite(arr)&(arr>=0)&(arr<1e19)
        if name=='salinity':valid &=arr<=50
        safe=np.where(valid,arr,0)
        if reference:samples.append(source.ravel()[mask].astype('float32'))
        for i in np.flatnonzero(np.any(w[:,:,j]>0,axis=1)):
            if i not in active:active[i]=(np.zeros((3,len(arr))),np.broadcast_to(mask,(3,len(arr))).copy())
            totals,goods=active[i]
            for k in np.flatnonzero(w[i,:,j]>0):totals[k]+=safe*w[i,k,j];goods[k]&=valid
            if j==ends[i]:
                for k,phase in enumerate(PHASES):
                    values=spatial_mean(totals[k],goods[k],ctx)
                    require(np.isfinite(values).any(),'Wholly missing filtered day/field')
                    results[phase].append((days[i],values))
                details.append({'date':str(days[i]),'native_complete_points':{phase:int(goods[k].sum()) for k,phase in enumerate(PHASES)},
                                'complete_support_sha256':{phase:hashlib.sha256(goods[k].tobytes()).hexdigest() for k,phase in enumerate(PHASES)}})
                del active[i]
    require(j+1==len(times) and not active and all(len(v)==len(days) for v in results.values()),'Incomplete source/window stream')
    if reference:
        samples=np.asarray(samples,dtype=float)
        valid=np.isfinite(samples)&(samples>=0)&(samples<1e19)
        if name=='salinity':valid &=samples<=50
        for i,day in enumerate(days):
            for k,phase in enumerate(PHASES):
                indices=np.flatnonzero(w[i,k]>0);good=np.all(valid[indices],axis=0)
                direct=w[i,k,indices]@np.where(valid[indices],samples[indices],0)
                values=np.zeros(mask.shape);ok=np.zeros(mask.shape,bool);values[mask]=direct;ok[mask]=good
                expected=spatial_mean(values,ok,ctx);actual=dict(results[phase])[day]
                require(np.array_equal(np.isnan(expected),np.isnan(actual)),'Reference support mismatch')
                error=float(np.nanmax(np.abs(expected-actual)));ref_max=max(ref_max,error)
                require(error<1e-10,'Direct matrix/streaming mismatch')
    frames={phase:pd.concat([pd.DataFrame({'date':day,'h3_index':ctx['cells'],FIELDS[name][4]:values}) for day,values in rows],ignore_index=True) for phase,rows in results.items()}
    return frames,{'field':name,'days':details,'native_field_sha256':raw_dig.hexdigest(),'direct_matrix_reference':reference,'reference_max_absolute_difference':ref_max}


def filter_source(path,name,start,end,days,ctx,reference=False):
    h,times=inspect(path,name,start,end,ctx['bounds']);var=FIELDS[name][1];shape=ctx['shape'];size=int(np.prod(shape))*4
    with gzip.open(path,'rb') as f:
        f.seek(h['variables'][var]['begin'])
        def stream():
            for _ in times:
                blob=f.read(size);require(len(blob)==size,'Truncated hourly field')
                yield np.frombuffer(blob,dtype='>f4').reshape(shape)
        frames,diag=reduce_hourly(stream(),times,days,ctx,name,reference)
        while f.read(1048576):pass  # gzip CRC validates the entire response.
    return frames,diag


def timing_diagnostics(frames,diagnostics):
    out={}
    for name in FIELDS:
        metric=FIELDS[name][4];a=frames[name]['native1130'][metric];b=frames[name]['native1230'][metric];n=frames[name]['noon_interpolated'][metric]
        paired=a.notna()&b.notna()&n.notna()
        delta=(b[paired]-a[paired]).abs();align=(b[paired]-n[paired]).abs()
        out[name]={'paired_cell_days':int(paired.sum()),'units':FIELDS[name][2],
          'identical_native_support_across_phases':all(len(set(day['complete_support_sha256'].values()))==1 for day in next(d for d in diagnostics if d['field']==name)['days']),
          'native_one_hour_difference_median':float(delta.median()),'native_one_hour_difference_p95':float(delta.quantile(.95)),
          'noon_alignment_difference_median':float(align.median()),'noon_alignment_difference_p95':float(align.quantile(.95)),
          'noon_alignment_difference_max':float(align.max()),
          'qualification':'Sampled model timing sensitivity, not a general error bound or cross-model bias correction. Native validity/support counts must also be inspected.'}
    return out


def cleanup(root,output,products):
    for p in products:require(sha(output/p['path'])==p['sha256'],'Final replacement checksum mismatch')
    complete=json.loads((root/'complete.json').read_text())
    require(sha(output/'provenance.json')==complete['provenance_sha256'],'Required provenance checksum mismatch')
    ledger=root/'cleanup.json';record=json.loads(ledger.read_text()) if ledger.exists() else {'removed':[]}
    listed={p['path']:p for p in record['removed']}
    for p in (root/'sources').iterdir():
        require(p.is_file() and not p.is_symlink() and p.suffix in ['.gz','.part'],'Unregistered source path')
        r=root/'receipts'/(p.stem+'.json')
        require(r.exists() and sha(p)==json.loads(r.read_text())['compressed_sha256'],'Unregistered/unverified source')
        listed[str(p)]={'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size}
    record.update(state='prepared',removed=list(listed.values()),verified_products=products)
    atomic_json(ledger,record)
    for item in record['removed']:
        p=Path(item['path']);require(p.parent==root/'sources','Cleanup escaped work root')
        if p.exists():require(sha(p)==item['sha256'],'Source changed');p.unlink()
    record.update(state='complete',bytes_removed=sum(x['bytes'] for x in record['removed']));atomic_json(ledger,record)


def run(study,pilot,mask,support,output,root,start,end,shared=(),offline=False,reference=False,retain_sources=False):
    root=Path(root).resolve();output=Path(output).resolve();root.mkdir(parents=True,exist_ok=True)
    marker=root/'ownership.json'
    if marker.exists():require(json.loads(marker.read_text())=={'pipeline':'regional-filtered-pilot'},'Work root ownership mismatch')
    else:require(not any(root.iterdir()),'Require a new empty work root');atomic_json(marker,{'pipeline':'regional-filtered-pilot'})
    for name in ['sources','receipts']:(root/name).mkdir(exist_ok=True)
    days=[d.date() for d in pd.date_range(start,end)]
    require(0<len(days)<=31,'Bounded timing qualification requires 1..31 output days; no full run before qualification')
    require(not reference or len(days)<=7,'Direct matrix reference is bounded to seven output days')
    padded_start=days[0]-dt.timedelta(days=1);padded_end=days[-1]+dt.timedelta(days=1)
    require(padded_start>=dt.date(2007,1,1),'Padded window before SSC archive')
    ctx=context(study,pilot,mask,support)
    expected_times=pd.date_range(f'{padded_start}T00:30:00Z',f'{padded_end}T23:30:00Z',freq='h')
    planned_weights=window_weights(expected_times,days)
    windows=[]
    for i,day in enumerate(days):
        for k,phase in enumerate(PHASES):
            indices=np.flatnonzero(planned_weights[i,k]>0)
            windows.append({'date':str(day),'phase':phase,'first_native_centre_utc':str(expected_times[indices[0]]),
                'last_native_centre_utc':str(expected_times[indices[-1]]),'weighted_native_samples':len(indices)})
    plan={'start':str(days[0]),'end':str(days[-1]),'padded_start':str(padded_start),'padded_end':str(padded_end),
          'source_cache_cap_bytes':2_000_000_000,'kernel':godin_weights().tolist(),'kernel_sha256':hashlib.sha256(godin_weights().tobytes()).hexdigest(),
          'phase_rules':{'native1130':'71 taps centred 11:30 UTC','native1230':'71 taps centred 12:30 UTC',
             'noon_interpolated':'Linear interpolation of 11:30/12:30 native filters to 12:00 UTC; effective 72 hourly inputs, additional alignment smoothing'},
          'scope':'Surface salinity gap target, oxygen/nitrate all SSC-supported study cells; no currents or model blending',
          'bounds':ctx['bounds'],'spatial':ctx['evidence'],
          'code':{n:sha(Path(__file__).with_name(n)) for n in ['regional_filtered.py','regional_history.py','regional.py','regional_transport.py','liveocean.py','daily.py','history.py']},
          'versions':{n:importlib.metadata.version(n) for n in ['numpy','pandas','pyarrow','h3','xarray']},
          'direct_reference_requested':reference,'windows':windows,
          'forecast_eligible':False,'model_eligible':False,'full_run_qualified':False}
    with (root/'run.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        old=json.loads((root/'plan.json').read_text()) if (root/'plan.json').exists() else None
        if old is None:atomic_json(root/'plan.json',plan)
        else:require(old==plan,'Frozen pilot plan changed')
        if (root/'complete.json').exists():
            result=json.loads((root/'complete.json').read_text())
            for p in result['products']:require(sha(output/p['path'])==p['sha256'],'Completed product changed')
            require(sha(output/'provenance.json')==result['provenance_sha256'],'Completed provenance changed')
            if not retain_sources:cleanup(root,output,result['products'])
            return result
        budget=Budget(root/'sources',shared)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures={n:pool.submit(acquire,root,budget,n,padded_start,padded_end,ctx['bounds'],offline) for n in FIELDS}
            sources={n:future.result() for n,future in futures.items()}
        frames={};diagnostics=[]
        for name,(path,r) in sources.items():
            frames[name],diag=filter_source(path,name,padded_start,padded_end,days,ctx,reference);diagnostics.append(diag)
            for frame in frames[name].values():
                require(pd.MultiIndex.from_frame(frame[['date','h3_index']]).equals(pd.MultiIndex.from_product([days,ctx['cells']],names=['date','h3_index'])),'Filtered H3 identity mismatch')
        stats=timing_diagnostics(frames,diagnostics);output.mkdir(parents=True,exist_ok=True);products=[]
        # Native 12:30 products preserve the exact requested 71-tap operator.
        for name in FIELDS:
            frame=frames[name]['native1230'];metric=FIELDS[name][4]
            filename=f'salishsea-godin71-{name}-r6-daily.parquet';stage=root/(filename+'.part')
            schema=pa.schema([('date',pa.date32()),('h3_index',pa.string()),(metric,pa.float64())])
            with pq.ParquetWriter(stage,schema,compression='zstd') as writer:
                for _,day in frame.groupby('date',sort=False):writer.write_table(pa.Table.from_pandas(day,schema=schema,preserve_index=False))
            pd.testing.assert_frame_equal(pq.read_table(stage).to_pandas(),frame,check_exact=True)
            target=output/filename
            if target.exists():require(sha(target)==sha(stage),'Conflicting final output');stage.unlink()
            else:os.replace(stage,target)
            products.append({'path':filename,'sha256':sha(target),'rows':len(frame),'metric':metric,'units':FIELDS[name][2],
                             'valid_time_utc':'12:30','native_samples':71})
        comparison=frames['salinity']['native1130'][['date','h3_index']].copy()
        for name in FIELDS:
            for phase in PHASES:comparison[name+'_'+phase]=frames[name][phase][FIELDS[name][4]].to_numpy()
        target=output/'timing-comparison-r6-daily.parquet';stage=root/'timing-comparison.part';comparison.to_parquet(stage,index=False,compression='zstd')
        pd.testing.assert_frame_equal(pq.read_table(stage).to_pandas(),comparison,check_exact=True)
        if target.exists():require(sha(target)==sha(stage),'Conflicting timing output');stage.unlink()
        else:os.replace(stage,target)
        products.append({'path':target.name,'sha256':sha(target),'rows':len(comparison),'purpose':'Final H3 phase comparison; no noon-interpolated value mislabeled as an exact 71-input native filter'})
        provenance={'plan':plan,'products':products,'field_definitions':FIELDS,'sources':[r for p,r in sources.values()],'native_validation':diagnostics,'timing':stats,
                    'source_retention':'Generated hourly payloads removed only after final H3 readback; exact raw replay requires reacquisition.',
                    'interpretation':'Same Godin kernel; source-hour interval averaging, spatial/depth support and model bias remain distinct. Native 12:30 versus LO noon is a real half-hour phase offset.'}
        atomic_json(output/'provenance.json',provenance)
        result={'status':'complete','output':str(output),'products':products,'provenance_sha256':sha(output/'provenance.json'),
                'timing':stats,'peak_shared_source_budget_bytes':budget.peak,'shared_source_bytes_before_cleanup':budget.used(),
                'owned_source_payload_bytes':sum(p.stat().st_size for p in (root/'sources').iterdir()),'full_run_started':False}
        atomic_json(root/'complete.json',result)
        if not retain_sources:cleanup(root,output,products)
        return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for n in ['study','pilot','mask','support','output','root','start','end']:p.add_argument('--'+n,required=True)
    p.add_argument('--shared-cache',action='append',default=[]);p.add_argument('--offline',action='store_true');p.add_argument('--reference',action='store_true')
    a=p.parse_args(argv);print(json.dumps(run(a.study,a.pilot,a.mask,a.support,a.output,a.root,a.start,a.end,a.shared_cache,a.offline,a.reference),indent=2))
    return 0


if __name__=='__main__':main()
