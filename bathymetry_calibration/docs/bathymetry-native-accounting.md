# HEC-RAS 1-D Sediment Native Volume Accounting

## Exact Native Variable Identities
Based on inspection of the local HEC-RAS plan HDF file (`R1_Dyn_SLR1.p01.hdf`):
- **Local Time-Cumulative Volume:**
  - Name: `Vol Bed Change Cum`
  - HDF Path: `Results/Sediment/Output Blocks/Sediment/Sediment Time Series/Cross Sections/Vol Bed Change Cum`
  - Units: `ft^3` (US Customary)
  - Sign Convention: Positive (+) for deposition, Negative (-) for erosion.

- **Longitudinally and Temporally Cumulative Volume:**
  - Name: `Long. Cum Vol Change`
  - HDF Path: `Results/Sediment/Output Blocks/Sediment/Sediment Time Series/Cross Sections/Long. Cum Vol Change`
  - Units: `ft^3`
  - Sign Convention: Positive (+) for net deposition, Negative (-) for net erosion.

## Spatial and Temporal Semantics
- **Time accumulation:** Both variables are time-cumulative. For a specific interval `[t0, t1]`, the native interval volume is found by differencing the values at `t1` and `t0` (`V(t1) - V(t0)`).
- **Spatial accumulation:** 
  - `Vol Bed Change Cum` is strictly a *local* volume at a specific cross section (control volume).
  - `Long. Cum Vol Change` is the spatial sum (upstream to downstream) of the local volumes (`Vol Bed Change Cum`).
- **Reach/Branch Resetting:** Numerical verification of the HDF shows that `Long. Cum Vol Change` *resets* at river/reach boundaries. For instance, the accumulation for the Mississippi MMR reach starts at 0 and goes down to the end of the reach, and then a new accumulation starts for the Ohio River reach, and another for the Mississippi LMR reach. Thus, to extract a continuous curve across the model, one must account for these branch-level resets, or re-calculate the cumulative sum from the local `Vol Bed Change Cum` variable directly.

## Volume Basis (Bulk vs. Solid)
- The volume change reported in `Vol Bed Change Cum` is the **bulk geometric bed volume**, which *includes* the porosity of the sediment bed. It represents the physical change in bed geometry, not just the volume of solid sediment particles. This is appropriate for direct comparison to bathymetric survey differences, which also measure bulk volume changes.
- Grain classes should not be summed directly from mass without accounting for porosity/density. Since we are using the total bulk volume change, grain class segregation is not necessary for the overall geometric volume calibration.

## Control Volume and Reconstruction
- **Control Volume Length:** The HEC-RAS 1D sediment model uses a nodal control volume approach. The control volume for interior cross-section $i$ extends halfway to the upstream section $i-1$ and halfway to the downstream section $i+1$. Therefore, the control length $\ell_i = \frac{L_{i-1} + L_i}{2}$, where $L_i$ is the channel length between section $i$ and $i+1$. 
- **Endpoint Rules:** For the first and last cross-sections in a reach, the control volume extends only halfway to the adjacent cross-section. Thus, $\ell_0 = \frac{L_0}{2}$ and $\ell_n = \frac{L_{n-1}}{2}$.
- **Reconstruction:** The total volume is mathematically equivalent to average-end-area quadrature over the reach lengths. The native numerical accounting volume `Vol Bed Change Cum` matches the geometrically reconstructed volume $dV_i = dA_i \times \ell_i$.

## Example Numerical Agreement
From HDF inspection (Time step = -1, first 5 cross-sections in Mississippi MMR):
1. XS 0 (5235610): Local `Vol Bed Change Cum` = -6,275,758.5. `Long. Cum Vol Change` = -6,275,758.5
2. XS 1 (5227859): Local = -4,159,091.8. `Long. Cum Vol Change` = -10,434,850.3
  - Verification: `-6275758.5 + -4159091.8 = -10434850.3` (Exact agreement)
3. XS 2 (Ohio 11409): Local = -99,013,208. `Long. Cum Vol Change` = -99,013,208. (Reset to local value at new reach).
