"""ZIP/restart checks and ArcPy orchestration; actual GIS checks are separate."""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import stat
from types import SimpleNamespace
from zipfile import ZipFile, ZipInfo

import pytest

from eHydro import process_bathymetry as bathy


class SpatialReference:
    def __init__(self, code=26915, vcs=None, gcs=4269):
        self.code, self.name = code, f'CRS_{code}'
        self.factoryCode = code
        self.type = 'Projected'
        self.linearUnitName, self.metersPerUnit = 'Meter', 1.
        self.GCS = SimpleNamespace(factoryCode=gcs, name=f'GCS_{gcs}')
        self.VCS = SimpleNamespace(name=vcs) if vcs else None

    def exportToString(self):
        return f'WKT:{self.code}'


def info(**overrides):
    return dict(dict(sr=26915, gcs=4269, vcs=None, bands=1, pixel='F32',
                     cell=5., width=2, height=2, extent=[0., 0., 10., 10.],
                     kind='RasterDataset', allnodata=False), **overrides)


class FakeArcPy:
    """Check tool arguments/state transitions, without simulating GIS algorithms."""
    SpatialReference = SpatialReference

    def __init__(self):
        self.datasets, self.events = {}, []
        self.management = SimpleNamespace(**{name: getattr(self, name) for name in (
            'CreateFileGDB', 'Delete', 'CopyRaster', 'Resample', 'ProjectRaster',
            'MosaicToNewRaster', 'Rename', 'GetRasterProperties', 'ClearWorkspaceCache')})
        self.ddd = SimpleNamespace(TinRaster=self.TinRaster)
        self.da = SimpleNamespace(Walk=self.walk)
        self.fail_copy, self.extension = False, 'Available'

    def walk(self, root, **kwargs):
        grouped = {}
        for metadata in Path(root).rglob('*.dataset.json'):
            path = metadata.with_name(metadata.name.removesuffix('.dataset.json'))
            self.datasets[str(path)] = json.loads(metadata.read_text())
            grouped.setdefault(str(path.parent), []).append(path.name)
        for parent, names in grouped.items():
            yield parent, [], names

    def Describe(self, path):
        data = self.datasets[str(path)]
        return SimpleNamespace(spatialReference=SpatialReference(data['sr'], data['vcs'], data['gcs']),
                               dataType=data['kind'])

    def Raster(self, path):
        data = self.datasets[str(path)]
        return SimpleNamespace(bandCount=data['bands'], pixelType=data['pixel'],
                               width=data['width'], height=data['height'],
                               meanCellWidth=data['cell'], meanCellHeight=data['cell'],
                               extent=SimpleNamespace(**dict(zip(('XMin', 'YMin', 'XMax', 'YMax'), data['extent']))))

    def Exists(self, path):
        return str(path) in self.datasets or Path(path).exists()

    def ValidateTableName(self, name, workspace):
        return name

    @contextmanager
    def EnvManager(self, **kwargs):
        self.events.append(('environment', kwargs))
        yield

    def CreateFileGDB(self, parent, name):
        self.events.append(('gdb', name))
        (Path(parent)/name).mkdir()

    def Delete(self, path):
        self.events.append(('delete', str(path)))
        self.datasets.pop(str(path), None)
        if Path(path).is_file():
            Path(path).unlink()

    def _copy(self, source, target, **changes):
        self.datasets[str(target)] = dict(deepcopy(self.datasets[str(source)]), **changes)

    def CopyRaster(self, source, target, **kwargs):
        self.events.append(('copy', source, target, kwargs))
        if self.fail_copy:
            raise RuntimeError('Injected read failure')
        assert kwargs == {'pixel_type': '32_BIT_FLOAT'}  # No zero/NoData override.
        self._copy(source, target, pixel='F32')

    def Resample(self, source, target, size, method):
        self.events.append(('resample', source, target, size, method))
        self._copy(source, target, cell=size)

    def ProjectRaster(self, source, target, sr, **kwargs):
        self.events.append(('project', source, target, sr.code, kwargs))
        self._copy(source, target, sr=sr.code, cell=kwargs['cell_size'])

    def TinRaster(self, source, target, **kwargs):
        self.events.append(('tin', source, kwargs))
        self._copy(source, target, kind='RasterDataset', pixel='F32')

    def MosaicToNewRaster(self, **kwargs):
        self.events.append(('mosaic', kwargs))
        target = Path(kwargs['output_location'])/kwargs['raster_dataset_name_with_extension']
        self._copy(kwargs['input_rasters'][0], target)
        target.write_bytes(b'FAKE TIFF (not GIS validation)')

    def Rename(self, source, target, datatype):
        self.events.append(('rename', source, target))
        self.datasets[target] = self.datasets.pop(source)
        Path(source).rename(target)

    def GetRasterProperties(self, path, property):
        assert property == 'ALLNODATA'
        return SimpleNamespace(getOutput=lambda _: str(int(self.datasets[str(path)]['allnodata'])))

    def ClearWorkspaceCache(self):
        pass

    def GetMessages(self, severity):
        return ''

    def ListTransformations(self, *args):
        return ['Example_Transform']

    def CheckExtension(self, name):
        return self.extension

    def CheckOutExtension(self, name):
        self.events.append(('checkout', name))
        return 'CheckedOut'

    def CheckInExtension(self, name):
        self.events.append(('checkin', name))


