# Technical Documentation

## HDF Paths Read
- XS attributes: `Results/Sediment/Geometry Info/Cross Section Attributes`
- Time series: `Results/Sediment/Output Blocks/Sediment/Sediment Time Series/Cross Sections/`
- Variable sets: Flow, Velocity, Shear Stress, Sediment Concentration, Sediment Flux (per grain class and total).

## Derived Calculations
- **Sediment Load**: Cumulative loads are evaluated backwards using HEC-RAS calculation principles (mass out cumulative backward interval). 
- **Rouse Partitioning**: Suspended load and bedload fractions are calculated from HEC-RAS 'Rouse #' output if available, or estimated using Ferguson-Church 2004 velocity otherwise.
- **Conversion Factor**: 1 mg/L * 1 cfs = 0.0026968879 short tons/day. 

## Integrity Checks
Negative concentrations reported by HEC-RAS in cohesive classes are flagged. Sum of class fluxes is reconciled against reported total sediment flux.
