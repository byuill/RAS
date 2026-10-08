"""HEC-RAS result-variable names (version-dependent strings, verified on HEC-RAS 7.0.1)."""

FLOW = "Flow"
WSE = "Water Surface"
VELOCITY = "Velocity"
SHEAR_STRESS = "Shear Stress"
SHEAR_VELOCITY = "Shear Velocity"
TEMPERATURE = "Temperature"
HYDRAULIC_RADIUS = "Hydraulic Radius"
ENERGY_SLOPE = "Slope"
INVERT = "Invert Elevation"

CONCENTRATION = "Sediment Concentration"     # total + per class (mg/L)
SEDIMENT_DISCHARGE = "Sediment Discharge"    # total only (tons/day)
VOL_OUT = "Vol Out"                          # per class, volume of sediment out per output step
ROUSE = "Rouse #"                            # per class
FALL_VELOCITY = "Fall Velocity"              # per class
MASS_OUT_CUM = "Mass Out Cum"                # total, cumulative tons (units attribute is mislabeled ft^3)

WATER_UNIT_WEIGHT_LB_FT3 = 62.4