def package(master, filename='survey_20250728.zip', datasets=None):
    folder = master/'files'
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder/filename
    with ZipFile(archive, 'w') as stream:
        for name, metadata in (datasets or {'survey.gdb/Bathymetry': info()}).items():
            stream.writestr(name+'.dataset.json', json.dumps(metadata))
    return archive


@pytest.mark.parametrize('member', ['../outside', '/absolute', 'C:/escape', 'a/../../escape',
                                    r'..\escape', 'a/file:stream', '//host/share/file'])
def test_zip_rejects_escaping_paths(tmp_path, member):
    archive = tmp_path/'bad.zip'
    with ZipFile(archive, 'w') as stream:
        stream.writestr(member, 'unsafe')
    with pytest.raises(ValueError, match='Unsafe ZIP member'):
        bathy.extract_archive(archive, tmp_path, bathy.file_hash(archive))
    assert not (tmp_path.parent/'outside').exists()


def test_zip_rejects_symlink_and_case_collision(tmp_path):
    archive = tmp_path/'bad.zip'
    link = ZipInfo('link')
    link.create_system, link.external_attr = 3, (stat.S_IFLNK | 0o777) << 16
    with ZipFile(archive, 'w') as stream:
        stream.writestr(link, '../elsewhere')
    with pytest.raises(ValueError, match='Symlinks'):
        bathy.extract_archive(archive, tmp_path, bathy.file_hash(archive))
    with ZipFile(archive, 'w') as stream:
        stream.writestr('Data.gdb/table', 'a')
        stream.writestr('Data.gdb/TABLE', 'b')
    with pytest.raises(ValueError, match='case-colliding'):
        bathy.extract_archive(archive, tmp_path, bathy.file_hash(archive))


def test_extraction_resume_and_incomplete_input_protection(tmp_path):
    archive = package(tmp_path)
    digest = bathy.file_hash(archive)
    extracted = bathy.extract_archive(archive, tmp_path, digest)
    member = extracted/'survey.gdb/Bathymetry.dataset.json'
    modified = member.stat().st_mtime_ns
    assert bathy.extract_archive(archive, tmp_path, digest) == extracted
    assert member.stat().st_mtime_ns == modified
    member.write_text('changed')
    with pytest.raises(RuntimeError, match='incomplete or changed'):
        bathy.extract_archive(archive, tmp_path, digest)
    assert member.read_text() == 'changed'
    assert bathy.archives_in(tmp_path) == [archive]


def test_raster_selection_excludes_ancillary_and_requires_disambiguation():
    arc = FakeArcPy()
    arc.datasets = {name: info() for name in ['Bathymetry', 'hillshade', 'unknown1', 'unknown2']}
    arc.datasets['RGB'] = info(bands=3)
    selected, inventory = bathy.select_rasters(arc, list(arc.datasets), [])
    assert [item['path'] for item in selected] == ['Bathymetry']
    assert len(inventory) == 5
    with pytest.raises(ValueError, match='Multiple unclassified'):
        bathy.select_rasters(arc, ['unknown1', 'unknown2'], [])
    selected, _ = bathy.select_rasters(arc, ['unknown1', 'unknown2'], ['*2'])
    assert selected[0]['path'] == 'unknown2'


