# Using the 1-D sediment workbench with large HEC-RAS files

The current review targets **HEC-RAS 7.x quasi-unsteady 1-D sediment results in
US customary units**. Open the computed plan `.p##.hdf` on your own computer;
it does not need to be uploaded to GitHub. Geometry-only files and 2-D cell/face
results do not provide the cross-section time series this reader needs.

## Start and inspect a model

Use Python 3.10–3.12 with the repository requirements installed in a virtual
environment. On Windows, an existing approved Python installation can install
packages in a user-owned virtual environment without changing system Python:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python main.py
```

On Linux use `.venv/bin/python`. Managed government computers may require an
approved Python installation and package access; these commands do not install
HEC-RAS or require it to be running. The workbench reads completed result files.

Click **Open HEC-RAS HDF**, select the computed sediment plan file, then choose
the river/reach/station in **Cross Section**. File opening and initial
cross-section data assembly use background workers. The editing/plot controls
are disabled while those reads finish. A failed open retains the previous model
and does not save the failed path as the last successful file. Successful
replacement and application closure release the old HDF handles.

Use **Diagnostics** before interpreting plots. It now shows model version and
units, input warnings, cache usage, current analysis warnings, dataset provenance
and comparisons with reported total sediment discharge. Errors in time order,
cross-section mapping, required matrix shapes or declared units are reported
instead of repaired by guessing which columns represent which sections.

The Time Series tab's **Export model CSV** button exports the selected sediment
group with hydraulic fields, output interval durations and a `.meta.json`
provenance sidecar. Calibration has a separate **Export Paired CSV** button.

## Memory and long records

Large result matrices are read using an HDF column selection for the requested
cross section. Matrices at most 64 MiB and within the configured HDF budget may
be cached whole to reduce repeated decompression. Float64 results retain their
stored precision instead of being silently reduced to float32.

Settings in `config/app_config.json` include:

| Setting | Default | Meaning |
| --- | --- | --- |
| `hdf_cache_mb` | 256 | Maximum retained raw-array cache, MiB |
| `analysis_cache_mb` | 128 | Maximum retained derived analysis cache, MiB |
| `negative_value_policy` | `keep` | Keep, set to `nan`, or set to `zero` negative concentrations |
| `drop_initial_step_sediment` | `true` | Mask an all-zero first sediment row when subsequent nonzero output exists |
| `sand_min_diameter_mm` | 0.063 | Fines/sand boundary based on representative diameter |
| `rouse_source` | `hecras` | Use complete stored Rouse numbers, otherwise compute; `computed` forces calculation |
| `rouse_kappa` | 0.4 | Kappa for computed Rouse numbers |
| `rouse_susp_max` / `rouse_bed_min` | 1.2 / 2.5 | Suspended/mixed/bed-dominated thresholds |

Close the application before editing settings. Existing saved settings are now
applied to model analysis; invalid types, ranges and display units fall back to
defaults. Preferences are written atomically after successful model opening.
Rating-curve limb/hydrologic colouring also honors the saved hysteresis window
and flow/flood thresholds. Its historical default discharge gate is 500,000 cfs,
suited to the original large-river project; reduce it deliberately for smaller
rivers. The active limb thresholds are displayed below the plot.

Each cache evicts old entries and refuses to retain an entry larger than its
budget. These budgets are **not a cap on total process RAM**: selected time
series/class stacks, HDF decompression buffers, plot arrays and pinned curves
also require memory. Very long records and switching plot modes/categories can
still take time to render. Pins deliberately retain copied snapshots; clear them
when they are no longer needed.

## Interpret sediment quantities carefully

The canonical concentration is mg/L, discharge is m³/s and mass flux is kg/s.
US customary display conversions use **short tons** (2000 lb), not metric tonnes.
The concentration-derived class rate is `C_k × Q / 1000`. Valid negative flow
and velocity are preserved as flow reversals, with signed sediment flux.
Undefined sentinels are masked. Negative concentrations remain a separately
reported numerical artifact governed by the saved policy; physical reverse flux
is not removed by that concentration policy.

**Sand** now means representative diameter from the configured lower cutoff
to **less than 2 mm**. **Fines** lie below the lower cutoff; **Gravel and coarser**
are 2 mm and above. The earlier code included gravel in sand. This correction
can change historical sand plots where coarse classes are present. Grouping uses
the representative diameter, not a fractional allocation of a class spanning
the cutoff.

A group total with a missing contributing class is NaN, rather than a partial
sum presented as a complete load. Rouse partitions also remain unknown when an
unclassifiable class carries nonzero sediment. Positive infinity from zero
computed shear velocity is a valid bed-dominated limit. Unsupported Rouse groups
are disabled in the selectors with explanatory tooltips.

Rouse groups classify the **entire rate of each class** at each output time.
They are equilibrium-profile estimates, not HEC-RAS's measured/solved separation
of bed load and suspended load. Stored HEC-RAS Rouse numbers are used directly;
changing `rouse_kappa` changes only computed numbers. Use `rouse_source:
"computed"` to evaluate another kappa. Observed suspended SSC/load is not
automatically an equivalent measurement of total modeled transport.

Load plots use the final rate of each backward output interval times that
interval's duration. They are **integration estimates from output rates**, not
native cumulative-mass records. Year-crossing intervals are divided by duration
between calendar years or October–September water years. Missing intervals are
excluded and counted visibly; a year with no valid interval mass is not reported
as a zero load. Compare estimates with HEC-RAS cumulative/volume budgets and
check output-frequency sensitivity before reporting annual loads.

Volume-out reconstruction interprets the documented US customary class unit
weights as lb/ft³ and checks volume units. SI grain unit-weight reconstruction is
disabled where its metadata convention has not been established. SI concentration
and hydraulic unit conversion is supported, but this review's target is US customary.

## Observations and calibration

Import a CSV/Excel table or use the station providers. Inspect the detected
columns and units. Recognized parenthesized units are respected, including
`m³/s` and `L/s`; unsupported/incompatible declared units are refused. Bare
headers still use documented defaults (for example discharge `cfs` and SSC
`mg/L`), so label columns with units whenever possible.

Time pairing never extrapolates outside the model period and does not remove
missing model steps to interpolate across them. Nearest pairing requires a
finite neighboring step within its tolerance. Duplicate model timestamps are
refused. Use the observation-clock offset deliberately: HEC-RAS date stamps do
not supply a time zone, and provider/local clocks may differ. A fixed offset
does not account for daylight-saving changes. Daily observations are paired at
their stored timestamp; they are not automatically paired to a model daily mean.

Automatic gauge mapping requires a recognized project projection. The built-in
transform handles the repository's Albers convention. If the projection is
missing/unsupported, projected coordinates are retained where available and
stations must be mapped manually. The application no longer assumes every
model uses the same Albers projection. Verify the river/reach and vertical datum
as well as proximity; nearest geometry alone does not prove hydraulic equivalence.

The local observation cache uses Parquet plus JSON coverage metadata. Access
within one workbench instance is serialized to prevent overlapping stores from
losing records/coverage. A change in cached value units is refused until the
station cache is rebuilt. External provider responses and live endpoint behavior
were not validated in this review. Avoid concurrently writing the same cache
from separate application processes.

## Inspect or share metadata without the large results

From the repository folder:

```powershell
.venv\Scripts\python tools\hdf_metadata.py "C:\Models\river.p01.hdf" --output model-metadata.json
```

The JSON includes dataset paths, shapes, dtypes, logical sizes, compression,
Units/Grain Class attributes and file version/unit system. It **does not read or
include result-array values**, station table contents or full model paths.
Review it before sharing: dataset names can still contain identifying labels.
The default limit is 5000 datasets; `--limit` changes it and the report indicates
truncation. A readable tree is available with `tools/hdf_tree.py`; that CLI now
prints its output and returns a failing status for an unreadable file.

## Verification and limits of this review

```powershell
.venv\Scripts\python -m pip install pytest
.venv\Scripts\python -m pytest -q
```

Tests generate temporary HDF files with the documented 7.x-style cross-section
layout. They cover unit conversions, class-only datasets, signed reversals,
volume reconstruction, invalid metadata, midnight rollover, memory limits,
missing-data pairing, year-boundary integration, observation-cache concurrency,
GUI model replacement/shutdown, load views, calibration and CSV export.
A sparse dataset has a **logical size of 2 GB** while its physical test file is
small; a read guard verifies that it is never loaded as a whole matrix.

These tests verify code behavior against deliberately constructed inputs.
They do not establish compatibility with every HEC-RAS 7.x output variation,
performance on your actual file compression/chunk layout, or physical calibration
of your project. No real HEC-RAS result file was available for this review.
