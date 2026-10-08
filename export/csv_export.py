"""Export model data frames and paired calibration tables to CSV."""
from __future__ import annotations

import json
from pathlib import Path
import pandas as pd

from analysis.model_data import ModelFrame
from plotting.styles import DisplayUnits

def export_model_frame(mf: ModelFrame, path: str | Path, du: DisplayUnits) -> None:
    """Export ModelFrame to CSV, converting to display units, with a sidecar .meta.json."""
    path = Path(path)
    df = mf.df.copy()
    
    out = pd.DataFrame(index=df.index)
    
    # Metadata columns
    out["River"] = mf.meta.get("river", "")
    out["Reach"] = mf.meta.get("reach", "")
    out["CrossSection"] = mf.meta.get("cross_section", "")
    out["SedimentGroup"] = mf.meta.get("sediment_group_label", "")
    
    # Values converted to display units
    out["Discharge"] = du.convert(df["Q"], "discharge")
    out["Stage"] = du.convert(df["Stage"], "length")
    out["Velocity"] = du.convert(df["Velocity"], "velocity")
    out["BedStress"] = du.convert(df["BedStress"], "shear_stress")
    out["SedimentFlux"] = du.convert(df["Flux"], "mass_flux")
    out["SedimentConcentration"] = du.convert(df["Conc"], "concentration")
    
    out['dt_days'] = df['dt_days']
    out[f"ShearVelocity_{du.label('velocity')}"] = du.convert(df['ShearVelocity'],'velocity')
    out['Temperature_degC'] = df['Temperature']
    out["Source"] = mf.meta.get("source_hdf", "")
    
    # Append unit names to columns
    out = out.rename(columns={
        "Discharge": f"Discharge_{du.label('discharge')}",
        "Stage": f"Stage_{du.label('length')}",
        "Velocity": f"Velocity_{du.label('velocity')}",
        "BedStress": f"BedStress_{du.label('shear_stress')}",
        "SedimentFlux": f"SedimentFlux_{du.label('mass_flux')}",
        "SedimentConcentration": f"SedimentConcentration_{du.label('concentration')}"
    })
    
    out.to_csv(path, index=True)
    
    # Sidecar JSON
    meta_path = path.with_suffix(".meta.json")
    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(mf.meta, f, indent=2)

def export_paired_calibration(df_paired: pd.DataFrame, path: str | Path, du: DisplayUnits, 
                              x_quantity: str, y_quantity: str) -> None:
    """Export paired calibration data."""
    path = Path(path)
    out = df_paired.copy()
    
    if "model_x" in out:
        out["model_x"] = du.convert(out["model_x"], x_quantity)
    if "obs_x" in out:
        out["obs_x"] = du.convert(out["obs_x"], x_quantity)
    if "model_y" in out:
        out["model_y"] = du.convert(out["model_y"], y_quantity)
    if "obs_y" in out:
        out["obs_y"] = du.convert(out["obs_y"], y_quantity)
        
    out.to_csv(path, index=True)
