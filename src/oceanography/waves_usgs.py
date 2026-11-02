"""USGS CoSMoS baseline waves, gated on evidence-backed effective coordinates."""
import argparse
from collections import OrderedDict
from contextlib import ExitStack
import datetime as dt
import hashlib
import html
import io
import json
from pathlib import Path
import re
import shutil
from urllib.parse import urljoin, urlparse

import h5py
import numpy as np
import pandas as pd
import requests

from .daily import sha, study_inputs
from .history import atomic_json
from .waves_ssc import clean_attr
from . import waves_regional as common

RELEASE='https://cmgds.marine.usgs.gov/data-releases/datarelease/10.5066-P14VOPEY/'
DOI='https://doi.org/10.5066/P14VOPEY'
PATTERN=r'Reanalysis_and_Projected_CoSMoSwaves_([A-Za-z]+)_sealevel000m.nc'


class QualificationError(ValueError):
    """Source support cannot yet justify publication; evidence remains outside Data."""


def release_files():
    with requests.Session() as session:
        session.trust_env=False
        response=session.get(RELEASE,timeout=(15,60),allow_redirects=False)
        response.raise_for_status()
        if len(response.content)>2_000_000:raise ValueError('USGS release metadata bound')
        links={}
        for href in re.findall(r'href=[\"\']([^\"\']+)',response.text):
            url=urljoin(RELEASE,html.unescape(href));name=url.rsplit('/',1)[-1]
            if re.fullmatch(PATTERN,name):links[name]=url
    if len(links)!=12:raise QualificationError('Expected twelve baseline county files; requalify changed release')
    return dict(sorted(links.items()))


class Remote(io.RawIOBase):
    """Exact coalesced HTTP ranges; bounded RAM and transfer, no raw disk archive."""
    def __init__(self,url,*,budget=2_000_000_000,cache_bytes=256_000_000):
        parsed=urlparse(url)
        if (parsed.scheme!='https' or parsed.netloc!='cmgds.marine.usgs.gov' or parsed.query or parsed.fragment
                or '..' in parsed.path or not re.fullmatch(PATTERN,parsed.path.rsplit('/',1)[-1])):
            raise ValueError('Untrusted USGS baseline source')
        super().__init__();self.url=url;self.position=0;self.size=None;self.bytes=0;self.budget=budget
        self.cache_bytes=cache_bytes;self.cached=0;self.cache=OrderedDict();self.records=[];self.identity=None
        self.session=requests.Session();self.session.trust_env=False
        self._get(0,4096)
    def readable(self):return True
    def seekable(self):return True
    def tell(self):return self.position
    def seek(self,offset,whence=0):
        self.position=int(offset+(self.position if whence==1 else self.size if whence==2 else 0))
        if self.position<0:raise ValueError('Negative USGS seek')
        return self.position
    def _get(self,start,n):
        key=(start,n)
        if key in self.cache:self.cache.move_to_end(key);return self.cache[key]
        if n>64_000_000 or self.bytes+n>self.budget:raise ValueError('USGS range transfer bound reached')
        end=start+n-1
        with self.session.get(self.url,headers={'Range':f'bytes={start}-{end}','Accept-Encoding':'identity'},
                              stream=True,timeout=(15,90),allow_redirects=False) as response:
            match=re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',response.headers.get('Content-Range',''))
            if response.status_code!=206 or not match or int(match[1])!=start or int(match[2])!=end:
                raise ValueError('USGS exact HTTP range support required')
            size=int(match[3]);identity=(size,response.headers.get('ETag'),response.headers.get('Last-Modified'))
            if self.identity is not None and identity!=self.identity:raise ValueError('USGS source changed during read')
            self.identity=identity;self.size=size;body=bytearray()
            for block in response.iter_content(65536):
                body.extend(block)
                if len(body)>n:raise ValueError('USGS range body exceeds request')
            if len(body)!=n:raise ValueError('Truncated USGS range')
        value=bytes(body);self.bytes+=n
        self.records.append(dict(start=start,bytes=n,sha256=hashlib.sha256(value).hexdigest()))
        while self.cache and self.cached+n>self.cache_bytes:
            _,old=self.cache.popitem(last=False);self.cached-=len(old)
        if n<=self.cache_bytes:self.cache[key]=value;self.cached+=n
        return value
    def read(self,n=-1):
        n=min(self.size-self.position,n if n>=0 else self.size-self.position)
        if n<=0:return b''
        value=self._get(self.position,n);self.position+=len(value);return value
    def readinto(self,b):
        value=self.read(len(b));b[:len(value)]=value;return len(value)
    def close(self):
        if hasattr(self,'session'):self.session.close();self.cache.clear();self.cached=0
        super().close()


