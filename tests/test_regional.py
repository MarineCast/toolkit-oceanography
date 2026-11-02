import numpy as np
import pytest
from oceanography.regional import rotation,collocate_rotate

def test_local_rotation_due_east_and_north():
 lon,lat=np.meshgrid([0.,.01,.02],[40.,40.01,40.02]);a=rotation(lon,lat)
 np.testing.assert_allclose(a,0,atol=1e-8)
 u=np.ones((24,3,3));v=np.zeros_like(u);east,north=collocate_rotate(u,v,a)
 np.testing.assert_allclose(east,1,atol=1e-12);np.testing.assert_allclose(north,0,atol=1e-8)
 east,north=collocate_rotate(u,v,np.full((2,2),np.pi/2))
 np.testing.assert_allclose(east,0,atol=1e-12);np.testing.assert_allclose(north,1,atol=1e-12)

def test_stagger_alignment_and_magnitude():
 u=np.broadcast_to(np.arange(4),(3,4)).astype(float);v=np.broadcast_to(np.arange(3)[:,None],(3,4)).astype(float);a=np.full((2,3),.5)
 east,north=collocate_rotate(u,v,a)
 uc=np.array([[.5,1.5,2.5],[.5,1.5,2.5]]);vc=np.array([[.5,.5,.5],[1.5,1.5,1.5]])
 np.testing.assert_allclose(np.hypot(east,north),np.hypot(uc,vc))
 np.testing.assert_allclose(east,uc*np.cos(.5)-vc*np.sin(.5))
 with pytest.raises(ValueError):collocate_rotate(u,v,np.zeros((3,3)))

def test_missing_face_is_not_zero():
 u=np.ones((2,3));v=np.zeros((2,3));u[1,0]=np.nan
 east,north=collocate_rotate(u,v,np.zeros((1,2)))
 assert np.isnan(east[0,0]) and np.isnan(north[0,0])
 assert east[0,1]==1 and north[0,1]==0
