import gzip,json,hashlib
import pytest
from oceanography import regional_history as h

def test_cache_cap_prevents_growth(tmp_path,monkeypatch):
    (tmp_path/'retained').write_bytes(b'1234');monkeypatch.setattr(h,'CAP',5)
    with pytest.raises(ValueError,match='cache cap'):h.budget(tmp_path,2)
    assert (tmp_path/'retained').read_bytes()==b'1234'

def test_compressed_and_raw_binding(tmp_path):
    p=tmp_path/'x.nc.gz';p.write_bytes(gzip.compress(b'native'));r=p.with_suffix('.json')
    meta=dict(compressed_sha256=h.sha(p),sha256=hashlib.sha256(b'native').hexdigest(),bytes=6);r.write_text(json.dumps(meta));assert h.checked_source(p,r)==meta
    meta['sha256']='incorrect';r.write_text(json.dumps(meta))
    with pytest.raises(ValueError,match='Decoded source checksum'):h.checked_source(p,r)

def test_offline_cannot_download(tmp_path):
    root=tmp_path/'cache';(root/'sources').mkdir(parents=True)
    with pytest.raises(ValueError,match='Offline source unavailable'):h.acquire(root,'u','2024-01-01',tmp_path/'missing',True)
