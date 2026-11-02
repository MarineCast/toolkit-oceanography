import numpy as np
import pytest
pytest.importorskip('numcodecs')
import numcodecs,xarray as xr
from oceanography.glorys import decode_chunk,unpack,surface_index

def test_standard_cf_unpack_and_compressed_chunk():
    packed=np.array([[[[-32767,0,2,10]]]],dtype='<i2');codec=numcodecs.Blosc(cname='lz4',clevel=5,shuffle=1)
    spec=dict(zarr_format=2,order='C',filters=None,chunks=list(packed.shape),dtype='<i2',compressor=codec.get_config(),fill_value=-32767)
    decoded=decode_chunk(codec.encode(packed),spec);np.testing.assert_array_equal(decoded,packed)
    attrs={'scale_factor':.25,'add_offset':1.0,'_FillValue':-32767}
    reference=xr.decode_cf(xr.Dataset({'v':xr.DataArray(packed,dims=['t','z','y','x'],attrs=attrs)})).v.values
    np.testing.assert_array_equal(unpack(decoded,spec,attrs),reference)

def test_arco_surface_is_last_not_first():
    elevation=-np.linspace(5727.917,.494024992,50)
    assert surface_index(elevation)==49
    with pytest.raises(ValueError):surface_index(-elevation)

def test_daily_mean_vector_speed_is_distinct():
    hourly=np.array([1.,-1.]);assert np.abs(hourly).mean()==1
    assert np.abs(hourly.mean())==0
