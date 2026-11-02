"""Offline scientific/support and publication regression checks for Waves."""
import datetime as dt
import hashlib
import json
from pathlib import Path

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from shapely.geometry import box

import oceanography.waves as w
from oceanography.daily import sha
from oceanography.waves_source import BASE, FIELDS, Source


def test_wmo_exact_boundaries_zero_unknown_and_invalid():
    heights = np.array([0, .001, .1, .10001, .5, 1.25, 2.5, 4, 6, 9, 14, 14.001, -1, np.nan, np.inf])
    np.testing.assert_equal(w.sea_state(heights), [0, 1, 1, 2, 2, 3, 4, 5, 6, 7, 8, 9, np.nan, np.nan, np.nan])


def test_circular_direction_wrap_and_undefined_resultant():
    a = np.ones((3, 24, 2)); a[1] = 6
    a[2, :12] = [359, 90]; a[2, 12:] = [1, 270]
    result = w.summarize(w.sanitize(a))
    assert result[3][0] == pytest.approx(0, abs=1e-10)
    assert np.isnan(result[3][1])
    np.testing.assert_equal(result[4], [3, 3])


def test_complete_support_is_independent_and_calm_direction_unknown():
    a = np.ones((3, 24, 3)); a[1] = 6; a[2] = 360
    a[0, 0, 0] = np.nan; a[1, 0, 1] = 0; a[0, :, 2] = 0
    cleaned = w.sanitize(a); out = w.summarize(cleaned)
    assert np.isnan(out[0][0]) and out[2][0] == 6
    assert out[0][1] == 1 and np.isnan(out[2][1])
    assert out[0][2] == 0 and out[4][2] == 0 and np.isnan(out[3][2])
    assert out[3][1] == 0  # 360 canonicalizes to north, not missing.


def test_all_cell_keys_and_unsupported_nulls():
    cells = ['native', 'unsupported']
    a = np.ones((3, 24, 1)); a[1] = 8; a[2] = 270
    result = w.tables(dt.date(2012, 2, 29), a, [{'h3_index': 'native'}], cells)
    assert result['hourly']['h3_index'].to_pylist() == cells*24
    assert result['hourly']['datetime'][0].as_py().isoformat() == '2012-02-29T00:00:00+00:00'
    for f, names in [('hourly', w.HOURLY), ('daily', w.DAILY)]:
        for name in names:
            assert all(v is None for v in result[f][name].to_pylist()[1::2])
        assert result[f].schema == w.schema(f)


@pytest.fixture
def study(tmp_path):
    mask = tmp_path/'mask.parquet'
    gpd.GeoDataFrame(geometry=[box(-123.1, 47.9, -122.9, 48.1)], crs='EPSG:4326').to_parquet(mask)
    manifest = tmp_path/'registry.json'; manifest.write_text('{}')
    reg = dict(status='validated', mask_revision='v1', mask_relative_path=mask.name,
               mask_sha256=sha(mask), manifest_relative_path=manifest.name,
               manifest_sha256=sha(manifest), memberships=[])
    for resolution in (5, 6):
        cells = sorted({h3.latlng_to_cell(48, -123, resolution), h3.latlng_to_cell(49, -124, resolution)})
        path = tmp_path/f'r{resolution}.txt'; path.write_text('\n'.join(cells)+'\n')
        reg['memberships'].append(dict(resolution=resolution, role='water_reporting',
                                      relative_path=path.name, sha256=sha(path), count=len(cells)))
    value = dict(study_id='waves-test', domain=dict(status='approved', revision='v1',
                 bbox_wgs84=[-125, 47, -122, 50]), grid_registry=reg,
                 time=dict(start='2009-01-01', end_exclusive='2010-01-01'),
                 storage=dict(data_root='Data'))
    path = tmp_path/'study.json'; path.write_text(json.dumps(value))
    return path


class Native:
    """Independent tiny instantaneous source with changing retrieval vintages."""
    revision = 0
    final_hour = 23
    def __init__(self, *args, **kwargs):
        self.times = pd.date_range('2009-01-01', f'2009-01-03T{self.final_hour:02d}:00', freq='h', tz='UTC').as_unit('s').asi8
        self.lat = np.array([48., 48.5, 49.]); self.lon = np.array([-124., -123.5, -123.])
        self.meta = {name+'/.zattrs': {'fixture_revision': self.revision} for name in FIELDS}
        self.metadata_sha256 = hashlib.sha256(str(self.revision).encode()).hexdigest()
        self.used = {}; self.requests = self.bytes = self.peak = 0
    def day(self, day, points):
        a = np.ones((3, 24, len(points)))
        a[0] = day.day+self.revision; a[1] = 8; a[2] = 270
        if day == dt.date(2009, 1, 3):
            a[:, self.final_hour+1:] = np.nan
        return a