def test_pipeline_projects_orders_and_resumes(tmp_path):
    arc = FakeArcPy()
    package(tmp_path, 'a_20251231.zip', {'a.gdb/Bathymetry': info(sr=26916, pixel='S16')})
    package(tmp_path, 'z_20250101.zip')
    args = bathy.parse_args([str(tmp_path)])
    assert bathy.process(args, arc) == 0
    report = bathy.load_state(tmp_path)
    assert report['owned_gdb'] == tmp_path.name+'.gdb'
    assert report['mosaic']['status'] == 'completed'
    assert (tmp_path/(tmp_path.name+'.tif')).exists()
    event = next(event for event in arc.events if event[0] == 'mosaic')[1]
    assert event['mosaic_method'] == 'LAST'
    assert event['pixel_type'] == '32_BIT_FLOAT' and event['number_of_bands'] == 1
    assert 'z_20250101' in event['input_rasters'][0]
    assert 'a_20251231' in event['input_rasters'][1]
    assert any(event[0] == 'project' for event in arc.events)
    assert len(report['rasters']) == 2
    arc.events.clear()
    assert bathy.process(args, arc) == 0
    assert not any(event[0] in {'copy', 'project', 'resample', 'mosaic'} for event in arc.events)


def test_tin_fallback_is_opt_in_and_license_is_released(tmp_path):
    arc = FakeArcPy()
    package(tmp_path, datasets={'source_tin': info(kind='Tin')})
    with pytest.raises(RuntimeError, match='No bathymetry rasters'):
        bathy.process(bathy.parse_args([str(tmp_path)]), arc)
    assert not any(event[0] == 'tin' for event in arc.events)
    assert bathy.process(bathy.parse_args([str(tmp_path), '--tin-to-raster']), arc) == 0
    event = next(event for event in arc.events if event[0] == 'tin')
    assert event[2] == dict(data_type='FLOAT', method='LINEAR', sample_distance='CELLSIZE 5', z_factor=1)
    assert ('checkin', '3D') in arc.events


def test_inventory_does_not_claim_existing_geodatabase(tmp_path):
    arc = FakeArcPy()
    package(tmp_path)
    gdb = tmp_path/(tmp_path.name+'.gdb')
    gdb.mkdir()
    (gdb/'user-file').write_text('keep')
    assert bathy.process(bathy.parse_args([str(tmp_path), '--inventory-only']), arc) == 0
    assert not any(event[0] in {'gdb', 'copy', 'mosaic'} for event in arc.events)
    with pytest.raises(ValueError, match='preserving it'):
        bathy.process(bathy.parse_args([str(tmp_path)]), arc)
    assert (gdb/'user-file').read_text() == 'keep'


@pytest.mark.parametrize('bad_info, message', [
    (info(allnodata=True), r'archive\(s\) failed'),
    (info(gcs=4326), r'archive\(s\) failed'),
])
def test_invalid_source_blocks_mosaic(tmp_path, bad_info, message):
    arc = FakeArcPy()
    package(tmp_path, datasets={'survey.gdb/Bathymetry': bad_info})
    with pytest.raises(RuntimeError, match=message):
        bathy.process(bathy.parse_args([str(tmp_path)]), arc)
    assert not any(event[0] == 'mosaic' for event in arc.events)
    assert len(bathy.load_state(tmp_path)['failures']) == 1


def test_interrupted_copy_is_retried_without_reextracting(tmp_path):
    arc = FakeArcPy()
    package(tmp_path)
    args = bathy.parse_args([str(tmp_path)])
    arc.fail_copy = True
    with pytest.raises(RuntimeError, match=r'archive\(s\) failed'):
        bathy.process(args, arc)
    assert next(iter(bathy.load_state(tmp_path)['rasters'].values()))['status'] == 'creating'
    arc.fail_copy = False
    assert bathy.process(args, arc) == 0
    assert next(iter(bathy.load_state(tmp_path)['rasters'].values()))['status'] == 'completed'


