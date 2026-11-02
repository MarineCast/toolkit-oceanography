"""Bounded native tide-event pilot, with conservative water-connected station proxies."""
from __future__ import annotations
import datetime as dt, json, hashlib, os, fcntl, uuid, argparse
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import h3
from .daily import sha,study_inputs,write_json,recover,publish
import pyarrow as pa
import pyarrow.parquet as pq
from .spatial import water_distances
def support_checksum(path):
    path=Path(path); digest=hashlib.sha256(path.name.encode('utf-8'))
    with path.open('rb') as handle:
        for chunk in iter(lambda:handle.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()

METRICS=['high_tide_times_utc','low_tide_times_utc','high_tide_local_times','low_tide_local_times']

def events(payload,provider,start,end):
    start=pd.Timestamp(start,tz='UTC'); stop=pd.Timestamp(end,tz='UTC')+pd.Timedelta(days=1)
    if provider=='noaa':
        if not isinstance(payload,dict) or 'error' in payload or not isinstance(payload.get('predictions'),list): raise ValueError('NOAA event response failure')
        rows=[(pd.Timestamp(x['t'],tz='UTC'),x['type']) for x in payload['predictions']]
        if any(t not in ('H','L') for _,t in rows):raise ValueError('Unknown event type')
        if not rows or rows[0][0]>=start or rows[-1][0]<stop:raise ValueError('NOAA missing bracketing events')
        if any(b[0]-a[0]>pd.Timedelta(hours=30) for a,b in zip(rows,rows[1:])):raise ValueError('Incomplete NOAA event sequence')
    elif provider=='chs':
        if not isinstance(payload,list) or len(payload)<3:raise ValueError('CHS event response failure')
        native=[(pd.Timestamp(x['eventDate']),float(x['value'])) for x in payload]
        if any(t.tzinfo is None or not np.isfinite(v) for t,v in native):raise ValueError('Invalid CHS event')
        if any(native[i][0]>=native[i+1][0] for i in range(len(native)-1)):raise ValueError('Unsorted or duplicate CHS events')
        if native[0][0]>=start or native[-1][0]<stop:raise ValueError('CHS missing bracketing events')
        rows=[]
        for i,(time,value) in enumerate(native[1:-1],1):
            if not start<=time<stop:continue
            before,after=native[i-1][1],native[i+1][1]
            kind='H' if value>max(before,after) else ('L' if value<min(before,after) else None)
            if kind is None:raise ValueError('Ambiguous CHS event extremum')
            rows.append((time,kind))
    else:raise ValueError('Unknown tide provider')
    times=[x[0] for x in rows]
    if len(set(times))!=len(times) or times!=sorted(times):raise ValueError('Unsorted or duplicate tide events')
    rows=[(t.tz_convert('UTC'),k) for t,k in rows if start<=t<stop]
    if not rows:raise ValueError('Empty requested event response')
    return rows

def daily_events(rows,day,timezone):
    zone=ZoneInfo(timezone); selected=[(t,k) for t,k in rows if t.date()==day]
    high=[t.to_pydatetime() for t,k in selected if k=='H'];low=[t.to_pydatetime() for t,k in selected if k=='L']
    return [high,low,[t.astimezone(zone).isoformat() for t in high],[t.astimezone(zone).isoformat() for t in low]]

def calculate(study_path,root,support_root,start,end):
    root=Path(root); support_root=Path(support_root);study,members,evidence=study_inputs(study_path)
    dates=[x.date() for x in pd.date_range(start,end)]
    if not 1<=len(dates)<=3:raise ValueError('Tide pilot limited to three days')
    stations=json.loads((root/'stations.json').read_text());parsed={};receipts=[]
    inventories={}
    for provider in ('chs','noaa'):
        path=root/(provider+'-stations.json');rec=json.loads((root/(path.name+'.json')).read_text())
        if sha(path)!=rec['sha256']:raise ValueError('Station metadata checksum mismatch')
        data=json.loads(path.read_text());inventories[provider]=data if provider=='chs' else data['stations'];receipts.append(rec)
    for station in stations:
        provider=station['provider'];code=station['id'].split('-',1)[1]
        native=[x for x in inventories[provider] if str(x.get('code',x.get('id')))==code]
        if len(native)!=1:raise ValueError('Unknown station')
        a=native[0];lat=a['latitude'] if provider=='chs' else a['lat'];lon=a['longitude'] if provider=='chs' else a['lng']
        if station['lat']!=lat or station['lon']!=lon:raise ValueError('Station coordinate mismatch')
        if station['timezone']!=('America/Vancouver' if provider=='chs' else 'America/Los_Angeles'):raise ValueError('Pilot timezone mismatch')
    for s in stations:
        p=root/s['path'];rec=json.loads((root/s['receipt']).read_text())
        if sha(p)!=rec['sha256'] or p.stat().st_size!=rec['bytes']:raise ValueError('Tide source checksum mismatch')
        parsed[s['id']]=events(json.loads(p.read_text()),s['provider'],start,end);receipts.append(rec)
    manifest_path=support_root/'water_network/_dataset_manifest.json';manifest=json.loads(manifest_path.read_text());bindings=[]
    needed=['h3_geometry/H3_MODEL_AREA_SUPPORT_RES_8.parquet','water_network/H3_WATER_PASSABLE_EDGES_RES_8.parquet','water_geometry/COASTAL_CONTEXT_WATER.parquet']
    entries=manifest['artifacts']+manifest.get('upstream_artifacts',[])
    for relative in needed:
        matches=[a for a in entries if a['path'].endswith('/'+relative)]
        if len(matches)!=1 or support_checksum(support_root/relative)!=matches[0]['checksum']:raise ValueError('Unbound tide water support: '+relative)
        bindings.append(dict(path=str(support_root/relative),sha256=sha(support_root/relative),seascape_name_prefixed_sha256=matches[0]['checksum']))
    bbox=study['domain']['bbox_wgs84']
    if bbox is None:raise ValueError('Missing study bounding box')
    if isinstance(bbox,list):bbox=dict(zip(['min_lon','min_lat','max_lon','max_lat'],bbox))
    cfg=SimpleNamespace(support_dir=str(support_root),water_polygon_relative_path="water_geometry/COASTAL_CONTEXT_WATER.parquet",bbox=bbox,seed_shore_tolerance_m=0,seed_snap_max_km=1,tide_coast_snap_max_m=0,mouth_coast_snap_max_m=0)
    doc=SimpleNamespace(resolve_path=lambda p:Path(p));support,dist,audit=water_distances(doc,cfg,[dict(id=s['id'],lon=s['lon'],lat=s['lat']) for s in stations])
    parents=np.array([h3.cell_to_parent(x,6) for x in support.H3_INDEX]);mapping={}
    for cell in members[6]:
        indices=np.flatnonzero(parents==cell)
        if not len(indices):continue
        candidates=dist[:,indices];si,ni=np.unravel_index(np.argmin(candidates),candidates.shape);distance=float(candidates[si,ni])
        if distance<=20:mapping[cell]=dict(station=stations[si]['id'],distance_km=distance,water_target_r8=str(support.iloc[indices[ni]].H3_INDEX))
    if not mapping:raise ValueError('No water-connected tide support')
    byid={s['id']:s for s in stations};records=[]
    for day in dates:
        for cell in members[6]:
            m=mapping.get(cell);values=[None]*4 if m is None else daily_events(parsed[m['station']],day,byid[m['station']]['timezone'])
            records.append([day,cell,*values])
    frame=pd.DataFrame(records,columns=['date','h3_index',*METRICS])
    qual=dict(study=evidence,source_receipts=receipts,code_sha256=sha(__file__),routing_code_sha256=sha(Path(__file__).with_name('spatial.py')),station_selection_sha256=sha(root/'stations.json'),support_manifest=dict(path=str(manifest_path),sha256=sha(manifest_path)),support_bindings=bindings,station_metadata=stations,station_seed_audit=audit,mapping=mapping,method='Nearest station over R8 passable water graph, maximum 20 km; no land snapping or buffer; representative connected child only',date_basis='UTC event day; local ISO8601 offsets preserve DST and local date',forecast_eligible=False,issue_date=None,meaning='Predicted station timing proxy, not local tide interpolation or navigation guidance')
    return frame,qual


def run(study,root,support,output,start,end,promote=False):
    frame,qual=calculate(study,root,support,start,end);output=Path(output).resolve()
    work=output.parent.parent/'.marinecast-work'/'oceanography';work.mkdir(parents=True,exist_ok=True)
    with (work/'publication.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);recover(output,work)
        catalog=json.loads((output/'catalog.json').read_text());filename='tide-events-r6-daily.parquet'
        if catalog['study']['study_sha256']!=qual['study']['study_sha256']:raise ValueError('Publication study mismatch')
        if (output/filename).exists():raise ValueError('Existing tide product requires preserving update')
        stage=work/('stage-'+uuid.uuid4().hex);stage.mkdir()
        for path in output.iterdir():
            if not path.is_file() or path.is_symlink():raise ValueError('Unexpected delivery entry')
            if path.name!='catalog.json':os.link(path,stage/path.name)
        for p in catalog['products']:
            if sha(stage/p['path'])!=p['sha256']:raise ValueError('Existing delivery checksum mismatch')
        schema=pa.schema([('date',pa.date32()),('h3_index',pa.string())]+[(m,pa.list_(pa.timestamp('us',tz='UTC') if m.endswith('_utc') else pa.string())) for m in METRICS])
        with pq.ParquetWriter(stage/filename,schema,compression='zstd') as writer:
            for _,f in frame.groupby('date',sort=True):writer.write_table(pa.Table.from_pandas(f,schema=schema,preserve_index=False))
        table=pq.read_table(stage/filename);expected=pa.Table.from_pandas(frame,schema=schema,preserve_index=False)
        if not table.equals(expected) or frame.duplicated(['date','h3_index']).any():raise ValueError('Tide readback mismatch')
        stats={m:dict(nonnull=int(frame[m].notna().sum()),null=int(frame[m].isna().sum()),events=int(sum(len(x) for x in frame[m] if x is not None))) for m in METRICS}
        product=dict(id='tide-events',path=filename,sha256=sha(stage/filename),columns=list(frame.columns),metric=METRICS[0],metrics=METRICS,units='event timestamps (UTC and offset-bearing local ISO8601)',h3_resolution=6,row_count=len(frame),date_start=str(frame.date.min()),date_end=str(frame.date.max()),source_dataset='NOAA CO-OPS and CHS IWLS high/low predictions',source_url='https://api.tidesandcurrents.noaa.gov/api/prod/',description='Water-connected station timing proxy within 20 km; every high/low retained. Not a local phase model or navigation product.',statistics=stats,qualification=qual)
        catalog['products'].append(product);write_json(stage/'catalog.json',catalog)
        if promote:publish(stage,output,work)
        return dict(published=promote,stage=str(stage),product=product)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('study','root','support','output','start','end'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--publish',action='store_true');a=parser.parse_args()
    print(json.dumps(run(a.study,a.root,a.support,a.output,a.start,a.end,a.publish),indent=2))
if __name__=='__main__':main()
