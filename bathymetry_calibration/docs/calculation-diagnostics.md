# Bed-volume calculation audit and assumption exploration

After comparing a survey pair, open **Calculation audit / assumptions**. The
reference is the completed comparison. Experiments use its original, reviewed
model and survey profiles; they do not edit source files, QA/QC decisions, or
the main comparison. Use the scenario selector to revisit retained results.
Click **Calculate and keep scenario** after changing knobs. The uncertainty
knobs apply to every retained scenario in the summary, under one common error
model. **Reset to reference** discards experiment history and restores controls.

The views show calculation stages, variability/cancellation, sensitivity plots,
the lateral integration ledger, reach operands, section accounting, and a
plain-language calculation guide. Selecting an XS shows the actual area,
control length, local volume, and the two cumulative values with units.
Table previews show up to 2,000 rows; exports contain every row. The calculation
stages plot overlays the reference with faint dotted curves when a scenario is
selected. Blue is model and orange is observed, consistently across segments.

## What the current curves mean

All geometry is in metres; deposition is positive and erosion negative.
Sources must have independently verified orientation, units, vertical datum,
model columns, and survey dates. Those checks cannot be inferred from agreement.

At XS `i`, interpolate the four profiles on a common domain and retain every
source knot. A lateral interval `[u_j,u_(j+1)]` is accepted only when **all**
sources have finite endpoints and supported interior. Explicit NaN knots and
source gaps larger than `max_gap_m` are barriers. Extra support epochs impose
the same rule on time-series comparisons. No extrapolation or filling occurs.

For accepted intervals of width `w_j`:

```
dz_j = target_z_j - baseline_z_j
dA_i = sum(w_j * (dz_j + dz_(j+1)) / 2)          [m²]
```

This is exact quadrature of the **piecewise-linear sampled profiles**. It is
not exact integration of an unsampled, continuous riverbed. The ledger records
each endpoint elevation, change, width, acceptance, failing source, and signed
area contribution. Unsupported intervals contribute zero to the integral;
that zero means excluded support, not measured zero change.

The default average-end-area calculation uses each manifest's verified channel
length, even when it differs from the plot's chainage spacing:

```
reach_V_i = L_i * (dA_i + dA_(i+1)) / 2          [m³]
control_length_i = (L_(i-1) + L_i) / 2            [m]
local_V_i = dA_i * control_length_i               [m³]
```

Endpoints receive only the available neighboring half-length. Missing XS
disconnect the reach; no integral, prefix, or derivative bridges them.

**Node cumulative** (the existing primary plot) is the running sum of `local_V`.
It includes a half-reach contribution at the first XS. **Completed-reach prefix**
starts at zero and accumulates whole reach integrals at downstream XS. Both
reset at disconnected segments and end at the same segment total, but their
intermediate values are different accounting conventions. A node prefix is
not the integral from the upstream boundary to that physical node.

For areas `[-10,-20,-30] m²` and lengths `[100,200] m`, reach volumes are
`[-1500,-5000] m³`, control lengths `[50,150,100] m`, and local volumes
`[-500,-3000,-3000] m³`. Node cumulative is `[-500,-3500,-6500]`; completed-reach
prefix is `[0,-1500,-6500]`. The audit exposes both instead of silently
substituting one for the other. Native RAS volume remains a separate audit.

## Nonuniform change and cancellation

Split each linearly interpolated interval **at its zero crossing** before
integrating positive deposition and negative erosion magnitudes. Clipping
endpoint changes and taking their trapezoid overestimates a crossing triangle.

```
deposition_area = integral(max(dz, 0), du)
erosion_area = integral(max(-dz, 0), du)
net = deposition - erosion
gross_turnover = deposition + erosion
cancellation = 1 - abs(net)/gross_turnover
```

Cancellation is undefined when gross turnover is zero, zero for one sign only,
and one for equal opposing changes. The same longitudinal estimator combines
section components into reach and overall indicators. These are **quadrature
indicators based on sampled sections**; they do not reconstruct erosion and
deposition within the unsampled space between sections. Interpolating full
2-D morphology between XS would impose additional, unverified assumptions.

For `dz=[-3,+3,-3] m` at stations `[0,5,10] m`, each XS has zero net change
but `7.5 m²` deposition and `7.5 m²` erosion. On a 200 m reach sampled by
three equally spaced XS, net volume is zero while gross turnover is `3000 m³`.
Opposing upstream/downstream changes can also cancel within a reach even when
each XS itself has no lateral cancellation. Reach-ledger indicators expose this.

The integral of squared change is exact for a linear interval:

```
second_moment = width * (dz_left² + dz_left*dz_right + dz_right²) / 3
RMS = sqrt(integral(dz²)/accepted_width)
lateral_std = sqrt(RMS² - mean_change²)
```

Overall spatial standard deviation combines lateral and between-section
variation using width × control length; the reach ledger provides analogous
reach indicators. Erosion/deposition width fractions split intervals at the
classification threshold, with a remainder within threshold. These fractions
and zones change with threshold; **signed and gross volume retain all change**.
Negative zero-roundoff variances are clamped to zero. Undefined statistics stay
undefined, not perfect agreement or zero variability.