def header(file):
    units=clean_attr(file['time'].attrs.get('units'))
    if units!='hours since 1941-01-01':raise QualificationError('USGS time units changed')
    time=file['time'];edges=time[[0,1,len(time)-2,len(time)-1]].astype(float)
    if not np.isfinite(edges).all() or edges[1]-edges[0]!=1 or edges[-1]-edges[-2]!=1:
        raise QualificationError('USGS hourly time edges invalid')
    lat=file['lat'][:].astype(float);lon=file['lon'][:].astype(float)
    station_index=list(range(len(lat)))
    variables={}
    for name,unit in [('Hs','meters'),('Tm','seconds'),('Dm','degrees')]:
        obj=file[name];attrs={k:clean_attr(v) for k,v in obj.attrs.items() if k in ('units','long_name','_FillValue','missing_value','scale_factor','add_offset')}
        if obj.shape!=(len(time),len(lat)) or clean_attr(obj.attrs.get('units'))!=unit:
            raise QualificationError('USGS native quantity dimensions/units changed')
        variables[name]=dict(shape=list(obj.shape),dtype=str(obj.dtype),attributes=attrs)
    return dict(attributes={k:clean_attr(v) for k,v in file.attrs.items()},time_units=units,time_edges=edges.tolist(),
                original_latitude=lat.tolist(),original_longitude=lon.tolist(),station_index=station_index,variables=variables)


def qualify(files,*,mapping_path=None,opener=Remote):
    mapping=json.loads(Path(mapping_path).read_text()) if mapping_path else None
    reports={};qualified={};reasons=[]
    if mapping and (mapping.get('release_doi')!=DOI or not mapping.get('effective_coordinate_evidence_url')):
        raise QualificationError('Effective-coordinate mapping needs release DOI and authoritative evidence URL')
    for name,url in files.items():
        with opener(url) as remote,h5py.File(remote,'r') as file:
            spec=header(file)
            digest=hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()
            native_pair=all(k in file for k in ('lat_10mIso','lon_10mIso'))
            evidence=(mapping or {}).get('files',{}).get(name)
            if native_pair:
                lat=file['lat_10mIso'][:].astype(float);lon=file['lon_10mIso'][:].astype(float)
                origin='native lat_10mIso/lon_10mIso'
            elif evidence and evidence.get('source_header_sha256')==digest and evidence.get('station_index')==spec['station_index']:
                lat=np.asarray(evidence['latitude'],dtype=float);lon=np.asarray(evidence['longitude'],dtype=float)
                origin=mapping['effective_coordinate_evidence_url']
            else:
                lat=lon=None;origin=None;reasons.append(name+': effective 10 m-isobath coordinates absent/unqualified')
            if lat is not None:
                if (lat.shape!=(len(spec['original_latitude']),) or lon.shape!=lat.shape or not np.isfinite(lat).all()
                        or not np.isfinite(lon).all() or (np.abs(lat)>90).any() or (np.abs(lon)>180).any()):
                    raise QualificationError('USGS effective-coordinate station identity/shape invalid')
                qualified[name]=dict(url=url,latitude=lat.tolist(),longitude=lon.tolist(),coordinate_evidence=origin,
                    header_sha256=digest,header=spec,source_http_identity=list(remote.identity) if getattr(remote,'identity',None) else None,direction_from_evidence=(mapping or {}).get('direction_from_true_north_evidence_url'))
            reports[name]=dict(url=url,header=spec,header_sha256=digest,effective_coordinates_qualified=lat is not None,
                range_bytes=getattr(remote,'bytes',None),range_hashes=getattr(remote,'records',[]),file_bytes=getattr(remote,'size',None))
    report=dict(provider='usgs-nearshore',release_doi=DOI,rights='CC0; attribution USGS',qualified=not reasons,reasons=reasons,
        files=reports,mapping_sha256=sha(mapping_path) if mapping_path else None,
        checked_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
        direction='FROM only with explicit supporting evidence; otherwise direction remains null',
        period='source Tm mean; moment unspecified',spatial_warning='Original coordinates are reference points, not effective model output locations')
    return report,qualified


