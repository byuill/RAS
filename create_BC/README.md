# Lower Mississippi boundary-condition workbench

Create, inspect, and export daily discharge boundaries for a 1-D quasi-unsteady
sediment model. The desktop and command-line workflows share one calculation
engine. The supplied 2000–2025 calibration and historical operating coefficients
are the defaults. This is an empirical scenario generator, not a hydraulic model
or a replacement for verified USACE operating rules.

From the repository root, using the Python 3.12 environment:

```bash
python -m pip install -r requirements.txt
python -m pip install -r create_BC/requirements-dss.txt  # optional DSS export
python -m create_BC
```

Running `python create_BC/Generate_Discharge_BC_Ver3.py` also opens the workbench.
The previous script is preserved in `legacy/Generate_Discharge_BC_Ver3.py` for
comparison; it retains the historical defects and should not generate new BCs.
Importing the new launcher does not execute calculations or create files.

The `create_BC` folder is self-contained once its Python dependencies are
installed. You can copy the complete folder to a separate project directory and
run `python Generate_Discharge_BC_Ver3.py` from inside it. Keep all the Python
modules, including `qt_support.py`, and bundled CSV files together; copying only
the launcher is insufficient. No separate top-level `gui` folder is required.

## Desktop workflow

1. Select the continuous daily flow CSV and monthly MMR/Ohio split CSV. All
   discharge inputs are cfs. Dates must be unique, ordered, and gap-free.
2. Review parameters by group: workflow, regional inflows, floodway/spillways,
   ORCC operations, hydrograph state, lower diversions, pass ratings, terminal
   passes, and E-flow feasibility limits. The floodway return weights are also
   editable. Tooltips and inline notes explain units, formulas, and limitations.
3. Click **Calculate & check budget** after editing. Export is disabled while
   calculations are stale. Save/load scenario JSON for repeatable runs.
4. Select a date or move the slider. **River flow budget** shows all represented
   inflows, ORCC structures, diversions, distributaries, and three terminal passes.
   Arrow widths scale with the square root of flow. The forcing/estimated-flow
   gap is displayed at Union Point. **Hydrographs & residuals**, **Daily ledger**,
   and **QA/QC & assumptions** provide the numerical audit.
5. Export to a new run directory. DSS is optional and its values, timestamps,
   units, and record counts are checked by reading every record back. Existing
   calibration data, DSS files, and HEC-RAS model files are not overwritten.

The application calculates and exports in a background worker. On a headless
machine, use the CLI below; `QT_QPA_PLATFORM=offscreen` is for GUI testing only.

## Inputs and interpretation

The included `new_data_RF.csv` contains `date,discharge,Red_River,ORCC`:

- `discharge` is pre-diversion Union Point flow; it is not Tarbert Landing flow.
- `Red_River` is the separate Red River contribution at latitude.
- `ORCC` is a positive diversion magnitude; `ORCC_sim` takes precedence if supplied.
- Optional `state`: 0 normal, 1 rising, 1.5 extended crest, 2 falling, 3 low water.
  Enable **Use supplied hydrograph state** to consume it.
- Optional `Eflows` is a Simmesport target, including Red River. It is used only
  when E-flow mode is enabled; infeasible targets fall back and are reported.

Tarbert-reference input is also supported. Its upstream forcing is inferred as
the input gauge flow plus the requested nonnegative ORCC diversion **before**
constraints. Imposing a minimum, ceiling, or override may change the modeled
Tarbert flow; adjustments are recorded, rather than asserted to reproduce observations.
If Red River is omitted in this mode, the historical 0.132 coefficient is used.

`ohio_split_wyV2.csv` contains bounded MMR/(MMR+Ohio) fractions. The older calendar
file has values above one and is treated as MMR/Ohio ratios, converted using
`r/(1+r)`. This interpretation should be checked against the original data
provenance. The desktop switches the bundled file and interpretation together
when the water-year checkbox changes. For CLI scenarios, set `split_semantics`
explicitly when using the calendar file. Water years control seasonal sampling,
not the timestamps of observed data. Random sampling uses the actual table length
and a saved seed, not an assumed 30 rows.

The default Union Point regional coefficients sum to **0.940694**, leaving a
**5.9306%** forcing/estimated-boundary discrepancy before floodway routing. The
default retains these coefficients and reports the discrepancy. Selecting
**Close budget using minor tributaries** computes:

```
minor tributaries = Union Point − MMR − Ohio + Birds Point diversion − New Madrid return
```

This is an explicit scenario assumption, not evidence that the missing flow
actually belongs to those tributaries. Negative inferred tributary flows fail
the calculation. The Hatchie, Arkansas/White, and Yazoo values are aggregate
regional boundaries; their original weights are normalized from 0.9995 to one.