def test_conflicting_vertical_references_block_mosaic(tmp_path):
    arc = FakeArcPy()
    package(tmp_path, 'a.zip', {'source.gdb/Bathymetry': info(vcs='NAVD88')})
    package(tmp_path, 'b.zip', {'source.gdb/Bathymetry': info(vcs='Local datum')})
    with pytest.raises(ValueError, match='Conflicting source vertical CRSs'):
        bathy.process(bathy.parse_args([str(tmp_path)]), arc)
    assert not any(event[0] == 'mosaic' for event in arc.events)


def test_grid_size_limit_prevents_unintended_large_mosaic(tmp_path):
    arc = FakeArcPy()
    package(tmp_path)
    with pytest.raises(RuntimeError, match='exceeds --max-cells'):
        bathy.process(bathy.parse_args([str(tmp_path), '--max-cells', '1']), arc)
    assert not any(event[0] == 'mosaic' for event in arc.events)


def test_partial_mosaic_is_explicit_and_keeps_failure_exit_code(tmp_path):
    arc = FakeArcPy()
    package(tmp_path, 'good_20250101.zip')
    package(tmp_path, 'bad_20251231.zip', {'source.gdb/Bathymetry': info(allnodata=True)})
    assert bathy.process(bathy.parse_args([str(tmp_path), '--allow-partial']), arc) == 1
    report = bathy.load_state(tmp_path)
    assert len(report['failures']) == 1
    assert report['mosaic']['status'] == 'completed'
    event = next(event for event in arc.events if event[0] == 'mosaic')[1]
    assert len(event['input_rasters']) == 1
    assert 'good_20250101' in event['input_rasters'][0]


def test_tin_horizontal_spacing_changes_from_metres_to_feet_without_z_scaling(tmp_path):
    arc = FakeArcPy()
    arc.datasets['tin'] = info(kind='Tin')
    describe = arc.Describe

    def feet_description(path):
        description = describe(path)
        description.spatialReference.metersPerUnit = 1200/3937
        return description

    arc.Describe = feet_description
    args = bathy.parse_args([str(tmp_path), '--tin-to-raster'])
    bathy.normalize(arc, Path('tin'), 'tin', tmp_path/'output', SpatialReference(),
                    args, tmp_path, None)
    event = next(event for event in arc.events if event[0] == 'tin')[2]
    assert float(event['sample_distance'].split()[1]) == pytest.approx(5*3937/1200)
    assert event['z_factor'] == 1


def test_rebuild_keeps_previous_tiff(tmp_path):
    arc = FakeArcPy()
    package(tmp_path)
    assert bathy.process(bathy.parse_args([str(tmp_path)]), arc) == 0
    assert bathy.process(bathy.parse_args([str(tmp_path), '--rebuild']), arc) == 0
    assert len(list(tmp_path.glob(tmp_path.name+'_previous_*.tif'))) == 1


def test_locked_report_uses_recovery_and_newest_snapshot(tmp_path, monkeypatch):
    state = dict(tool=bathy.TOOL, version=1, rasters={}, archives={})
    bathy.save_state(tmp_path, state)
    original = bathy.replace_file

    def locked_primary(source, target):
        if Path(target).name == bathy.STATE:
            raise PermissionError('Windows file lock')
        return original(source, target)

    monkeypatch.setattr(bathy, 'replace_file', locked_primary)
    state['test_progress'] = 'newest'
    bathy.save_state(tmp_path, state)
    assert bathy.load_state(tmp_path)['test_progress'] == 'newest'


def test_date_lookup_and_filename_fallback(tmp_path):
    from eHydro.download_ehydro import package_name
    url = 'https://example.test/package.zip'
    archive = tmp_path/package_name(url)
    report = dict(surveys=[dict(sourcedatalocation=url, surveydatestart='2025-07-28T12:00:00+00:00')])
    assert bathy.archive_date(archive, report) == ('2025-07-28', 'download manifest')
    assert bathy.archive_date(Path('hash_LM_01_20251231_CS.zip'), {})[0] == '2025-12-31'
    assert bathy.archive_date(Path('unknown.zip'), {})[0] == ''


@pytest.mark.parametrize('option', ['0', '-1', 'nan', 'inf'])
def test_invalid_cell_size_is_rejected(option):
    with pytest.raises(SystemExit):
        bathy.parse_args(['master', '--cell-size', option])
