import numpy as np
import pytest
from oceanography import regional_tiles as rt
from oceanography.surface_history import target_context


def test_tiles_keep_every_point_of_a_cell_including_disconnected_parts():
    ids=np.full((20,20),'',dtype='U2');ids[0:2,0:2]='a';ids[18:20,18:20]='b';ids[2,18]='c';ids[3,17]='c'
    ids[10,4]='a'  # Same H3 extends across the proposed geometric split.
    ctx={'shape':ids.shape,'bounds':[1,20,1,20],'cells':['a','b','c','x'],'ids':ids.ravel(),
         'weights':np.ones(ids.size),'masks':{'oxygen':(ids!='').ravel()}}
    # target_context expects a mask for every scalar; their content is irrelevant here.
    ctx['masks'].update(salinity=ctx['masks']['oxygen'],nitrate=ctx['masks']['oxygen'])
    tiles=rt.partitions(ctx,'oxygen',['a','b','c'],4)
    assert len(tiles)==3 and sum(t['required_native_points'] for t in tiles)==11
    assert sum(t['native_positions'] for t in tiles)<400
    for tile in tiles:
        narrow=target_context(ctx,'oxygen',tile['cells'])
        assert narrow['bounds']==tile['bounds']
        assert int(narrow['masks']['oxygen'].sum())==tile['required_native_points']
    assert sorted(c for t in tiles for c in t['cells'])==['a','b','c']
    assert rt.partitions(ctx,'oxygen',['x'],4)==[]
    with pytest.raises(ValueError):rt.partitions(ctx,'oxygen',['a'],0)


def test_deterministic_single_tile_and_no_increased_request_area():
    rng=np.random.default_rng(8);bounds=[]
    for _ in range(30):
        y,x=rng.integers(0,100,size=2);bounds.append([y,y+2,x,x+3])
    b=np.array(bounds);s=rt.split(b)
    assert s[0]>=0
    assert rt.area(rt.enclosing(b))>=rt.area(rt.enclosing(b[s[1]]))+rt.area(rt.enclosing(b[s[2]]))
    assert rt.split(b[:1]) is None