Gross turnover is a two-date geometric-change indicator. It cannot measure
transport, sediment-solid volume, porosity, or intervening erosion/refilling.
Large gross turnover with small net change is a useful dynamism indicator,
but two surveys cannot establish the event history.

## Tuning knobs and their limits

| Control | Interpretation |
| --- | --- |
| Longitudinal estimator | Default average end area; upstream or downstream area held constant through each reach test reconstruction sensitivity. They are diagnostic alternatives, not automatically better estimators. Their node weights use the selected estimator rather than half-lengths. |
| Domain | Intersection compares available overlap; transect requires the selected manifest footprint subject to the coverage setting. |
| Maximum gap / minimum coverage / minimum accepted width | Change which lateral intervals and XS can be integrated. NaN barriers always remain. Minimum width applies **after** unsupported intervals are removed. |
| Trim fraction per bank | Symmetrically reduces the original manifest width. It changes the sampled bed footprint and tests bank sensitivity; it does not identify the active channel automatically. |
| Integration grid spacing | Adds interpolation points while preserving every source knot. Results should be invariant for the piecewise-linear estimator; this is a numerical QA check. It does not change raster resolution or source sampling. |
| Classification threshold | Reclassifies changes, retaining all volume. The main workflow can raise this to its conditional survey error limit; explorer changes are explicit classification experiments. |
| Hypothetical target shift | Adds a specified elevation to the target survey for sensitivity only. Actual datum corrections still require benchmark evidence and the existing Survey QA/QC workflow. |
| Survey sigma / temporal and spatial correlations | Explore the conditional uncertainty of observed volume and model-minus-observed bias. |

The summary reports deltas from the reference and `support_changed`. A changed
footprint or accepted XS set means a volume delta mixes changed sampling with
changed calculation. Compare the support and exclusion ledgers first. No
scenario silently scales partial coverage up to a full bed or infers that its
method is correct. Failed scenarios remain unavailable with their reason.

Raster interpolation (nearest/bilinear), extraction sample spacing, point-to-XS
mapping, acquisition dates, and QA/QC exclusions are upstream of this explorer.
Change their source/configuration settings and rerun the main comparison if
needed; the explorer intentionally reuses the reviewed profiles, not extraction.
This distinction avoids mistaking denser integration points for new measurements.

## Conditional uncertainty and bias

`vertical_uncertainty_m` on each survey is an evidence-based one-sigma elevation
error. Configuration `volume_uncertainty` accepts `temporal_correlation`
(default 0) and `spatial_correlation` (default 1). The GUI permits both sigmas
and correlations as experiments. Before/after elevation difference uncertainty is:

```
sigma_change² = sigma_before² + sigma_after²
               - 2*rho_temporal*sigma_before*sigma_after
a_i = effective_width_i * control_length_i
sigma_volume² = sigma_change² * ((1-rho_spatial)*sum(a_i²)
                                + rho_spatial*(sum(a_i))²)
conditional_bias_interval = bias ± 1.96*sigma_volume
```

This Gaussian model treats elevation error as coherent within each XS. A spatial
correlation of zero makes section errors independent; one makes them coherent
across the entire selected bed, including disconnected segments. Shared epoch
errors can cancel if before/after sigma and their temporal correlation support
that assumption. The main classification limit is `1.96*sigma_change`.

Model volume is treated as exact in these intervals. They exclude unmodeled
systematic datum bias, unresolved between-XS morphology, lateral registration,
date mismatch, and model uncertainty. Whiskers and `bias_exceeds_survey_error_95`
therefore screen bias under stated survey-error assumptions; they are **not a
statistical validation of the model**. Correlated cumulative residuals are not
independent observations. Missing sigma produces no interval or significance
claim; a zero conditional variance does not establish significance either.
Grid refinement never reduces this error estimate by increasing sample count.

## Reproduce and export experiments

Normal pair exports now include `lateral_audit.csv`, original reviewed
`source_profiles.csv`, `transects.csv`, `calculation_guide.txt`, calculation-stage
and variability figures. Section and reach tables contain gross, net, moment,
and fraction indicators. Reports preserve the calculation options and conditional
error assumptions. Series exports retain the extra fixed-support epochs too.

The explorer exports the reference, every available scenario, failed reasons,
`sensitivity_summary.csv`, `scenarios.json`, and `sensitivity.png`. Its **Save
scenario instructions** action creates a JSON usable by the headless entry point:

```bash
python -m bathymetry_calibration --config config.json --hdf plan.p01.hdf \
  --headless --before-survey baseline --after-survey target \
  --sensitivity bathymetry_calibration/examples/sensitivity.example.json \
  --output output/assumptions
```

Scenarios contain a unique `name` and `overrides`. Valid controls are the
integration controls above plus `observed_target_shift_m` and
`change_threshold_m`. Optional top-level `uncertainty` supplies error-model knobs.
The CLI defaults these to the reference's survey/configuration assumptions;
the example deliberately leaves them unspecified. Exports record hypothetical
shifts explicitly, and do not reuse the reference's native or datum audits as
if those audits had been rerun on a scenario. Reference QA/QC remains available.
