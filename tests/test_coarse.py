import datetime as dt
import numpy as np
import pandas as pd
import pytest
import xarray as xr
from oceanography.coarse import daily_samples,qualify,validate,subset_url

def test_speed_before_temporal_mean():
 s=np.full((8,2,2),30.);u=np.ones_like(s);u[4:]=-1;v=np.zeros_like(s)
 a=daily_samples(s,u,v)
 assert np.all(a['current_east_m_s']==0)
 assert np.all(a['current_speed_m_s']==1)

def test_joint_complete_support_and_zero():
 s=np.zeros((8,1,2));u=s.copy();v=s.copy();u[0,0,0]=np.nan
 a=daily_samples(s,u,v)
 assert a['salinity_psu'][0,0]==0
 assert all(np.isnan(a[m][0,0]) for m in ['current_east_m_s','current_north_m_s','current_speed_m_s'])
 assert a['current_speed_m_s'][0,1]==0

def test_source_contract():
 d=xr.Dataset({'water_u':(('time','depth','lat','lon'),np.zeros((8,1,2,2)),{'units':'m/s','standard_name':'eastward_sea_water_velocity'})},coords={'time':pd.date_range('2024-07-01',periods=8,freq='3h'),'depth':('depth',[0.],{'units':'m','positive':'down'}),'lat':[46,46.04],'lon':[231,231.08]})
 day=dt.date(2024,7,1);bbox=[-129,46,-128.92,46.04]
 qualify(d,['water_u'],day,day,bbox)
 for bad in [d.isel(time=slice(1,None)),d.assign_coords(depth=[2])]:
  with pytest.raises(ValueError):qualify(bad,['water_u'],day,day,bbox)
 d.water_u.attrs['standard_name']='grid_eastward_sea_water_velocity'
 with pytest.raises(ValueError):qualify(d,['water_u'],day,day,bbox)

def test_output_identity_and_vector_inequality():
 day=dt.date(2024,7,1);metrics=['current_east_m_s','current_north_m_s','current_speed_m_s']
 f=pd.DataFrame([[day,'a',1.,0.,1.],[day,'b',np.nan,np.nan,np.nan]],columns=['date','h3_index',*metrics])
 validate(f,metrics,[day],['a','b'])
 with pytest.raises(ValueError):validate(f.iloc[::-1],metrics,[day],['a','b'])
 f.loc[0,'current_speed_m_s']=.5
 with pytest.raises(ValueError):validate(f,metrics,[day],['a','b'])

def test_subset_surface_only():
 u=subset_url('uv3z',dt.date(2024,7,1),dt.date(2024,7,3),[-129.7,45.9,-121.5,51.5])
 assert 'vertCoord=0' in u and 'var=water_u&var=water_v' in u and 'timeStride=1' in u
 with pytest.raises(ValueError):subset_url('uv3z',dt.date(2023,12,31),dt.date(2024,1,1),[-129,46,-128,47])


def test_network_multiday_rejected_before_io():
 from oceanography.coarse import request_sources
 class FakeCache:
  offline=False
  def get(self,*args):raise AssertionError('Must not make network request')
 with pytest.raises(ValueError,match='at most one day'):
  request_sources(FakeCache(),dt.date(2024,7,1),dt.date(2024,7,3),[-129.7,45.9,-121.5,51.5])
