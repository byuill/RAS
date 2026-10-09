# HEC-RAS bathymetry comparison and survey QA/QC

Compare evolving 1-D model cross sections with dated bathymetric rasters and
survey point profiles. The workbench compares **signed bed change on matched
lateral support**, and reports both the magnitude of the error and how well the
model reproduces erosion/deposition zones and longitudinal bed shape.

The application reads dense `[time, XS, knot]` and ragged HEC-RAS Station Elevation
outputs. Surveys can be normalized cross-section CSVs, projected XYZ CSVs,
single-band raster files such as GeoTIFFs, or ArcGIS geodatabase rasters/points.
Direct raster/CSV processing works without ArcGIS. File geodatabases use the
configured, separately licensed ArcGIS interpreter.

## Start and compare

Use Python 3.12 in a separate virtual environment:

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt pytest
python -m pytest -q
```

The dependencies include `pyarrow==21.0.0` for the pinned NumPy 1.26 stack,
Rasterio 1.4, and Affine 2.x. Keep the GUI/scientific environment separate from
ArcGIS Pro's managed Python environment. Do not install these requirements into
ArcGIS Pro's default environment.

Copy `examples/local.example.json` to a personal configuration folder. Relative
paths resolve against that folder. Supply actual acquisition dates, correct
vertical units/datum, and a verified transect manifest. Verification flags must
record completed checks rather than suppress errors. The supplied `real_config.json`
contains project-specific paths and assertions from the branch; verify them on
your machine, including the acquisition date of its `MB_2025` layer.

```bash
python -m bathymetry_calibration --config /path/to/config.json --hdf /path/to/plan.p01.hdf
```

The HDF argument can be omitted if `model.path` is configured. Choose a baseline
and target survey, review **Survey QA/QC**, then compare. Model outputs must be
ordered and within `survey_alignment_tolerance_days` of the actual survey dates;
out-of-tolerance comparisons fail. Automatic date matching does not establish
that a survey spread across several months represents one instantaneous state.

The main plot shows segment cumulative volume and mean bed elevation change.
**Pattern diagnostics** adds magnitude scatter, standardized change, observed
zones, baseline/target elevations, slopes, and concavities. Choose bed-change,
baseline-bed, or target-bed derivatives. **Cross-section profiles** displays the
four original interpolated profiles and their changes on accepted intervals,
without drawing lines across missing-data holes. IDs may be text; physical
chainage, not an inferred river mile, determines downstream ordering.

**Compare all survey intervals** sorts configured surveys by acquisition date
and compares consecutive pairs. Every interval uses the same common support
across all selected model and survey epochs. This prevents changing survey width
or NoData coverage from masquerading as a temporal trend. Model and observed
annual rates each use their own matched dates. Red/blue heatmaps show deposition/
erosion through time; black dividers mark disconnected supported segments.

## Survey QA/QC

Survey QA/QC runs independently of model selection and before duplicate-resolution
errors stop a comparison. It reviews the **extracted transect samples**, not every
cell in the original terrain raster. Review full-raster seams/stripes, metadata,
benchmarks, and horizontal alignment in your GIS as well.

The review flags missing/nonfinite elevations, duplicate stations, optional
physical elevation limits, excessive lateral slopes, isolated robust spikes,
and large sampling gaps. Spikes are deviations from neighbouring linear profiles
that exceed both a physical threshold and a robust MAD limit. Natural banks,
sharp breaks in slope, and real scour can also flag: no finite value is removed
by default.

The table and profile plot show original and used elevations. Review thresholds,
exclude selected points, or explicitly enable exclusion of finite elevation/
spike/slope flags. Exclusions leave NaN barrier knots. Duplicate stations require
an explicit `mean`/`median` aggregation decision or remain an error; missing or
excluded duplicate rows cannot be resurrected by averaging. **Restore raw values
and decisions** removes the session's filtering and correction decisions.

A coherent survey-to-survey elevation shift is reported as a **candidate** datum
issue, with median shift and robust scatter. Uniform real bed change is also a
possible explanation. Supply independently verified stable controls to strengthen
that check. A signed correction is only applied when you specify it and record
benchmark/datum evidence; no correction is inferred from the model residual.
Changing QA/QC options reuses cached raw extraction and leaves source data intact.

Apply decisions to the comparison, recompute, and use **Save configuration copy**
to preserve the reviewed settings. Exports contain all audit rows, including rows
beyond the GUI's 2,000-row display cap. Model comparisons retain warnings about
flagged values still in use, reduced footprints, excluded sections, and skipped
native audits.

## Interpret model performance

| Diagnostic | Meaning |
| --- | --- |
| Signed volume bias, interval volume RMSE/MAE | Amount of geometric change and error; deposition positive, erosion negative |
| Mean-change RMSE and bias | Bed elevation change error on the matched sampled footprint, in metres |
| Demeaned change RMSE | Residual spatial-pattern error after removing each series' uniform mean; does not correct the data |
| Weighted shape/rank correlation | Similarity of the downstream spatial pattern, independent of uniform offset and positive magnitude scaling |
| Amplitude ratio / regression gain | Whether model spatial variation is too strong/weak; gain relates model change to observed change |
| Zone agreement / erosion and deposition IoU | Location agreement for erosion, deposition, and changes within the detection threshold |
| Change and baseline/target slope/concavity | Direction and curvature of downstream mean-bed trends, using physical chainage and supported segments |

For example, a model predicting twice every observed change can have perfect
pattern correlation and zone agreement while retaining a substantial magnitude
error. A constant series has **undefined** correlation/amplitude statistics;
JSON reports use `null`, never a fabricated perfect score. Zone confusion is
weighted by supported control length. Magnitude/shape metrics are weighted by
sampled width times control length, preventing dense XS spacing from dominating.

Derivatives are **unsmoothed** local finite differences with metres/kilometre and
metres/kilometre² units. At least three consecutive supported XS are required for
concavity. Noise, sparse spacing, and lateral footprints changing between XS can
affect these derivatives. They describe sampled **mean bed** rather than the
thalweg or a reach-wide 2-D terrain surface. Inspect cross-section profiles and
footprint coverage before making physical inferences.

The zone detection threshold defaults to 0.05 m and is configurable. If survey
`vertical_uncertainty_m` values are supplied as independent one-sigma uncertainties,
the threshold is at least `1.96 * sqrt(sigma_before² + sigma_after²)`. This is a
simple 95% difference detection limit, not a spatially correlated uncertainty
model. Thresholds classify patterns only: sub-threshold changes remain in the
signed volume accounting.

## Accounting and support

All elevations, lateral stations, and lengths are converted to metres before
comparison. Per XS, the engine builds the intersection of the four profile
extents and the manifest transect, includes source knots and NaN barriers, and
integrates only intervals valid in every source. It neither extrapolates nor
bridges explicit NoData knots or source gaps wider than `max_gap_m`.

`domain_mode: "intersection"` compares their overlap and reports both overlap
coverage and full-transect footprint coverage. `domain_mode: "transect"` requires
coverage of the specified footprint. `min_common_width_m` defaults to zero, so
small channels and the known-answer demo work; the real project can retain its
50 m setting. Insufficient sections are recorded, not silently filled. Unsupported
XS disconnect longitudinal integration; no volume, derivative, or zone crosses
them. A partial/disconnected result describes the supported portions only.

Let `dA_i` be the trapezoidal integral of signed elevation change on accepted
lateral intervals. Use the manifest's **verified channel length** `L_i`, rather
than replacing it with an unrelated station/chainage difference:

```
interval_volume_i = 0.5 * (dA_i + dA_(i+1)) * L_i
control_length_0 = L_0 / 2
control_length_i = (L_(i-1) + L_i) / 2
control_length_n = L_(n-1) / 2
local_volume_i = dA_i * control_length_i
```

Apply these rules independently within each supported segment. Node cumulative
and interval-prefix curves are exported separately: they have the same final
segment total but different intermediate values. Cumulative RMSE is descriptive;
its residuals are strongly correlated, so review local/interval errors too.

Native RAS volume is a separate audit. It requires verified variable semantics,
bulk basis, units/sign, `footprint_verified: true`, contiguous full support,
recorded evidence, and its own `time_dataset`. Native dates are matched explicitly
to profile dates; SE and sediment result indices are not assumed interchangeable.
Spatial cumulative orders must describe exactly one verified reach, respecting
branch resets. Reduced support skips the audit with a persistent reason.
The branch's native-accounting notes do not replace numerical local verification.

## Input configuration

The manifest requires `xs_id,model_column,chainage_m,length_to_next_m,u_m,x_m,y_m`.
Each XS has one model column and chainage, at least two unique lateral stations,
and a verified positive channel length except at the final selected XS. Chainage
must increase downstream within one reach. XY must be in the projected metre
`analysis_crs`, and lateral stations must align to the model's oriented profiles.
Use explicit river/reach identities to distinguish repeated station labels.

Normalized `kind: "csv"` surveys require `xs_id,u_m,z_m` already in metres in the
common datum. Blank elevation represents missing data. Raw `kind: "xyz_csv"`
surveys require explicit field mappings and projected-metre coordinates:

```json
{
  "kind": "xyz_csv",
  "path": "survey.xyz.csv",
  "fields": {"x": "Easting", "y": "Northing", "z": "Elevation"},
  "horizontal_mapping_verified": true,
  "date": "2025-01-01",
  "vertical_datum": "NAVD88",
  "vertical_alignment_verified": true,
  "z_scale_to_m": 1,
  "z_offset_m": 0,
  "qaqc": {"duplicate_policy": "error"}
}
```

XYZ points map once to the nearest selected polyline within
`integration.longitudinal_limit_m` (default 50 m). Curved-polyline lateral stations
interpolate the manifest's station coordinates. Points equally close to different
XS within `ambiguity_tolerance_m` (default 0.01 m) remain unmatched. Mapping counts
and distances are retained in the audit/cache. This proximity mapping does not
prove that historic survey sections occupy the same physical section; verify
registration and choose a defensible distance limit.

Direct rasters use `kind: "raster"`, `path`, `sampling: "nearest"` or `"bilinear"`,
and explicit vertical scaling. They require a known CRS and one elevation band.
A different analysis/raster CRS requires verified horizontal mapping. Bilinear
sampling retains NoData in any contributing cell and never silently switches to
nearest. Raster samples are densified along the actual polyline using
`integration.sample_spacing_m`.

Geodatabase sources retain `gdb_raster`, `gdb_points`, and `gdb_points_raw`.
Configured SB fields must exist; the bridge no longer guesses an alternative Z
field. Different horizontal datums need an explicit ArcPy transformation. ArcPy
bilinear sampling requires Spatial Analyst; a license/operation failure is a
reported error rather than a change of acquisition method.

Typical QA/QC and diagnostic options (choose limits for your own river):

```json
{
  "qaqc": {
    "elevation_min_m": -100,
    "elevation_max_m": 50,
    "max_slope_m_per_m": 2,
    "spike_min_m": 1,
    "robust_z_limit": 6,
    "exclude_flagged": false,
    "duplicate_policy": "error",
    "excluded_points": [],
    "datum_correction_m": 0,
    "datum_correction_evidence": ""
  }
}
```

Place `qaqc` under each survey. Manual exclusions are
`{"xs_id":"River:Reach:XS", "u_m":120, "reason":"Reviewed bad sounding"}`.
Top-level `diagnostics` supports `change_threshold_m`, `slope_threshold_m_per_km`,
`concavity_threshold_m_per_km2`, `datum_shift_threshold_m`, and `stable_controls`
(a list of independently verified stable `{xs_id,u_m}` locations).
`z_offset_m` is part of source normalization; `qaqc.datum_correction_m` is an
additional reviewed correction. Do not count the same offset twice.

Dense HDF mappings use `elevation_dataset`, `station_dataset`, and `time_dataset`.
Ragged SE mappings use `layout: "ragged_se"`, `se_group`, and `time_dataset`.
The reader validates start/count slices and reads only selected XS and outputs.
HEC stamps ending `24:00:00` are interpreted as midnight of the following day.
Static initial geometry must never stand in for both evolving profiles.

## Headless workflows and exports

```bash
python -m bathymetry_calibration --config config.json --hdf plan.p01.hdf --headless --before-survey baseline --after-survey target --output results
python -m bathymetry_calibration --config config.json --hdf plan.p01.hdf --series --surveys survey_2012 survey_2018 survey_2025 --output results
python -m bathymetry_calibration --config config.json --qaqc-only --output results
```

Pair output indices may be specified explicitly, otherwise nearest model dates
are selected and checked against the configured tolerance. Each export creates a
new timestamped directory. Pair exports contain `sections.csv`, `intervals.csv`,
`profiles.csv`, `zones.csv`, `zone_confusion.csv`, `survey_qaqc.csv`, optional
`excluded_sections.csv`, a strict `report.json`, and comparison/diagnostic PNGs.
Time-series exports add `interval_skill.csv`, `section_time_series.csv`, a rate
heatmap, and complete per-interval results. Standalone QA/QC exports contain all
sample audit rows and section gap counts.

Raw survey extraction is cached atomically with checksums and content fingerprints.
The new schema invalidates older processed caches. Geodatabase contents are hashed;
raster mean or point count alone is not trusted to detect spatial edits. Fingerprints
are shared within a run, and changed inputs are rejected. Large GDB hashing can
still be expensive. No pickle is loaded, and cache/output paths must stay outside
the source geodatabase. Cancellation stops between read-only processing steps;
an active ArcPy/file read must finish before the operation can close safely.

## Known-answer validation and local limits

```bash
python -m bathymetry_calibration.demo --output /new/empty/demo
python -m bathymetry_calibration --config /new/empty/demo/config.json --hdf /new/empty/demo/synthetic.p01.hdf --headless --before-survey baseline --after-survey target --output /new/exports
```

Expected totals are **+2000 m³** model and observed; local contributions are
`[500,1000,500]` and node prefixes `[500,1500,2000]`. The fixture is synthetic,
not an asserted real RAS layout. Regression cases also test pattern agreement
with magnitude error, reversed zones, irregular-spacing derivatives, disconnected
support, robust survey review, direct GeoTIFF/XYZ input, ragged reads, time-series
support, and GUI review/restore/configuration saving.

Real HEC-RAS compatibility, exact native footprint/control-volume accounting,
ArcGIS licensing, vertical transformations, and project acquisition dates still
need verification on the local machine with your data. See `VS_CODE_HANDOFF.md`
for that work. The tool assesses comparisons; it does not change model parameters,
run RAS, or fit an automatic calibration optimizer.