## Budget logic

At each day:

```
Latitude flow = Union Point + Red River
Tarbert Landing = Union Point − total ORCC diversion
Simmesport (before Morganza) = Red River + total ORCC diversion
Calculated ORCC = (1 − Mississippi latitude fraction) × latitude flow − Red River
```

The 0.7 default fraction therefore targets 70% of combined Mississippi/Red flow
remaining in the Mississippi. It is not simply a 30% diversion of Union Point.
The operating rules then constrain available water, the ORCC total, and structure
allocations. The Auxiliary default ceiling is the total ORCC ceiling because the
legacy script lacks a separate verified Auxiliary rating; change it with project
evidence. The optional head constraint is a discharge-based proxy, not a computed
water-surface/head differential.

Birds Point extractions are convolved with return weights
`[0.5,0.25,0.1,0.05,0.05,0.025,0.015,0.01]` after the base lag. Overlapping returns
are added. Returns after the end of the run, modeled losses, and stored volume
are accounted for explicitly in ft³ using daily cfs × 86400 seconds. There is no
reach travel-time model; the prescribed gauge still controls downstream forcing.

Morganza/Bonnet Carré diversion uses the modeled Tarbert threshold as an empirical
proxy for lower-river operations. Threshold allocation fills Bonnet Carré up to
its configured ceiling, then Morganza receives the remaining excess. Controlled
diversions and pass ratings subtract water **sequentially**, bounded by zero and
the water remaining at each node. Below-range negative ratings are zero before
the next rating is evaluated. Log curves use the natural logarithm of cfs flow.

At Head of Passes, the bounded Southwest Pass fraction is extracted first and
the remainder is split equally into South Pass and Pass a Loutre. The historical
SW Pass piecewise curve is retained, including its small threshold discontinuity.

No independent output smoothing is applied: optional Savitzky–Golay filtering
smooths the input Mississippi and Red forcing before partitioning. It changes
the scenario forcing and is recorded; raw inputs remain in the export.

## Exports and HEC-RAS mapping

Each export includes:

- `flows.csv`, with signed boundary values, gauge/receiving-channel estimates,
  requested/adjusted ORCC flow, hydrograph state, storage, and all residuals.
- `input_data.csv`, `monthly_splits.csv`, and `parameters.json` for reproduction;
  canonical input/split hashes and QA/QC summary in `report.json`.
- `qaqc_issues.csv`, containing dated warnings and information.
- `ForRon.xlsx`, retaining the historical sign convention for ORCC structures.
- `river_budget.png`, `hydrographs.png`, and `boundary_roles.csv`.
- Optional `boundary_conditions.dss`, with preserved historical B-parts plus
  explicit terminal/gauge diagnostics; DSS round-trip precision is reported.
- Optional `stage_input.csv`, retaining the supplied aligned stage data.

Inflows are positive; lateral extractions are negative. Do not double-count
`Minor_Tribs` and its three constituent boundaries. `RedRiver` is external to the
Mississippi mainstem model. `Terminal_Passes` is a legacy alias for **each** of
South Pass and Pass a Loutre, not their sum. Terminal outflow diagnostics are not
automatically appropriate lateral extractions at a model's downstream boundary.
Review the river/reach/station mapping and downstream boundary type before linking.
The workbench does not edit `.q##` or `.s##` files.

DSS E-parts are regular `1DAY` records; the historical A-part `IRREGULAR` is
retained for compatibility and is only a label. Flow values remain `cfs, INST-VAL`.
No random water-level series is generated. An optional stage CSV must contain
`date,stage_ft` with exactly the same dates and coverage as the discharge series.
Verify its datum independently; DSS units are `ft`, without an invented datum.
The original enabled `Generate_WL` even though `WL_data.csv` is absent here.

## Command line and verification

```bash
python -m create_BC --headless --dss --output create_BC/output
python -m create_BC --headless --parameters scenario.json --input my_flows.csv --splits my_splits.csv --output results
QT_QPA_PLATFORM=offscreen python -m pytest -q
```

Generate an editable complete default scenario with:

```bash
python -c "from create_BC import Parameters; Parameters().save('scenario.json')"
```

See [QAQC_FINDINGS.md](QAQC_FINDINGS.md) for the baseline comparison, corrections,
and engineering checks that remain project-specific. The downloader now rejects
partial ORCC totals, unknown units, and negative derived Red River contributions.
It fills only complete interior gaps of at most seven days in non-Overbank series
and reports the interpolation; missing Overbank observations are never assumed
closed. Live CWMS access and source-series semantics require independent review.