def test_mapping_uses_native_centre_inside_mask_not_nearest(study):
    value, members, _ = w.study_inputs(study)
    points = w.spatial_support(study, Native(), value, members[5])
    assert points == [dict(y=0, x=2, latitude=48., longitude=-123., h3_index=h3.latlng_to_cell(48, -123, 5))]


def test_append_preserves_vintage_and_full_reader(study, monkeypatch):
    monkeypatch.setattr(w, 'Source', Native); monkeypatch.setattr(Native, 'revision', 0)
    first = w.run_waves(study, '2009-01-01', '2009-01-01', offline=True)
    output = Path(first['catalog_path']).parent
    old = pq.read_table(output/'waves-hourly.parquet').to_pydict()
    monkeypatch.setattr(Native, 'revision', 10)
    w.run_waves(study, '2009-01-02', '2009-01-03', offline=True)
    result = w.check_waves(output/'catalog.json', study_path=study)
    assert result['coverage']['ever_finite_height_cells'] == 1
    assert result['coverage']['no_geometric_support_cells'] == 1
    assert pq.ParquetFile(output/'waves-hourly.parquet').read_row_group(0).to_pydict() == old
    cat = json.loads((output/'catalog.json').read_text())
    assert len(cat['source_epochs']) == 2 and len(cat['source_evidence']) == 2
    assert cat['source_epochs'][0]['end'] == '2009-01-01'
    assert cat['source_epochs'][1]['start'] == '2009-01-02'
    assert w.run_waves(study, '2009-01-01', '2009-01-03', offline=True)['unchanged']


def test_partial_frontier_is_explicit_and_daily_remains_null(study, monkeypatch):
    monkeypatch.setattr(w, 'Source', Native); monkeypatch.setattr(Native, 'final_hour', 12)
    with pytest.raises(ValueError, match='complete source'):
        w.run_waves(study, '2009-01-03', '2009-01-03', offline=True)
    result = w.run_waves(study, '2009-01-03', '2009-01-03', offline=True, allow_partial_final_day=True)
    output = Path(result['catalog_path']).parent
    for name in w.DAILY:
        assert pq.read_table(output/'waves-daily.parquet')[name].null_count == 2
    assert w.check_waves(output/'catalog.json', study_path=study)['valid']


def test_failed_publication_and_unowned_paths_preserved(study, monkeypatch):
    monkeypatch.setattr(w, 'Source', Native)
    result = w.run_waves(study, '2009-01-01', '2009-01-01', offline=True)
    output = Path(result['catalog_path']).parent
    hashes = {p.name: sha(p) for p in output.iterdir()}
    def fail(*args):
        raise OSError('publication failure')
    monkeypatch.setattr(w, 'publish', fail)
    with pytest.raises(OSError):
        w.run_waves(study, '2009-01-02', '2009-01-02', offline=True)
    assert hashes == {p.name: sha(p) for p in output.iterdir()}
    (output/'unrelated.txt').write_text('preserve')
    with pytest.raises(ValueError, match='Unrelated'):
        w.run_waves(study, '2009-01-02', '2009-01-02')
    assert (output/'unrelated.txt').read_text() == 'preserve'


def test_reader_detects_filled_unsupported_cell_even_with_updated_hash(study, monkeypatch):
    monkeypatch.setattr(w, 'Source', Native)
    result = w.run_waves(study, '2009-01-01', '2009-01-01', offline=True)
    output = Path(result['catalog_path']).parent
    path = output/'waves-hourly.parquet'; table = pq.read_table(path)
    values = table[w.HOURLY[0]].to_pylist()
    values[values.index(None)] = 1.5
    table = table.set_column(table.schema.get_field_index(w.HOURLY[0]), w.HOURLY[0], pa.array(values))
    pq.write_table(table, path)
    cat = json.loads((output/'catalog.json').read_text()); entry = cat['products']['hourly']
    entry.update(sha256=sha(path), bytes=path.stat().st_size)
    (output/'catalog.json').write_text(json.dumps(cat))
    with pytest.raises(ValueError, match='Unsupported'):
        w.check_waves(output/'catalog.json', study_path=study)