def decode(obj,start,stop,indices,hs=None):
    raw=obj[start:stop,:][:,indices];missing=~np.isfinite(raw)
    for key in ('_FillValue','missing_value'):
        for fill in np.asarray(obj.attrs.get(key,[])).ravel():missing|=raw==fill
    value=raw.astype(float)*float(np.asarray(obj.attrs.get('scale_factor',1)).item())+float(np.asarray(obj.attrs.get('add_offset',0)).item())
    value[missing]=np.nan
    if hs is not None:value[hs<.05]=np.nan
    return value


def run(study_path,start=None,end=None,*,output=None,work=None,mapping_path=None,qualify_only=False,files=None,opener=Remote):
    """Qualify, then generate separate hourly/daily products; no unqualified fallback."""
    import fcntl
    study,members,evidence=study_inputs(study_path)
    data=(Path(study_path).resolve().parent/study['storage']['data_root']).resolve()
    output=Path(output).absolute() if output else data/'Oceanography/waves-usgs-nearshore'
    work=Path(work).absolute() if work else data.parent/'.marinecast-work/oceanography/waves-usgs-nearshore'
    if work.is_symlink() or output.is_symlink():raise ValueError('Symlink USGS roots refused')
    work=work.resolve();output=output.resolve()
    common.delivery_target(output,'usgs-nearshore',evidence)
    if data==work or data in work.parents or work==output or work in output.parents or output in work.parents:
        raise ValueError('USGS work must be outside Data and separate from delivery')
    work.mkdir(parents=True,exist_ok=True);owner=dict(provider='usgs-nearshore',study=evidence,output=str(output))
    if (work/'owner.json').exists():
        if json.loads((work/'owner.json').read_text())!=owner:raise ValueError('USGS work ownership mismatch')
    elif any(work.iterdir()):raise ValueError('Unowned USGS work preserved')
    else:atomic_json(work/'owner.json',owner)
    with (work/'run.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        report,qualified=qualify(files or release_files(),mapping_path=mapping_path,opener=opener)
        atomic_json(work/'qualification.json',report)
        if qualify_only:return dict(qualification_path=str(work/'qualification.json'),qualified=report['qualified'])
        if not report['qualified']:
            raise QualificationError('USGS H3 publication blocked: effective 10 m-isobath coordinates absent; see '+str(work/'qualification.json'))
        coordinates=[(lat,lon) for q in qualified.values() for lat,lon in zip(q['latitude'],q['longitude'])]
        if len(set(coordinates))!=len(coordinates):
            raise QualificationError('Duplicate effective USGS points require source-qualified station deduplication before averaging')
        first=dt.date.fromisoformat(start or study['time']['start'])
        native_start=max(q['header']['time_edges'][0] for q in qualified.values())
        native_end=min(q['header']['time_edges'][-1] for q in qualified.values())
        origin=pd.Timestamp('1941-01-01',tz='UTC');last_time=origin+pd.Timedelta(hours=native_end)
        last=dt.date.fromisoformat(end) if end else last_time.date()
        if (first<dt.date.fromisoformat(study['time']['start']) or first>last or last>=dt.date.fromisoformat(study['time']['end_exclusive'])
                or first<(origin+pd.Timedelta(hours=native_start)).date() or last>last_time.date()):
            raise ValueError('USGS requested dates outside study/source support')
        cells=members[5];code={n:sha(Path(__file__).parent/n) for n in ('waves_usgs.py','waves_regional.py','waves_ssc.py','waves.py','daily.py','history.py')}
        plan=dict(provider='usgs-nearshore',start=str(first),end=str(last),cells=cells,study=evidence,sources=qualified,
                  qualification=report,code_sha256=code,source_end_time=str(last_time))
        if (work/'plan.json').exists():
            old=json.loads((work/'plan.json').read_text())
            # Retrieval timestamps/range receipts may differ; scientific and source identity must match.
            if any(old[k]!=plan[k] for k in ('provider','start','end','cells','study','sources','code_sha256')):
                raise ValueError('Frozen USGS plan differs; use a new owned work/output')
            plan=old
        else:atomic_json(work/'plan.json',plan)
        maps={name:common.mapping(study_path,q['latitude'],q['longitude'])[1:4] for name,q in qualified.items()}
        checkpoints=work/'checkpoints';checkpoints.mkdir(exist_ok=True)
        # One county at a time, one source request. Keep only H3 monthly reductions in RAM.
        for period in pd.period_range(first,last,freq='M'):
            days=[s.date() for s in pd.date_range(max(first,period.start_time.date()),min(last,period.end_time.date()))]
            pending=[d for d in days if not (checkpoints/str(d)).exists()]
            for day in set(days)-set(pending):common.read_checkpoint(checkpoints/str(day),'usgs-nearshore',day,cells)
            if not pending:continue
            if shutil.disk_usage(work).free<26_000_000_000:raise ValueError('USGS staging disk floor')
            begin=pd.Timestamp(days[0],tz='UTC');hours=len(days)*24;values=np.full((3,hours,len(cells)),np.nan);counts=np.zeros((4,hours,len(cells)),dtype='i4')
            numerator=np.zeros_like(values);denominator=np.zeros_like(values);sine=np.zeros((hours,len(cells)));cosine=np.zeros_like(sine);sources={}
            offset=int((begin-origin).total_seconds()/3600)
            for name,q in qualified.items():
                indices,groups,weights=maps[name]
                if not len(indices):continue
                with opener(q['url']) as remote,h5py.File(remote,'r') as file:
                    if q.get('source_http_identity') is not None and list(remote.identity)!=q['source_http_identity']:
                        raise QualificationError('USGS source HTTP vintage changed from frozen qualification')
                    if hashlib.sha256(json.dumps(header(file),sort_keys=True).encode()).hexdigest()!=q['header_sha256']:
                        raise QualificationError('USGS native header changed during generation')
                    stop=min(offset+hours,len(file['time']));axis=file['time'][offset:stop].astype(float)
                    if not np.array_equal(axis,np.arange(offset,stop)):raise QualificationError('USGS hourly axis incomplete or shifted')
                    raw=np.full((3,hours,len(indices)),np.nan);h=decode(file['Hs'],offset,stop,indices)
                    raw[0,:len(axis)]=h;raw[1,:len(axis)]=decode(file['Tm'],offset,stop,indices,h)
                    if q['direction_from_evidence']:raw[2,:len(axis)]=decode(file['Dm'],offset,stop,indices,h)
                    # Accumulate native point means across county files, never means of county means.
                    raw[0][raw[0]<0]=np.nan;raw[1][raw[1]<=0]=np.nan;raw[2][(raw[2]<0)|(raw[2]>360)|(raw[0]==0)]=np.nan
                    raw[2]%=360
                    for t in range(hours):
                        counts[0,t]+=np.bincount(groups,minlength=len(cells))
                        for k in range(3):
                            good=np.isfinite(raw[k,t]);w=weights[good];g=groups[good];a=raw[k,t,good]
                            counts[k+1,t]+=np.bincount(g,minlength=len(cells));denominator[k,t]+=np.bincount(g,weights=w,minlength=len(cells))
                            if k<2:numerator[k,t]+=np.bincount(g,weights=w*a,minlength=len(cells))
                            else:
                                sine[t]+=np.bincount(g,weights=w*np.sin(np.deg2rad(a)),minlength=len(cells));cosine[t]+=np.bincount(g,weights=w*np.cos(np.deg2rad(a)),minlength=len(cells))
                    sources[name]=dict(url=q['url'],range_bytes=getattr(remote,'bytes',None),ranges=getattr(remote,'records',[]),header_sha256=q['header_sha256'])
            np.divide(numerator[:2],denominator[:2],out=values[:2],where=denominator[:2]>0)
            angle=np.degrees(np.arctan2(sine,cosine))%360;angle[np.isclose(angle,360,atol=1e-10,rtol=0)]=0
            valid=(denominator[2]>0)&(np.hypot(sine,cosine)>denominator[2]*1e-12);values[2,valid]=angle[valid]
            for i,day in enumerate(days):
                if day not in pending:continue
                selection=slice(i*24,(i+1)*24);tables=common.day_tables('usgs-nearshore',day,values[:,selection],counts[:,selection],cells)
                common.checkpoint(checkpoints,'usgs-nearshore',day,tables,cells,dict(status='available',sources=sources,
                    source_end_time=str(last_time),direction_qualified=all(q['direction_from_evidence'] for q in qualified.values())))
            atomic_json(work/'progress.json',dict(status='running',last_completed_month=str(period),source_end_time=str(last_time)))
        return common.finalize(work,output,plan,study_path)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('study','start','end','output','work','mapping-path','check'):p.add_argument('--'+key,required=key=='study')
    p.add_argument('--qualify-only',action='store_true');a=p.parse_args(argv)
    result=common.check(a.check,study_path=a.study) if a.check else run(a.study,a.start,a.end,output=a.output,work=a.work,mapping_path=a.mapping_path,qualify_only=a.qualify_only)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
