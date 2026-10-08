import json
import pytest
from config.settings import AppSettings
from core.io import atomic_text


def test_invalid_setting_types_ranges_and_units_fall_back(tmp_path):
    path=tmp_path/'settings.json'
    path.write_text(json.dumps({'hdf_cache_mb':-1,'rouse_kappa':'bad','rouse_source':'unknown',
        'negative_value_policy':[],'sand_min_diameter_mm':8,'display_discharge_unit':'ft',
        'drop_initial_step_sediment':'false','last_hdf_path':'run.p01.hdf'}))
    settings=AppSettings.load(path);defaults=AppSettings()
    assert settings.hdf_cache_mb==defaults.hdf_cache_mb
    assert settings.rouse_kappa==defaults.rouse_kappa and settings.rouse_source=='hecras'
    assert settings.display_discharge_unit=='cfs' and settings.drop_initial_step_sediment is True
    assert settings.sand_min_diameter_mm==.063 and settings.last_hdf_path=='run.p01.hdf'
    path.write_text('[]')
    assert AppSettings.load(path)==defaults


def test_failed_atomic_settings_write_preserves_original(tmp_path,monkeypatch):
    import core.io
    path=tmp_path/'settings.json';path.write_text('{"last_hdf_path":"previous.hdf"}')
    def fail(*args):raise OSError('simulated replacement failure')
    monkeypatch.setattr(core.io.os,'replace',fail)
    with pytest.raises(OSError):AppSettings(last_hdf_path='new.hdf').save(path)
    assert json.loads(path.read_text())['last_hdf_path']=='previous.hdf'
    assert list(tmp_path.iterdir())==[path]
