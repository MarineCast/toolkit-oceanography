"""Whole-H3-cell request partitions preserving complete native wet support."""
import numpy as np
import pandas as pd

from .liveocean import require


def area(bounds):
    return int((bounds[1]-bounds[0]+1)*(bounds[3]-bounds[2]+1))


def enclosing(bounds):
    return np.array([bounds[:,0].min(),bounds[:,1].max(),bounds[:,2].min(),bounds[:,3].max()])


def split(bounds):
    """Find a compact two-way split of whole cells; rectangles may overlap."""
    if len(bounds)<2:return None
    best=None;parent=area(enclosing(bounds))
    for lo,hi in [(0,1),(2,3)]:
        order=np.argsort(bounds[:,lo]+bounds[:,hi],kind='stable');b=bounds[order]
        prefix=np.column_stack([np.minimum.accumulate(b[:,0]),np.maximum.accumulate(b[:,1]),
                                np.minimum.accumulate(b[:,2]),np.maximum.accumulate(b[:,3])])
        reverse=b[::-1]
        suffix=np.column_stack([np.minimum.accumulate(reverse[:,0]),np.maximum.accumulate(reverse[:,1]),
                                np.minimum.accumulate(reverse[:,2]),np.maximum.accumulate(reverse[:,3])])[::-1]
        a,c=prefix[:-1],suffix[1:]
        size=(a[:,1]-a[:,0]+1)*(a[:,3]-a[:,2]+1)+(c[:,1]-c[:,0]+1)*(c[:,3]-c[:,2]+1)
        cut=int(np.argmin(size))+1;gain=parent-int(size[cut-1])
        if best is None or gain>best[0]:best=(gain,order[:cut],order[cut:])
    return best


def partitions(ctx,name,selected,max_tiles=4):
    require(1<=max_tiles<=16,'Tile count must be 1..16')
    mask=ctx['masks'][name]&np.isin(ctx['ids'],selected)
    if not mask.any():return []
    yy,xx=np.indices(ctx['shape']);points=pd.DataFrame({'id':ctx['ids'][mask],
        'y':yy.ravel()[mask]+ctx['bounds'][0],'x':xx.ravel()[mask]+ctx['bounds'][2]})
    grouped=points.groupby('id',sort=True).agg(ymin=('y','min'),ymax=('y','max'),xmin=('x','min'),xmax=('x','max'),points=('id','size'))
    cells=grouped.index.to_numpy();bounds=grouped[['ymin','ymax','xmin','xmax']].to_numpy();groups=[np.arange(len(cells))]
    while len(groups)<max_tiles:
        candidates=[(split(bounds[g]),i) for i,g in enumerate(groups) if len(g)>1]
        if not candidates:break
        candidate,index=max(candidates,key=lambda item:item[0][0])
        if candidate[0]<=0:break
        group=groups.pop(index);groups.extend([group[candidate[1]],group[candidate[2]]])
    result=[{'cells':sorted(cells[g].tolist()),'bounds':enclosing(bounds[g]).tolist(),
             'native_positions':area(enclosing(bounds[g])),
             'required_native_points':int(grouped.iloc[g].points.sum())} for g in groups]
    result.sort(key=lambda p:p['cells'])
    assigned=[c for p in result for c in p['cells']]
    require(len(assigned)==len(set(assigned)) and set(assigned)==set(cells),'Tile assignment lost/duplicated cells')
    return result
