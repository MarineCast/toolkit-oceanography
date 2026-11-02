import numpy as np
import pytest
from oceanography.regional import collocate_rotate

def test_hourly_speed_cannot_be_replaced_by_daily_vector_magnitude():
    u=np.ones((24,2,2));u[12:]*=-1;v=np.zeros_like(u)
    east,north=collocate_rotate(u,v,np.zeros((1,1)))
    assert np.hypot(east,north).mean()==1
    assert np.hypot(east.mean(),north.mean())==0

def test_streaming_refuses_incomplete_day(monkeypatch):
    import pandas as pd
    import xarray as xr
    from oceanography.regional_streaming import temporal_means
    monkeypatch.setattr(xr,'open_dataset',lambda path:xr.Dataset(coords={'time':pd.date_range('2009-01-01T00:30',periods=23,freq='h')}))
    with pytest.raises(ValueError,match='Incomplete hourly'):
        temporal_means(dict(salinity='s',u='u',v='v'),'2009-01-01',np.zeros((1,1)))