@pytest.fixture
def native_objects():
    nc = pytest.importorskip('numcodecs'); codec = nc.Blosc(cname='lz4', clevel=5, shuffle=1)
    meta, objects = {}, {}
    coords = dict(time=pd.date_range('2009-01-01', periods=48, freq='h', tz='UTC').as_unit('s').asi8,
                  latitude=np.array([-90., -89.5]), longitude=np.arange(-180, -178, .5))
    for name, values in coords.items():
        meta[name+'/.zarray'] = dict(zarr_format=2, chunks=[len(values)], shape=[len(values)],
             dtype=values.dtype.str, order='C', filters=None, compressor=codec.get_config())
        meta[name+'/.zattrs'] = dict(units='seconds since 1970-01-01', calendar='proleptic_gregorian') if name == 'time' else {}
        objects[name+'/0'] = codec.encode(values)
    for name, (pid, units) in FIELDS.items():
        meta[name+'/.zarray'] = dict(zarr_format=2, chunks=[135168, 2, 4], shape=[48, 2, 4],
              dtype='<f4', order='C', filters=None, compressor=codec.get_config(), fill_value='NaN')
        meta[name+'/.zattrs'] = dict(units=units, GRIB_paramId=pid, GRIB_stepType='instant',
             GRIB_missingValue=float(np.finfo('f4').max), _ARRAY_DIMENSIONS=['time', 'latitude', 'longitude'])
        values = np.full((135168, 2, 4), np.nan, dtype='<f4')
        values[:48, 1, 1] = {'swh': 1.5, 'mwp': 8, 'mwd': 270}[name]
        values[3, 1, 1] = np.finfo('f4').max
        values[:48, 1, 2] = 0
        objects[name+'/0.0.0'] = codec.encode(values)
    objects['.zmetadata'] = json.dumps({'metadata': meta}).encode()
    return objects


def test_source_native_extraction_fill_time_and_checksum(tmp_path, native_objects):
    source = Source(tmp_path, fetcher=native_objects.__getitem__)
    points = [dict(y=1, x=1), dict(y=1, x=2)]
    result = source.day(dt.date(2009, 1, 1), points)
    assert result.shape == (3, 24, 2)
    np.testing.assert_equal(result[:, 0, 0], [1.5, 8, 270])
    assert np.isnan(result[:, 3, 0]).all()
    assert (result[:, :, 1] == 0).all()
    assert np.isnan(source.day(dt.date(2009, 1, 3), points)).all()
    assert source.requests == 7
    source2 = Source(tmp_path, offline=True)
    assert source2.requests == 0
    p = tmp_path/'swh/0.0.0'; p.write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='Corrupt'):
        source2.day(dt.date(2009, 1, 1), points)


def test_source_identity_drift_and_unpaired_cache_refused(tmp_path, native_objects):
    metadata = json.loads(native_objects['.zmetadata'])
    metadata['metadata']['mwd/.zattrs']['units'] = 'radians'
    native_objects['.zmetadata'] = json.dumps(metadata).encode()
    with pytest.raises(ValueError, match='identity/layout'):
        Source(tmp_path, fetcher=native_objects.__getitem__)
    path = tmp_path/'other'; path.mkdir(); (path/'.zmetadata').write_text('unpaired')
    with pytest.raises(ValueError, match='Incomplete'):
        Source(path, fetcher=native_objects.__getitem__)


def test_online_updates_use_distinct_bounded_snapshots(study, monkeypatch):
    seen = []
    class Fresh(Native):
        def __init__(self, root, **options):
            seen.append((Path(root), Path(options['budget_root'])))
            super().__init__(root, **options)
    monkeypatch.setattr(w, 'Source', Fresh)
    w.run_waves(study, '2009-01-01', '2009-01-01')
    result = w.run_waves(study, '2009-01-01')
    assert len(seen) == 2 and seen[0][0] != seen[1][0]
    assert seen[0][1] == seen[1][1] == seen[0][0].parent
    assert w.check_waves(result['catalog_path'], study_path=study)['date_end'] == '2009-01-03'


def test_unowned_source_directory_refused(study, tmp_path, monkeypatch):
    monkeypatch.setattr(w, 'Source', Native)
    cache = tmp_path/'unrelated'; cache.mkdir(); (cache/'source.nc').write_text('preserve')
    with pytest.raises(ValueError, match='ownership'):
        w.run_waves(study, '2009-01-01', '2009-01-01', cache_dir=cache)
    assert (cache/'source.nc').read_text() == 'preserve'


def test_budget_counts_other_snapshots_and_preserves_sources(tmp_path, native_objects, monkeypatch):
    source = Source(tmp_path/'current', budget_root=tmp_path, fetcher=native_objects.__getitem__)
    other = tmp_path/'previous'; other.mkdir()
    with (other/'retained').open('wb') as handle:
        handle.truncate(300_000_001)  # Sparse file, no large allocation.
    with pytest.raises(ValueError, match='budget'):
        source.object('swh/0.0.0')
    assert (other/'retained').stat().st_size == 300_000_001
    assert not (tmp_path/'current/swh/0.0.0').exists()
