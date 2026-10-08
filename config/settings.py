"""Application settings (JSON-persisted) and project paths."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

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
            for k, v in data.items():
                if k in known:
                    setattr(s, k, v)
                else:
                    logger.warning("Ignoring unknown setting '%s'", k)
        return s

    def save(self, path: Path = SETTINGS_FILE) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
