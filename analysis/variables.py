"""Registry of plottable model variables and their physical quantities."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VarDef:
    key: str                  # column name in the model frame
    name: str
    quantity: str             # key in sediment.units.CANONICAL
    provenance_key: str       # key in model meta['provenance']
    is_sediment: bool = False


MODEL_VARS: dict[str, VarDef] = {v.key: v for v in [
    VarDef("Q", "Discharge", "discharge", "discharge"),
    VarDef("Stage", "Water-surface elevation", "length", "stage"),
    VarDef("Velocity", "Mean velocity", "velocity", "velocity"),
    VarDef("BedStress", "Bed shear stress", "shear_stress", "shear_stress"),
    VarDef("Flux", "Sediment flux", "mass_flux", "flux", True),
    VarDef("Conc", "Sediment concentration", "concentration", "concentration", True),
]}

HYDRAULIC_KEYS = ["Q", "Stage", "Velocity", "BedStress"]
SEDIMENT_KEYS = ["Flux", "Conc"]
# Rating-curve x variables
X_KEYS = ["Q", "Velocity", "BedStress", "Stage"]

OBS_FOR_MODEL = {"Q": "discharge_m3s", "Stage": "stage_elev_m", "Flux": "ssl_kg_s", "Conc": "ssc_mg_l"}
# For sand/fines groups observations have dedicated columns
OBS_FOR_GROUP = {("Conc", "sand"): "sand_mg_l", ("Conc", "fines"): "fines_mg_l"}


def obs_column(var_key: str, group_key: str) -> str | None:
    """Observation column comparable with model variable ``var_key`` of sediment group ``group_key``."""
    if var_key in ("Flux", "Conc"):
        if group_key == "total":
            return OBS_FOR_MODEL[var_key]
        if group_key in ("sand", "fines"):
            return "sand_mg_l" if group_key == "sand" else "fines_mg_l"   # flux derived by the caller (x Q)
        return None   # individual classes / Rouse groups have no observed counterpart
    return OBS_FOR_MODEL.get(var_key)
