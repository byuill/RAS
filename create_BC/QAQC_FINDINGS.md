# Boundary-condition QA/QC findings

Review used Wednesday commit `1d062bcf685a8f6def3adfc16e3ede244b407a5a`,
all three Python scripts, all four CSV inputs, and the supplied calibration DSS.
The CSV contains 9,497 gap-free daily records, 2000-01-01 through 2025-12-31,
with finite nonnegative flow values and no ORCC diversion exceeding its Union
Point input. Included inputs/outputs were preserved.

## Confirmed calculation defects and corrections

| Finding | Effect | Correction in the shared engine |
| --- | --- | --- |
| First monthly split is converted as a ratio while later WY V2 values are fractions | First-day MMR/Ohio discrepancy of 8,490.732 cfs | Explicit file semantics, consistent conversion on every day |
| CY values can exceed one but later rows are treated as fractions | Can produce negative Ohio flow | Ratio interpretation with `r/(1+r)` and strict range validation |
| Birds Point returns use assignment and omit diversions near the run end | Overlapping returns overwrite water; tail disappears | Convolution with additive returns and a loss/storage/tail ledger |
| Minimum redistribution and annual random-flux loops omit the last day/year | Boundary behavior depends on position in file | All days and years processed; infeasible minimums reported |
| High-flow ORCC hydropower is fixed at 170,000 even if total ORCC is smaller | 52 supplied-calibration days have excess allocated structure flow, up to 132,000 cfs | Hydropower bounded by total diversion and capacity before allocating residual |
| Random/head-proxy allocations can exceed caps or become negative | Clipping individual structures later breaks total conservation | Conservative bounded allocation; unachievable head preference reported |
| E-flow feasibility requires mainstem flow simultaneously >1,250,000 and <150,000 | Mainstem plausibility condition can never be true | Feasibility checks use a real interval and available-water/ORCC limits; misses recorded |
| Independent spillway switch/ceiling values can create negative Morganza | Apparent mainstem inflow from an extraction boundary | Threshold mode uses min(excess, Bonnet Carré ceiling) |
| Negative raw pass extractions enter subsequent rating calculations before final clipping | Artificial water propagates downstream; printed BCs do not conserve | Constrain each extraction before evaluating the next rating |
| QA/QC covers ORCC and lower river only | Regional boundary deficit is hidden | Add regional, latitude, whole-system, and floodway volume ledgers |
| Independent Savitzky–Golay filters on exported series | Printed QA/QC may not describe the actual exported boundaries; sign/cap errors possible | Optional input-forcing smoothing, followed by one shared audited partition |
| HydroTool tests `'state' in locals()` after storing `state_col` | Imported hydrograph states can be ignored | Explicit validated input-state option |
| No strict date/finite-value/gap checking; DSS writer not read back | Missing or misaligned BCs can reach a model | Validate inputs and read back every exported DSS record |

The unchanged legacy algorithm was executed in a temporary directory to capture
its numerical output. DSS writes were stubbed and missing water-level generation
was disabled **in memory**; no original data/code was altered for that run. This
comparison validates the flow calculations, not the legacy DSS writer or stage
generation. Maximum legacy ORCC imbalance was **132,000 cfs on 52 days**. Maximum
legacy lower-river imbalance was **131,711.887 cfs**, with errors >1 cfs on
**7,469 days**. For the corrected engine, all ORCC, latitude, and lower-river daily
residuals are below **1e-6 cfs** on this calibration.

Validation: **164 repository tests passed**, including 29 new engine, GUI, input
download, and export checks. The full calibration exported 33 flow DSS series;
every value and timestamp was read back. Maximum DSS value rounding difference
was **0.058845 cfs**, distinct from the engine's numerical residual. Replaying
the saved raw inputs, split table, and parameters reproduced their canonical
hashes. The optional minor-tributary closure scenario has zero regional residual
on the supplied calibration. No HEC-RAS hydraulic/sediment run was performed.

## Defaults retained and exposed for engineering review

The supplied ORCC series exceeds the 620,000 cfs scenario ceiling on **9 days**
and is below the 8,000 cfs hydropower minimum on **28 days**. The new default
scenario applies those limits and reports all **37 adjustments**. This is an
operating scenario based on observations, not an exact observational replay.

Regional coefficients total 0.940694 of Union Point forcing. The maximum upstream
gap is **135,929.352 cfs**. This remains a warning under the default scenario;
downstream closure does not prove that the applied upstream model BCs close.
The optional minor-tributary closure rule is explicit and requires hydrologic
judgment. Original minor-tributary weights total 0.9995; their normalization is
recorded. Aggregate names are retained for model compatibility, not asserted to
be individual gauged tributary hydrographs.

ORCC state/head heuristics, spillway discharge triggers, constant diversion
magnitudes, rating coefficients, equal terminal-pass splits, and the SW Pass
curve discontinuity are scenario assumptions retained as editable parameters.
No independently verified Auxiliary rating was supplied; its default ceiling
equals the total ORCC ceiling. No claim is made that these limits reproduce an
official operating plan or actual head, gate openings, or stage-dependent capacity.

## Associated workflow scripts

`Generate_dataFile_Input.py` previously summed whatever ORCC structures were
available (`min_count=1`) and silently treated missing Overbank values as zero.
It also partially filled longer gaps and clipped negative derived Red River flow.
The corrected downloader requires all four structures, handles pagination and
unit metadata, fills only complete short interior non-Overbank gaps, reports
interpolation, and refuses incomplete or inconsistent final inputs. These paths
are tested with controlled CWMS responses; no live multi-decade download was
needed to use the bundled calibration. UTC daily aggregation remains its source
convention; verify CWMS observation timestamps and DailyComputed definitions for
your project before building new inputs.

`connect_DSS2RASFile.py` was reviewed but is unchanged. It overwrites selected
model XML files and has broad boundary matching. The new workbench does not invoke
it, alter model files, or certify its river/reach/station links. Review it separately
with representative `.q##`/`.s##` files before using automatic model modification.

The included `Calibration_2000to2025.dss` was inspected through a temporary copy
with the installed HEC-DSS reader. It contains the historical flow B-parts and
stage records. Reading the exact 2000-01-01–2000-01-03 TL_UP window returns
`[304000, 281000, 258000]`, matching the CSV; default yearly-block reads start at
Jan 2 because midnight Jan 1 belongs to the preceding block. New export validation
therefore requests the exact date window and checks every returned timestamp.
The source DSS is retained rather than rewritten.

## Project-specific checks still needed

Verify actual gauge definitions/time alignment, tributary apportionment, ORCC
structure ratings and operating procedures, lower pass rating calibration/ranges,
and stage datum. Review empirical thresholds against stages and travel times in
the selected model. Validate river/reach/station links, downstream boundary types,
durations, and sediment inputs in HEC-RAS. App regression tests and DSS read-back
checks do not establish the hydraulic or sediment accuracy of a model run.
