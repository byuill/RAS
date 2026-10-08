"""Analysis state for the HEC-RAS Sediment Calibration Workbench."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

@dataclass
class RegressionOptions:
    fit_power_law: bool = True
    show_ci: bool = True
    # more options can be added here as needed

@dataclass
class AnalysisState:
    hdf_path: str = ""
    plan_id: str = ""
    xs_index: int = 0
    sediment_group: str = "total"
    hydraulic_var: str = "Discharge"
    sediment_var: str = "Flux"
    start_date: str = ""
    end_date: str = ""
    
    # filters
    month_filters: list[int] = field(default_factory=lambda: list(range(1, 13)))
    season_filters: list[str] = field(default_factory=lambda: ["DJF", "MAM", "JJA", "SON"])
    limb_filters: list[str] = field(default_factory=lambda: ["Rising", "Falling", "Other"])
    
    # options
    regression: RegressionOptions = field(default_factory=RegressionOptions)
    rouse_kappa: float = 0.4
    rouse_bed_min: float = 2.5
    rouse_susp_max: float = 1.2
    
    # observations
    obs_station: str = ""
    
    @classmethod
    def load(cls, path: str | Path) -> "AnalysisState":
        path = Path(path)
        if not path.exists():
            return cls()
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
            
        reg_data = data.pop("regression", {})
        state = cls(**data)
        state.regression = RegressionOptions(**reg_data)
        return state
        
    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)
