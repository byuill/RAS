"""Application settings (JSON-persisted) and project paths."""
from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from core.io import atomic_text

logger = logging.getLogger(__name__)

APP_NAME = "RAS Sediment Calibration Workbench"  # change here to rename the application
APP_VERSION = "1.0.0"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
CACHE_DIR = PROJECT_ROOT / "cache"
OBS_CACHE_DIR = CACHE_DIR / "observations"
LOG_DIR = PROJECT_ROOT / "logs"
SETTINGS_FILE = CONFIG_DIR / "app_config.json"
STATIONS_FILE = CONFIG_DIR / "stations.yaml"
USER_STATIONS_FILE = CONFIG_DIR / "stations_user.yaml"
MAPPINGS_FILE = CONFIG_DIR / "station_mappings.json"
DEFAULT_MODEL_DIR = Path(r"E:\LMR Comp Phase 2\Calibration_2004_2025\sediment_calibration\model_template_Ver2")


@dataclass
class AppSettings:
    last_hdf_path: str = ""
    default_model_dir: str = str(DEFAULT_MODEL_DIR)
    observation_cache_dir: str = str(OBS_CACHE_DIR)
    sand_min_diameter_mm: float = 0.063
    rouse_kappa: float = 0.4
    rouse_bed_min: float = 2.5
    rouse_susp_max: float = 1.2
    rouse_source: str = "hecras"            # hecras | computed
    display_discharge_unit: str = "cfs"
    display_length_unit: str = "ft"
    display_velocity_unit: str = "ft/s"
    display_shear_unit: str = "lb/ft2"
    display_concentration_unit: str = "mg/L"
    display_flux_unit: str = "tons/day"
    display_diameter_unit: str = "mm"
    negative_value_policy: str = "keep"     # keep (as HEC-RAS wrote) | nan | zero
    drop_initial_step_sediment: bool = True  # first HEC-RAS output is the zero-sediment initial condition
    hdf_cache_mb: float = 256.0
    analysis_cache_mb: float = 128.0
    hysteresis_window_days: int = 7
    hysteresis_rise_threshold_cfs: float = 5000.0
    hysteresis_min_q_cfs: float = 500000.0
    first_flood_rise_threshold_cfs: float = 300000.0
    first_flood_abs_threshold_cfs: float = 600000.0
    pairing_max_gap_hours: float = 36.0
    log_level: str = "INFO"

    def display_unit(self, quantity: str) -> str:
        return {
            "discharge": self.display_discharge_unit, "length": self.display_length_unit,
            "velocity": self.display_velocity_unit, "shear_stress": self.display_shear_unit,
            "concentration": self.display_concentration_unit, "mass_flux": self.display_flux_unit,
            "diameter": self.display_diameter_unit,
        }[quantity]

    @classmethod
    def load(cls, path: Path = SETTINGS_FILE) -> "AppSettings":
        s = cls()
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Could not read settings %s (%s); using defaults", path, exc)
                return s
            known = {f.name for f in fields(cls)}
            if not isinstance(data,dict):
                logger.warning('Settings must be a JSON object; using defaults')
                return s
            for k, v in data.items():
                if k in known:
                    default = getattr(s,k)
                    valid_type = (isinstance(v,(int,float)) and not isinstance(v,bool)) if isinstance(default,float) else isinstance(v,type(default))
                    if valid_type:
                        setattr(s,k,v)
                    else:
                        logger.warning("Ignoring setting '%s' with incorrect type", k)
                else:
                    logger.warning("Ignoring unknown setting '%s'", k)
        defaults=cls()
        numeric = {'hdf_cache_mb':0,'analysis_cache_mb':0,'sand_min_diameter_mm':0,
                   'rouse_kappa':0,'rouse_bed_min':0,'rouse_susp_max':0,'pairing_max_gap_hours':0}
        for key,lower in numeric.items():
            number=getattr(s,key)
            if not math.isfinite(number) or number < lower or (key not in ('hdf_cache_mb','analysis_cache_mb') and number==0):
                setattr(s,key,getattr(defaults,key))
                logger.warning("Ignoring invalid setting '%s'",key)
        if not s.sand_min_diameter_mm < 2:
            s.sand_min_diameter_mm=defaults.sand_min_diameter_mm
        if s.rouse_susp_max>s.rouse_bed_min:
            s.rouse_susp_max,s.rouse_bed_min=defaults.rouse_susp_max,defaults.rouse_bed_min
        if s.hysteresis_window_days < 1:
            s.hysteresis_window_days = defaults.hysteresis_window_days
        for key in ('hysteresis_rise_threshold_cfs','hysteresis_min_q_cfs',
                    'first_flood_rise_threshold_cfs','first_flood_abs_threshold_cfs'):
            if not math.isfinite(getattr(s,key)) or getattr(s,key)<0:setattr(s,key,getattr(defaults,key))
        for key,choices in [('negative_value_policy',('keep','nan','zero')),('rouse_source',('hecras','computed'))]:
            if getattr(s,key) not in choices:setattr(s,key,getattr(defaults,key))
        from sediment.units import quantity_of
        from core.exceptions import UnitError
        for quantity,key in [('discharge','display_discharge_unit'),('length','display_length_unit'),
                             ('velocity','display_velocity_unit'),('shear_stress','display_shear_unit'),
                             ('concentration','display_concentration_unit'),('mass_flux','display_flux_unit'),
                             ('diameter','display_diameter_unit')]:
            try:
                if quantity_of(getattr(s,key))!=quantity:raise UnitError('Incompatible display unit')
            except UnitError:
                setattr(s,key,getattr(defaults,key))
                logger.warning("Ignoring invalid display unit '%s'",key)
        return s

    def save(self, path: Path = SETTINGS_FILE) -> None:
        atomic_text(path,json.dumps(asdict(self),indent=2)+'\n')
