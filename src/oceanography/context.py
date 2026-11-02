"""Native-period NOAA CPC RONI context; no daily or local-observation claims."""
from __future__ import annotations
import argparse, calendar, datetime as dt, fcntl, json, math, os, re, uuid
from html.parser import HTMLParser
from pathlib import Path
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from .daily import sha, write_json, study_inputs, recover, publish
URL = "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/roni/"
SEASONS = "DJF JFM FMA MAM AMJ MJJ JJA JAS ASO SON OND NDJ".split()

class Rows(HTMLParser):
    def __init__(self):
        super().__init__(); self.active=False; self.rows=[]; self.row=None; self.cell=None
    def handle_starttag(self,tag,attrs):
        if tag=='table' and dict(attrs).get('id')=='roni-v5-table2': self.active=True
        if not self.active: return
        if tag=='tr':
            if self.row is not None: self.rows.append(self.row)
            self.row=[]
        if tag in ('td','th'): self.cell=[]
    def handle_data(self,data):
        if self.active and self.cell is not None: self.cell.append(data)
    def handle_endtag(self,tag):
        if not self.active: return
        if tag in ('td','th') and self.cell is not None:
            if self.row is not None: self.row.append(''.join(self.cell).strip())
            self.cell=None
        if tag in ('tr','tbody','table') and self.row is not None: self.rows.append(self.row); self.row=None
        if tag=='table': self.active=False

def period(year,month):
    centre=pd.Timestamp(year=year,month=month,day=1)
    return (centre-pd.DateOffset(months=1)).date(), (centre+pd.DateOffset(months=2)-pd.Timedelta(days=1)).date()

def parse_roni(html):
    if 'ERSSTv6' not in html or '1991' not in html or 'Relative Oceanic' not in html: raise ValueError('RONI source version mismatch')
    parser=Rows(); parser.feed(html); result=[]; seen=set()
    for row in parser.rows:
        if not row or not re.fullmatch(r'\d{4}',row[0]): continue
        year=int(row[0])
        if year in seen or not 1 <= len(row)-1 <= 12: raise ValueError('Duplicate/malformed RONI year')
        seen.add(year)
        for month,value in enumerate(row[1:],1):
            if not re.fullmatch(r'[+-]?\d+\.\d+',value): raise ValueError('Invalid RONI value')
            value=float(value)
            if not math.isfinite(value) or abs(value)>10: raise ValueError('Invalid RONI range')
            start,end=period(year,month)
            result.append(dict(date=end,period_start=str(start),period_end=str(end),season=SEASONS[month-1],source_year=year,issue_date=None,roni_c=value))
    result.sort(key=lambda x:x['date'])
    if not result: raise ValueError('No RONI periods')
    actual=pd.DatetimeIndex([r['date'] for r in result])
    if not actual.equals(pd.date_range(actual[0],actual[-1],freq='ME')): raise ValueError('Missing/duplicate RONI periods')
    return result

def calculate(study,source,receipt,start,end):
    source=Path(source); rec=json.loads(Path(receipt).read_text())
    if rec.get('url')!=URL or rec.get('sha256')!=sha(source) or rec.get('bytes')!=source.stat().st_size: raise ValueError('RONI receipt mismatch')
    _,members,evidence=study_inputs(study); cells=members[5]
    start=dt.date.fromisoformat(start); end=dt.date.fromisoformat(end)
    if start>end: raise ValueError('Invalid date range')
    periods=[r for r in parse_roni(source.read_text()) if start<=r['date']<=end]
    if not periods: raise ValueError('No requested RONI periods')
    expected=pd.date_range(start,periods[-1]['date'],freq='ME')
    if list(expected.date)!=[r['date'] for r in periods]: raise ValueError('Requested history incomplete')
    frame=pd.DataFrame([(r['date'],cell,r['roni_c']) for r in periods for cell in cells],columns=['date','h3_index','roni_c'])
    qual=dict(study=evidence,source_receipts=[rec],code_sha256=sha(__file__),source_version='RONI ERSSTv6',baseline='1991–2020',native_cadence='overlapping three-month seasons, monthly update',date_basis='last calendar day of native three-month period; not publication date',spatial_mapping='Same basin-scale context broadcast to approved R5 cells; no local measurement',publication_lag='CPC updates by fifth of month; most recent two months may revise',forecast_eligible=False,periods=[{k:str(v) if k=='date' else v for k,v in r.items() if k!='roni_c'} for r in periods])
    return frame,qual

def run(study,source,receipt,output,start,end,promote=False):
    frame,qual=calculate(study,source,receipt,start,end); output=Path(output).resolve()
    work=output.parent.parent/'.marinecast-work'/'oceanography'; work.mkdir(parents=True,exist_ok=True)
    with (work/'publication.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB); recover(output,work)
        catalog=json.loads((output/'catalog.json').read_text())
        if catalog['study']['study_sha256']!=qual['study']['study_sha256']: raise ValueError('Publication study mismatch')
        filename='enso-roni-r5-seasonal.parquet'
        if (output/filename).exists(): raise ValueError('Existing context requires explicit preserving update')
        stage=work/('stage-'+uuid.uuid4().hex); stage.mkdir()
        for path in output.iterdir():
            if not path.is_file() or path.is_symlink(): raise ValueError('Unexpected delivery entry')
            if path.name!='catalog.json': os.link(path,stage/path.name)
        for p in catalog['products']:
            if sha(stage/p['path'])!=p['sha256']: raise ValueError('Existing checksum mismatch')
        schema=pa.schema([('date',pa.date32()),('h3_index',pa.string()),('roni_c',pa.float64())])
        with pq.ParquetWriter(stage/filename,schema,compression='zstd') as writer:
            for _,f in frame.groupby('date',sort=True): writer.write_table(pa.Table.from_pandas(f,schema=schema,preserve_index=False))
        pd.testing.assert_frame_equal(frame,pq.read_table(stage/filename).to_pandas())
        if frame.duplicated(['date','h3_index']).any(): raise ValueError('Duplicate context identity')
        product=dict(id='enso-roni',path=filename,sha256=sha(stage/filename),columns=list(frame.columns),metric='roni_c',metrics=['roni_c'],units='degree_C',h3_resolution=5,row_count=len(frame),date_start=str(frame.date.min()),date_end=str(frame.date.max()),source_dataset='NOAA CPC RONI ERSSTv6',source_url=URL,description='Three-month ENSO context indexed by period end; broadcast across study, not local or daily observations.',statistics={'roni_c':dict(nonnull=len(frame),null=0,minimum=float(frame.roni_c.min()),maximum=float(frame.roni_c.max()))},qualification=qual)
        catalog['products'].append(product); write_json(stage/'catalog.json',catalog)
        if promote: publish(stage,output,work)
        return dict(published=promote,stage=str(stage),product=product)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['study','source','receipt','output','start','end']: p.add_argument('--'+name,required=True)
    p.add_argument('--publish',action='store_true'); a=p.parse_args()
    print(json.dumps(run(a.study,a.source,a.receipt,a.output,a.start,a.end,a.publish),indent=2))
if __name__=='__main__': main()
