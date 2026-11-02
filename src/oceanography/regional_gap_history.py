"""Resumable monthly SalishSeaCast history restricted to GLORYS spatial gaps."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import datetime as dt
import fcntl
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import time
from importlib.metadata import version

import h3
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests
import xarray as xr

from .daily import sha, study_inputs
from .regional import PRODUCTS, SPECS, read_source, validate
from .regional_history import DATASETS, spatial
from .regional_transport import BASE, Transport, atomic_json, inspect_source, source_bytes

FAMILIES = {'salinity':['reference_salinity_g_kg'],
            'currents':['current_east_m_s','current_north_m_s','current_speed_m_s']}


def emit(root, **event):
    receipts=Path(root)/'receipts'
    event['completed_months']={family:len(list(receipts.glob(family+'-*.month.json'))) for family in FAMILIES}
    source_dir=Path(root)/'sources'
    event['source_cache_bytes']=source_bytes(source_dir) if source_dir.is_dir() else 0
    event['updated_at_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
    atomic_json(Path(root)/'progress.json', event)
    print(json.dumps(event, sort_keys=True), flush=True)


def months(start, end):
    current = dt.date.fromisoformat(str(start)).replace(day=1)
    end = dt.date.fromisoformat(str(end))
    start = dt.date.fromisoformat(str(start))
    while current <= end:
        following = (current.replace(day=28)+dt.timedelta(days=4)).replace(day=1)
        yield max(start,current), min(end,following-dt.timedelta(days=1))
        current = following


def fingerprint():
    here = Path(__file__).parent
    return {name:sha(here/name) for name in ['regional_gap_history.py','regional_transport.py',
            'regional.py','regional_history.py','daily.py']}


def availability(start, requested_end):
    receipts = {}
    latest = requested_end
    axes = {}
    for kind,(dataset,_) in DATASETS.items():
        url = f'{BASE}/griddap/{dataset}.csv?time'
        response = requests.get(url,timeout=(20,90))
        response.raise_for_status()
        if len(response.content) > 8_000_000:
            raise ValueError('Time-axis metadata exceeds cap')
        axis = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(io.StringIO(response.text),skiprows=[1])['time'],utc=True))
        if not axis.is_unique or not axis.is_monotonic_increasing or axis.empty:
            raise ValueError('Invalid source time axis')
        complete = axis[-1].date()
        if axis[-1].time() != dt.time(23,30):
            complete -= dt.timedelta(days=1)
        latest = min(latest,complete)
        axes[kind] = axis
        receipts[kind] = dict(url=url,sha256=hashlib.sha256(response.content).hexdigest(),
                              samples=len(axis),first=str(axis[0]),last=str(axis[-1]),
                              retrieved_at_utc=dt.datetime.now(dt.timezone.utc).isoformat())
    expected = pd.date_range(str(start)+'T00:30:00Z',str(latest)+'T23:30:00Z',freq='h')
    if not len(expected):
        raise ValueError('No complete available study days')
    for axis in axes.values():
        selected = axis[(axis>=expected[0])&(axis<=expected[-1])]
        if not selected.equals(expected):
            raise ValueError('Historical time-axis gap; source dates remain pending')
    return latest,receipts


def spatial_target(study_path, pilot, output):
    study,members,study_evidence = study_inputs(study_path)
    cells,_,angle,weight,ids,inside,geometry = spatial(study_path,pilot)
    catalog = json.loads((Path(output)/'catalog.json').read_text())
    gaps = None
    bindings = {}
    for product_id in ['glorys12-salinity','glorys12-currents']:
        record = next(p for p in catalog['products'] if p['id']==product_id)
        path = Path(output)/record['path']
        if sha(path) != record['sha256'] or record['h3_resolution'] != 5:
            raise ValueError('GLORYS delivery binding mismatch')
        file = pq.ParquetFile(path)
        reference = None
        for group in range(file.num_row_groups):
            frame = file.read_row_group(group,columns=['h3_index',*record['metrics']]).to_pandas()
            if frame.h3_index.tolist() != members[5]:
                raise ValueError('GLORYS membership/order mismatch')
            mask = frame[record['metrics']].isna()
            if not mask.eq(mask.iloc[:,0],axis=0).all().all():
                raise ValueError('GLORYS metric support differs')
            missing = set(frame.loc[mask.iloc[:,0],'h3_index'])
            if reference is not None and missing != reference:
                raise ValueError('Require stable GLORYS spatial gap footprint')
            reference = missing
        if reference is None or (gaps is not None and reference != gaps):
            raise ValueError('GLORYS salinity/current gaps differ or are empty')
        gaps = reference
        bindings[product_id] = {'path':str(path.resolve()),'sha256':record['sha256']}
    gp,_ = read_source(Path(pilot),'geometry')
    with xr.open_dataset(gp) as g:
        lon,lat = g.longitude.values[1:,1:].ravel(),g.latitude.values[1:,1:].ravel()
    r5 = np.array([h3.latlng_to_cell(float(lat[i]),float(lon[i]),5) if inside[i] else '' for i in range(len(inside))])
    selected = sorted(set(ids[inside & np.isin(r5,sorted(gaps))]))
    retained = inside & np.isin(ids,selected)
    if not retained.any():
        raise ValueError('No qualified native points in GLORYS gaps')
    yy,xx = np.where(retained.reshape(angle.shape))
    core = [int(yy.min()+1),int(yy.max()+1),int(xx.min()+1),int(xx.max()+1)]
    evidence = dict(study=study_evidence,geometry=geometry,glorys=bindings,selected_r6=selected,
                    missing_glorys_r5=sorted(gaps),core=core,native_centres=int(retained.sum()),
                    native_mask_sha256=hashlib.sha256(retained.tobytes()).hexdigest())
    a,b,c,d = core
    idx = np.s_[a-1:b,c-1:d]
    context = dict(cells=cells,core=core,angle=angle[idx],weight=weight.reshape(angle.shape)[idx].ravel(),
                   ids=ids.reshape(angle.shape)[idx].ravel(),inside=retained.reshape(angle.shape)[idx].ravel(),
                   selected=selected)
    return study,evidence,context


def rectangles(core):
    a,b,c,d = core
    return {'salinity':core,'u':[a,b,c-1,d],'v':[a-1,b,c,d]}


def day_frame(day, values, context, family):
    frame = pd.DataFrame({'date':day,'h3_index':context['cells']})
    for metric,array in values.items():
        value = array.ravel()
        good = context['inside'] & np.isfinite(value)
        data = pd.DataFrame({'id':context['ids'][good], 'weighted':value[good]*context['weight'][good],
                             'weight':context['weight'][good]}).groupby('id')[['weighted','weight']].sum()
        frame[metric] = frame.h3_index.map(data.weighted/data.weight)
    validate(frame,FAMILIES[family],[day],context['cells'])
    if frame.loc[~frame.h3_index.isin(context['selected']),FAMILIES[family]].notna().any().any():
        raise ValueError('Output escaped frozen gap target')
    return frame


def interval_frames(sources, start, end, context, family):
    """One hourly slice per source in memory; no decoded source staging."""
    required = rectangles(context['core'])
    kinds = ['salinity'] if family=='salinity' else ['u','v']
    with ExitStack() as stack:
        streams = {}
        for kind in kinds:
            path = sources[kind]
            header,bounds = inspect_source(path,kind,start,end,required[kind])
            handle = stack.enter_context(gzip.open(path,'rb'))
            handle.seek(header['variables'][SPECS[kind][0]]['begin'])
            a,b,c,d = bounds
            ra,rb,rc,rd = required[kind]
            streams[kind] = (handle,(b-a+1,d-c+1),np.s_[ra-a:rb-a+1,rc-c:rd-c+1])
        cosine,sine = np.cos(context['angle']),np.sin(context['angle'])
        for day in pd.date_range(start,end):
            totals = [np.zeros(context['angle'].shape) for _ in FAMILIES[family]]
            valid = np.ones(context['angle'].shape,bool)
            for hour in range(24):
                arrays = {}
                for kind,(handle,shape,index) in streams.items():
                    size = int(np.prod(shape))*4
                    blob = handle.read(size)
                    if len(blob) != size:
                        raise ValueError('Truncated native hourly field')
                    arrays[kind] = np.frombuffer(blob,dtype='>f4').reshape(shape)[index].astype(float)
                if family=='salinity':
                    value = arrays['salinity']
                    valid &= np.isfinite(value)&(value>=0)&(value<=50)
                    totals[0] += value
                else:
                    uc=(arrays['u'][:,:-1]+arrays['u'][:,1:])/2
                    vc=(arrays['v'][:-1,:]+arrays['v'][1:,:])/2
                    u,v=uc*cosine-vc*sine,uc*sine+vc*cosine
                    valid &= np.isfinite(u)&np.isfinite(v)&(np.abs(u)<=10)&(np.abs(v)<=10)
                    for total,value in zip(totals,[u,v,np.hypot(u,v)]):
                        total += value
            values={name:np.where(valid,total/24,np.nan) for name,total in zip(FAMILIES[family],totals)}
            yield day_frame(day.date(),values,context,family)
        for handle,_,_ in streams.values():
            # Finish gzip CRC verification even if coordinate variables follow data.
            while handle.read(1024*1024):
                pass


def verify_month(path, start, end, context, family):
    dates = [d.date() for d in pd.date_range(start,end)]
    file = pq.ParquetFile(path)
    if file.num_row_groups != len(dates):
        raise ValueError('Checkpoint day count mismatch')
    for i,day in enumerate(dates):
        frame=file.read_row_group(i).to_pandas()
        validate(frame,FAMILIES[family],[day],context['cells'])
        if frame.loc[~frame.h3_index.isin(context['selected']),FAMILIES[family]].notna().any().any():
            raise ValueError('Checkpoint escaped spatial gap mask')
        if not frame[FAMILIES[family]].notna().any().any():
            raise ValueError('Entire gap-target day lacks qualified native values')
    return sha(path)


def evict_month_sources(transport, family, start, end, checkpoint_path, digest):
    """Also release registered valid inputs left by interrupted/recovered attempts."""
    kinds=['salinity'] if family=='salinity' else ['u','v']
    for path in transport.sources.glob('*.gz'):
        receipt=transport.receipts/(path.stem+'.json')
        if not receipt.exists():
            continue
        source=json.loads(receipt.read_text())
        if source.get('kind') in kinds and str(start)<=source.get('start','')<=source.get('end','')<=str(end):
            if sha(path)!=source['compressed_sha256']:
                raise ValueError('Source changed before checkpoint eviction')
            transport.evict(path,{'checkpoint':str(checkpoint_path),'sha256':digest})


def checkpoint(root, family, start, end, context, transport, following=None):
    key=f'{family}-{start}-{end}'
    path=root/'months'/(key+'.parquet')
    receipt=root/'receipts'/(key+'.month.json')
    if path.exists() and receipt.exists():
        record=json.loads(receipt.read_text())
        if verify_month(path,start,end,context,family) != record['sha256']:
            raise ValueError('Checkpoint checksum mismatch')
        evict_month_sources(transport,family,start,end,path,record['sha256'])
        return record
    if following is not None:
        following_key=f'{family}-{following[0]}-{following[1]}'
        if (root/'months'/(following_key+'.parquet')).exists() and (root/'receipts'/(following_key+'.month.json')).exists():
            following=None
    temporary=path.with_suffix('.part')
    schema=pa.schema([('date',pa.date32()),('h3_index',pa.string())]+[(m,pa.float64()) for m in FAMILIES[family]])
    kinds=['salinity'] if family=='salinity' else ['u','v']
    all_sources=[]
    intervals=[(start,end)]
    prefetch=getattr(transport,'prefetch',lambda *args:None)
    for kind in kinds:
        prefetch(kind,start,end,rectangles(context['core'])[kind])
    # Scalars overlap two adjacent months. Vector requests first reserve both
    # current faces; their next cohort starts only once this pair is available.
    if family=='salinity' and following is not None:
        prefetch('salinity',*following,rectangles(context['core'])['salinity'])
    with pq.ParquetWriter(temporary,schema,compression='zstd') as writer:
        while intervals:
            first,last=intervals.pop(0)
            acquired={}
            try:
                acquisition_failures=[]
                for kind in kinds:
                    emit(root,status='acquiring',family=family,month=str(start),kind=kind,
                         interval_start=str(first),interval_end=str(last),cache_cap_bytes=transport.cap)
                    try:
                        acquired[kind]=transport.acquire(kind,first,last,rectangles(context['core'])[kind])
                    except (RuntimeError,requests.RequestException) as exc:
                        if getattr(transport,'requests_in_flight',1)==1:
                            raise
                        acquisition_failures.append(exc)
                # Drain both submitted vector requests before fallback so a late
                # successful face cannot escape lineage or verified eviction.
                if acquisition_failures:
                    raise acquisition_failures[0]
            except (RuntimeError,requests.RequestException):
                if (last-first).days < 7:
                    raise
                for source_path,metadata in acquired.values():
                    all_sources.append({**metadata,'unused_after_weekly_recovery':True,
                                        'owned_path':str(source_path) if source_path.parent==transport.sources else None})
                # Monthly acquisition failed before any rows from this interval.
                # Existing owned valid field stays available for a later retry.
                weeks=[]
                cursor=first
                while cursor<=last:
                    stop=min(last,cursor+dt.timedelta(days=6));weeks.append((cursor,stop));cursor=stop+dt.timedelta(days=1)
                intervals=weeks+intervals
                continue
            paths={kind:item[0] for kind,item in acquired.items()}
            if family=='currents' and following is not None:
                for kind in kinds:
                    prefetch(kind,*following,rectangles(context['core'])[kind])
            for frame in interval_frames(paths,first,last,context,family):
                writer.write_table(pa.Table.from_pandas(frame,schema=schema,preserve_index=False))
            for source_path,metadata in acquired.values():
                all_sources.append({**metadata,'owned_path':str(source_path) if source_path.parent==transport.sources else None})
    verify_month(temporary,start,end,context,family)
    os.replace(temporary,path)
    record=dict(family=family,start=str(start),end=str(end),sha256=sha(path),sources=all_sources,producer_code=fingerprint())
    atomic_json(receipt,record)
    # The immutable H3 replacement was read back before normal cache eviction.
    evict_month_sources(transport,family,start,end,path,record['sha256'])
    return record


def assemble(root, output, plan, context, family, promote):
    name=f'salishsea-gap-{family}-r6-daily.parquet'
    final=root/name
    records=[]
    schema=pa.schema([('date',pa.date32()),('h3_index',pa.string())]+[(m,pa.float64()) for m in FAMILIES[family]])
    with pq.ParquetWriter(final.with_suffix('.part'),schema,compression='zstd') as writer:
        for start,end in months(plan['start'],plan['end']):
            p=root/'months'/f'{family}-{start}-{end}.parquet'
            record=json.loads((root/'receipts'/f'{family}-{start}-{end}.month.json').read_text())
            if verify_month(p,start,end,context,family)!=record['sha256']:
                raise ValueError('Final assembly input checksum mismatch')
            source=pq.ParquetFile(p)
            for i in range(source.num_row_groups):
                writer.write_table(source.read_row_group(i))
            records.append(record)
    os.replace(final.with_suffix('.part'),final)
    merged=pq.ParquetFile(final)
    offset=0
    statistics={m:dict(nonnull=0,null=0,minimum=None,maximum=None) for m in FAMILIES[family]}
    for record in records:
        source=pq.ParquetFile(root/'months'/f"{family}-{record['start']}-{record['end']}.parquet")
        for i in range(source.num_row_groups):
            table=merged.read_row_group(offset)
            if not table.equals(source.read_row_group(i)):
                raise ValueError('Final daily readback differs from checkpoint')
            frame=table.to_pandas()
            for metric,stats in statistics.items():
                values=frame[metric].dropna()
                stats['nonnull']+=len(values);stats['null']+=int(frame[metric].isna().sum())
                if len(values):
                    stats['minimum']=float(values.min()) if stats['minimum'] is None else min(stats['minimum'],float(values.min()))
                    stats['maximum']=float(values.max()) if stats['maximum'] is None else max(stats['maximum'],float(values.max()))
            offset+=1
    if offset != merged.num_row_groups:
        raise ValueError('Extra final daily partitions')
    lineage_name=f'salishsea-gap-{family}-lineage.json'
    lineage=root/lineage_name
    atomic_json(lineage,dict(plan=plan,months=records,source_retention='Transient generated source cohorts evicted only after verified daily H3 checkpoint; external sources preserved. Exact hourly replay requires source reacquisition.',
                             scientific_scope='Source-separated spatial gap supplement; reference salinity and mean collocated hourly-vector speed are not GLORYS metric substitutions.'))
    product=dict(id=f'salishsea-gap-{family}',path=name,sha256=sha(final),h3_resolution=6,
                 columns=['date','h3_index',*FAMILIES[family]],metric=FAMILIES[family][0],metrics=FAMILIES[family],
                 units='g kg-1' if family=='salinity' else 'm/s',row_count=merged.metadata.num_rows,
                 date_start=plan['start'],date_end=plan['end'],source_dataset='SalishSeaCast v21-11',source_url=BASE+'/',
                 description='Historical source-separated GLORYS spatial-gap supplement; no numeric mosaic.',statistics=statistics,
                 qualification=dict(study=plan['spatial']['study'],plan_sha256=plan['plan_sha256'],lineage_path=lineage_name,
                                    lineage_sha256=sha(lineage),surface_depth_m=.5000003,selected_r6_cells=context['selected'],
                                    date_basis='24 complete hourly-mean UTC intervals; native labels 00:30–23:30',
                                    salinity_definition='Reference salinity g/kg, not practical salinity psu',
                                    speed_definition='Daily mean magnitude of collocated hourly-mean vectors',forecast_eligible=False))
    if not promote:
        return product
    publication=output.parent.parent/'.marinecast-work'/'oceanography'/'publication.lock'
    publication.parent.mkdir(parents=True,exist_ok=True)
    with publication.open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        catalog_path=output/'catalog.json'
        catalog=json.loads(catalog_path.read_text())
        if catalog['study']['study_sha256']!=plan['spatial']['study']['study_sha256']:
            raise ValueError('Delivery study changed during acquisition')
        prior=next((p for p in catalog['products'] if p['id']==product['id']),None)
        if prior is not None and prior!=product:
            raise ValueError('Refusing replacement of a different accepted gap product')
        for source,target in [(final,output/name),(lineage,output/lineage_name)]:
            if target.exists():
                if sha(target)!=sha(source):
                    raise ValueError('Refusing overwrite of conflicting delivery file')
            else:
                os.replace(source,target)
        if prior is None:
            catalog['products'].append(product)
            atomic_json(catalog_path,catalog)
        if sha(output/name)!=product['sha256'] or sha(output/lineage_name)!=product['qualification']['lineage_sha256']:
            raise ValueError('Published final checksum mismatch')
        atomic_json(root/(family+'.complete.json'),product)
        # Only this run's checkpoints whose final readback passed are disposable.
        for record in records:
            p=root/'months'/f"{family}-{record['start']}-{record['end']}.parquet"
            if sha(p)!=record['sha256']:
                raise ValueError('Checkpoint changed before cleanup')
            p.unlink()
        for p in (final,lineage):
            if p.exists():
                p.unlink()  # identical own staging copy after idempotent publish
    return product


def upgrade_plan(root, plan, binding, context, expected_sha):
    """Explicit, checksum-bound producer transition; never silently relax resume."""
    path=root/'plan.json'
    if expected_sha is None or sha(path)!=expected_sha:
        raise ValueError('Frozen plan code changed; explicit exact prior-plan checksum required')
    if any(plan[k]!=v for k,v in binding.items() if k!='code'):
        raise ValueError('Frozen plan spatial/source/period/dependencies changed')
    if any((root/(family+'.complete.json')).exists() for family in FAMILIES):
        raise ValueError('Cannot upgrade a plan with completed published families')
    checked=[]
    attribution={(r['path'],r['sha256']):r['producer_code']
                 for transition in plan.get('producer_transitions',[])
                 for r in transition['verified_checkpoints']}
    for receipt in sorted((root/'receipts').glob('*.month.json')):
        r=json.loads(receipt.read_text())
        checkpoint_path=root/'months'/(receipt.name.removesuffix('.month.json')+'.parquet')
        digest=verify_month(checkpoint_path,dt.date.fromisoformat(r['start']),dt.date.fromisoformat(r['end']),context,r['family'])
        if digest!=r['sha256']:
            raise ValueError('Checkpoint changed before producer upgrade')
        producer=r.get('producer_code',attribution.get((str(checkpoint_path),digest),plan['code']))
        checked.append(dict(path=str(checkpoint_path),sha256=digest,producer_code=producer))
    snapshot=root/('plan-before-'+expected_sha+'.json')
    original=path.read_bytes()
    if snapshot.exists():
        if snapshot.read_bytes()!=original:
            raise ValueError('Conflicting prior-plan snapshot')
    else:
        snapshot.write_bytes(original)
    updated={**plan,'code':binding['code']}
    updated['producer_transitions']=[*plan.get('producer_transitions',[]),dict(
        upgraded_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),prior_plan_file_sha256=expected_sha,
        prior_plan= snapshot.name,prior_code=plan['code'],code=binding['code'],verified_checkpoints=checked)]
    updated.pop('plan_sha256',None)
    updated['plan_sha256']=hashlib.sha256(json.dumps(updated,sort_keys=True).encode()).hexdigest()
    atomic_json(path,updated)
    return updated


def run(study, pilot, output, root, families=('salinity','currents'), start=None, end=None,
        seeds=(), offline=False, prepare=False, promote=False, limit=None, rounds=3,
        requests_in_flight=1, upgrade_plan_from=None):
    if rounds<1 or (limit is not None and limit<1) or not families or any(f not in FAMILIES for f in families):
        raise ValueError('Require valid families and positive run limits')
    study,pilot,output,root=map(lambda p:Path(p).resolve(),(study,pilot,output,root))
    if root==output or root in output.parents or output in root.parents or root==pilot or root in pilot.parents:
        raise ValueError('Work, delivery and retained geometry paths must not overlap')
    root.mkdir(parents=True,exist_ok=True)
    for name in ['months','receipts']:
        (root/name).mkdir(exist_ok=True)
    if requests_in_flight not in (1,2):
        raise ValueError('Require one or two in-flight requests')
    with (root/'run.lock').open('a') as lock, ExitStack() as stack:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        config,evidence,context=spatial_target(study,pilot,output)
        requested_start=dt.date.fromisoformat(start or config['time']['start'])
        requested_end=dt.date.fromisoformat(end) if end else dt.date.fromisoformat(config['time']['end_exclusive'])-dt.timedelta(days=1)
        if requested_start<dt.date.fromisoformat(config['time']['start']) or requested_end>=dt.date.fromisoformat(config['time']['end_exclusive']) or requested_start>requested_end:
            raise ValueError('Requested period outside approved study')
        binding=dict(code=fingerprint(),spatial=evidence,requested_start=str(requested_start),requested_end=str(requested_end),
                     versions={name:version(name) for name in ['numpy','pandas','pyarrow','h3','shapely','pyproj','xarray']})
        plan_path=root/'plan.json'
        if plan_path.exists():
            plan=json.loads(plan_path.read_text())
            if any(plan[k]!=v for k,v in binding.items()):
                if upgrade_plan_from is None:
                    raise ValueError('Frozen plan code/study/source/target/period changed')
                plan=upgrade_plan(root,plan,binding,context,upgrade_plan_from)
        elif upgrade_plan_from is not None:
            raise ValueError('Producer upgrade requires an existing frozen plan')
        else:
            if offline:
                raise ValueError('Offline run needs an existing frozen availability plan')
            latest,axes=availability(requested_start,requested_end)
            plan={**binding,'start':str(requested_start),'end':str(latest),'availability':axes,
                  'python':platform.python_version(),'source_cache_cap_bytes':2_000_000_000,
                  'free_floor_bytes':20_000_000_000,'source_cleanup':'Only generated registered inputs after verified checkpoints; existing sources excluded',
                  'spatial_method':'Native T-centre direct R5 gap membership selects R6 cells; full accepted native spatial support retained for those cells; no H3-parent substitution'}
            plan['plan_sha256']=hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest()
            atomic_json(plan_path,plan)
        emit(root,status='prepared',start=plan['start'],end=plan['end'],requested_end=plan['requested_end'],
             selected_r6_cells=len(context['selected']),native_centres=evidence['native_centres'],monthly_slices=len(list(months(plan['start'],plan['end']))))
        if prepare:
            return plan
        transport=stack.enter_context(Transport(root,seeds,offline,requests_in_flight=requests_in_flight))
        atomic_json(root/'execution.json',dict(requests_in_flight=requests_in_flight,
                    code=fingerprint(),plan_sha256=plan['plan_sha256'],source_cache_cap_bytes=transport.cap,
                    started_at_utc=dt.datetime.now(dt.timezone.utc).isoformat()))
        completed_this_invocation=0
        for iteration in range(rounds):
            failures=[]
            for family in families:
                if family not in FAMILIES:
                    raise ValueError('Unknown regional history family')
                complete=root/(family+'.complete.json')
                if complete.exists():
                    product=json.loads(complete.read_text())
                    if product['qualification']['plan_sha256']!=plan['plan_sha256'] or sha(output/product['path'])!=product['sha256'] or sha(output/product['qualification']['lineage_path'])!=product['qualification']['lineage_sha256']:
                        raise ValueError('Completed delivery changed')
                    lineage=json.loads((output/product['qualification']['lineage_path']).read_text())
                    for record in lineage['months']:
                        p=root/'months'/f"{family}-{record['start']}-{record['end']}.parquet"
                        if p.exists():
                            if sha(p)!=record['sha256']:
                                raise ValueError('Completed checkpoint cleanup checksum mismatch')
                            p.unlink()
                    continue
                cohorts=list(months(plan['start'],plan['end']))
                for index,(first,last) in enumerate(cohorts):
                    try:
                        following=cohorts[index+1] if index+1<len(cohorts) and (limit is None or completed_this_invocation+1<limit) else None
                        record=checkpoint(root,family,first,last,context,transport,following)
                        completed_this_invocation+=1
                        emit(root,status='checkpoint_verified',family=family,start=str(first),end=str(last),sha256=record['sha256'])
                        if limit is not None and completed_this_invocation>=limit:
                            return {'status':'bounded_checkpoint_run','months':completed_this_invocation}
                    except (RuntimeError,requests.RequestException,OSError) as exc:
                        failures.append(dict(family=family,start=str(first),end=str(last),error=repr(exc)))
                        emit(root,status='pending',failures=failures)
                        if len(failures)>=3:
                            break
                if not any(f['family']==family for f in failures):
                    product=assemble(root,output,plan,context,family,promote)
                    emit(root,status='family_complete' if promote else 'family_staged',family=family,product=product['path'],sha256=product['sha256'])
            if not failures:
                emit(root,status='complete' if promote else 'staged',start=plan['start'],end=plan['end'],families=list(families))
                return {'status':'complete' if promote else 'staged'}
            if iteration+1<rounds:
                emit(root,status='retry_wait',failures=failures,retry_seconds=300)
                time.sleep(300)
        emit(root,status='needs_attention',failures=failures)
        raise RuntimeError('Historical cohorts remain pending; resumable checkpoints preserved')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['study','pilot','output','root']:
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--family',action='append',choices=list(FAMILIES))
    parser.add_argument('--start');parser.add_argument('--end')
    parser.add_argument('--reuse-cache',action='append',default=[])
    parser.add_argument('--offline',action='store_true')
    parser.add_argument('--prepare-only',action='store_true')
    parser.add_argument('--publish',action='store_true')
    parser.add_argument('--limit-months',type=int)
    parser.add_argument('--requests-in-flight',type=int,choices=[1,2],default=1)
    parser.add_argument('--upgrade-plan-from',help='Exact SHA256 of prior plan.json; archives old plan and verifies every checkpoint')
    args=parser.parse_args(argv)
    try:
        run(args.study,args.pilot,args.output,args.root,args.family or tuple(FAMILIES),args.start,args.end,
            args.reuse_cache,args.offline,args.prepare_only,args.publish,args.limit_months,
            requests_in_flight=args.requests_in_flight,upgrade_plan_from=args.upgrade_plan_from)
    except BaseException as exc:
        if Path(args.root).is_dir():
            emit(Path(args.root),status='needs_attention',error=repr(exc))
        raise
    return 0


if __name__=='__main__':
    raise SystemExit(main())
