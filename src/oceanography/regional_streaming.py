"""Low-memory SalishSeaCast calculation; same complete-hour and mean-speed semantics."""
from __future__ import annotations
from contextlib import ExitStack
import numpy as np
import pandas as pd
import xarray as xr
from .regional import SPECS,collocate_rotate

def temporal_means(paths,day,angle):
    """Read one hourly surface slice per variable; never load full-day arrays."""
    with ExitStack() as stack:
        datasets={kind:stack.enter_context(xr.open_dataset(paths[kind])) for kind in SPECS}
        expected=pd.date_range(str(day)+'T00:30:00',periods=24,freq='h')
        for kind,d in datasets.items():
            var,units,standard=SPECS[kind]
            if not pd.DatetimeIndex(d.time.values).equals(expected):raise ValueError('Incomplete hourly UTC intervals')
            if d.depth.size!=1 or abs(float(d.depth.values[0])-.5000003)>1e-6 or d.depth.attrs.get('positive')!='down' or d.depth.attrs.get('units')!='m':raise ValueError('Regional top-depth mismatch')
            a=d[var]
            if a.dims!=('time','depth','gridY','gridX') or (a.attrs.get('units'),a.attrs.get('standard_name'))!=(units,standard):raise ValueError('Regional variable contract mismatch')
            if d.sizes['gridY']!=898 or d.sizes['gridX']!=398 or not np.array_equal(d.gridY.values,np.arange(898)) or not np.array_equal(d.gridX.values,np.arange(398)):raise ValueError('Regional index grid mismatch')
        sums=[np.zeros(angle.shape,dtype=float) for _ in range(4)];sg=np.ones(angle.shape,dtype=bool);vg=sg.copy()
        for hour in range(24):
            fields={kind:d[SPECS[kind][0]].isel(time=hour,depth=0).values.astype(float) for kind,d in datasets.items()}
            scalar=fields['salinity'][1:,1:];u,v=collocate_rotate(fields['u'],fields['v'],angle)
            sg &= np.isfinite(scalar)&(scalar>=0)&(scalar<=50)
            vg &= np.isfinite(u)&np.isfinite(v)&(np.abs(u)<=10)&(np.abs(v)<=10)
            for total,value in zip(sums,[scalar,u,v,np.hypot(u,v)]):total+=value
        return {name:np.where(valid,total/24,np.nan) for name,total,valid in zip(['reference_salinity_g_kg','current_east_m_s','current_north_m_s','current_speed_m_s'],sums,[sg,vg,vg,vg])}
