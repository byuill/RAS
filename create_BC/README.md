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
   Labels sit in separate cards outside the connector lanes. Use the diagram-view
   selector for the full network, regional/ORCC, or lower-river detail; scroll to
   inspect the figure at its readable minimum size. The forcing/estimated-flow
   gap is displayed at Union Point. **Ratings & operating rules**, **Hydrographs
   & residuals**, **Daily ledger**, and **QA/QC & assumptions** provide the audit.
5. Export to a new run directory. DSS is optional and its values, timestamps,
   units, and record counts are checked by reading every record back. Existing
   calibration data, DSS files, and HEC-RAS model files are not overwritten.

The application calculates and exports in a background worker. On a headless
machine, use the CLI below; `QT_QPA_PLATFORM=offscreen` is for GUI testing only.

### Limb delineation

The **Limb delineation** tab illustrates the current hydrograph-state rules on a
fixed synthetic daily Lower Mississippi hydrograph: winter pulses, sustained
spring high water, a summer recession, and a fall low-water period. It is an
illustration, not observed data or a forecast. Shading and a matching state strip
identify normal, rising, crest, falling, and low-water days. Separate annotation
cards show the rule thresholds and classified day counts without obscuring the
hydrograph. The plot scrolls on smaller windows to keep the annotations readable.

Edit **Scenario parameters → Hydrograph state**, then click **Update plot** in
the tab to apply the edits without recalculating boundaries. The same engine
classifier is used, including flood memory, the preceding rise-window and six-day
means, and the crest continuation counter. Changing thresholds does not reshape
the synthetic forcing to manufacture a particular state; some settings can
produce zero days of a state. The reference gauge and input smoothing also apply
to the illustration. A preceding synthetic year supplies trailing history.
If supplied-state mode is selected, the tab still illustrates the automatic
rules and explains that actual runs instead use the CSV state column. The
head-constraint proxy is displayed separately when enabled. This tab does not
modify input files, the current budget result, or exported boundaries.

### Junction percentages

For a withdrawal, `out` is withdrawn flow divided by the mainstem flow arriving
at that junction, and `stays` is the remaining fraction. For a tributary/return,
`in` is that contribution divided by the merged flow after the confluence, and
`main` is the share from the upstream mainstem. Percentages use those local
references, not one gauge denominator for the entire river.

The MMR/Ohio confluence uses their combined total. ORCC and Tarbert branches use
Union Point; the four structure shares use total ORCC. ORCC/Red River contributions
to Simmesport use their receiving-channel total. All three terminal fractions use
Head of Passes. The actual Mississippi fraction of latitude flow is displayed
separately because it has a different denominator from the Union Point split.
At zero reference flow, share is undefined (`—`), not a fabricated zero percent.

The **Junction percentages** subtab includes flow magnitudes, local reference
flows, percentage bases, and mainstem flow after each applicable confluence or
withdrawal. `All flow / audit fields` retains the original signed ledger. Use
**Largest gap** to inspect the maximum upstream discrepancy, or the arrow buttons
to move one day at a time. Recalculation preserves the inspected date when it is
inside the new input range.

### Ratings and operating rules

The tab provides a seven-pass overview and individual plots for every pass,
terminal fractions, controlled diversions, spillway allocation, Birds Point/
New Madrid, and the ORCC total target. Individual pass views show both discharge
and its percentage of local inflow. By default applied pass outflows are shown;
enable **Show raw formulas** to inspect negative or over-available raw requests.
Use **Auto range**, or set the maximum input flow explicitly. **Edit parameters**
opens the relevant group and, for an individual pass, scrolls to its coefficient.

Orange markers show the selected day's applied output at the correct local input.
Grey bands mark the input span encountered at that location in the loaded run;
they are not asserted calibration ranges. Explanations name each curve's input,
formula, bounds, sequential role, and any inactive controls. ORCC ratio lines in
prescribed-total mode are explicitly labeled inactive alternatives. New Madrid
is shown as a delayed return kernel because today's return depends on earlier
diversions, not just today's discharge. Terminal pieces are drawn separately at
their switch so a discontinuity is visible rather than visually interpolated.

All views use the last calculated scenario. Editing parameters disables export
and displays a stale-results notice until **Calculate & check budget** is run.
Greyed parameter controls are inactive in the selected workflow; their values
remain in the saved scenario. Group introductions explain relationships visible
in the original code without assigning undocumented physical interpretations.

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
- `river_budget.png`, `hydrographs.png`, `pass_ratings.png`, and `boundary_roles.csv`.
- `junction_budget.csv`, with percentages and explicit reference flows for the
  selected diagram date, which is also recorded in `report.json`.
- `rating_notes.html`, with formulas and operating-rule explanations for the
  saved scenario. Open it in a browser alongside the exported plots.
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
