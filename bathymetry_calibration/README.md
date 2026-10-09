# Initial bathymetry-volume calibration tool

This is an executable starter, with a standalone PySide6 GUI, calculation engine,
ArcPy subprocess adapter, content-addressed observation cache, synthetic demo,
and CSV/JSON/figure exports. It does **not** claim validation against your local
HEC-RAS files or `LMR_Bathy.gdb`. Use [VS_CODE_HANDOFF.md](VS_CODE_HANDOFF.md) to
finish the local adapters and verify the native accounting before interpreting
real calibration results.

The GUI selects a plan HDF, geodatabase, baseline/target surveys, and baseline/target
model outputs. The configured survey selectors refer to datasets **inside** the
geodatabase; a `.gdb` is a directory, not a raster file. Survey year alone does not
establish a baseline date. Earlier SB survey years must be discovered locally.

## Volume accounting

Let `B_i(t)` be native **local**, time-cumulative bed-volume change at XS `i`.
For survey dates `t0 < t1`, the correct interval change and downstream prefix are:

```
dV_i = B_i(t1) - B_i(t0)
C_k  = sum(dV_i, i=0..k)             # explicitly ordered upstream -> downstream
```

Do not sum the already time-cumulative values over saved output times, take their
absolute values, or multiply stored volumes by reach length. Deposition is positive
and erosion negative in this tool; the native sign convention must be verified.

If the native stored variable is **already both time- and longitudinal-cumulative**,
`S_k(t)`, its interval longitudinal curve is simply `S_k(t1)-S_k(t0)`. To recover local
volumes for a subreach, difference adjacent *spatial* prefixes. Subtract the prefix
immediately upstream of the selected domain to establish its own origin. The native
audit adapter supports these two semantics explicitly and tests that neither is
double summed.

Names such as `Volume Bed Change Cumulative` or `Vol Bed Change Cum` are candidates,
not a sufficient semantic contract. The exact variable name, HDF path, time meaning,
spatial meaning, control lengths, bed footprint, units, sign, and bulk versus solid
volume basis are **unverified for your project**. The official HEC documentation
host was blocked by the cloud network during this work. The local handoff requires
checking the official manual and a numerical RAS GUI export. No native formula is
presented as verified merely because the word "cumulative" appears in a name.

## One method for model, MB rasters, and SB transects

Use the same fixed, georeferenced transect lines, lateral station grid, sediment-bed
footprint, downstream order, and model reach lengths for every source and date.
Convert all bed elevations to metres in a common vertical datum; do not substitute
water depth, thalweg elevation, or invert-only change for a full bed profile.

For valid common lateral intervals `[u_j,u_(j+1)]`, compute signed cross-sectional
bed-area change using trapezoidal integration:

```
dz_ij = z_i(t1,u_j) - z_i(t0,u_j)
dA_i  = sum(0.5 * (dz_ij + dz_i,j+1) * (u_j+1-u_j))       # m²
```

Let `L_i` be the **verified sediment/channel reach length** from XS `i` to XS `i+1`.
The starter uses a lumped average-end-area quadrature:

```
ell_0 = L_0/2
ell_i = (L_i-1 + L_i)/2                                   # interior nodes
ell_n = L_n-1/2
dV_i  = dA_i * ell_i
C_k   = sum(dV_i, i=0..k)                                 # primary plotted curve
```

This declares half-interval endpoints and no extrapolation outside the first/last
XS. The final total is algebraically identical to the average-end-area total:

```
sum(dV_i) = sum(0.5 * (dA_i+dA_i+1) * L_i)
```

Both the node-prefix tally and interval-prefix curve are exported. Their final
totals agree, but their intermediate values differ: a node-prefix is a discrete
control-volume tally, **not** the continuous integral evaluated at each XS center.
The first node-prefix includes the first half-interval contribution and need not
be zero. Never overlay different prefix conventions as if they were identical.

This quadrature is an explicit starter assumption; it is not yet verified as your
RAS version's exact sediment control-volume implementation. If RAS uses different
end lengths, footprint widths, or nodal accounting, reproduce those rules for
**all** sources. The optional native curve remains an audit until this is proved.

The engine linearly interpolates supplied profiles onto the common lateral grid
without extrapolation or bridging NaNs/large gaps. The ArcPy raster adapter currently
uses explicitly labelled **nearest-cell** sampling. Acquisition methods differ;
the comparison grid, common support, and volume integration are identical. Local
completion should add tested bilinear sampling and sample-spacing sensitivity.

All four profiles (model before/after, survey before/after) share the same accepted
lateral intervals. The default requires 100% common support. A lower threshold
creates a labelled *partial-footprint comparison*, not a full-bed native-volume
calibration. Native audits are refused on partial support. Missing XS and excessive
longitudinal gaps are rejected, never bridged silently. Masks may differ between
XS, so local completion must verify the spatial coherence of any partial footprint.

## Run the known-answer demo

From the repository root, using a Python environment with the repository's scientific
and PySide6 dependencies:

The cloud-tested stack uses Python 3.12 and `pyarrow==21.0.0` with the repository's
`numpy==1.26.4`. PyArrow 26 failed to import with that NumPy pin despite pip accepting
the installation. Have the local assistant prepare a separate GUI environment and
verify imports; do not run dependency installation in ArcGIS Pro's default environment.

```powershell
python -m bathymetry_calibration.demo --output C:\Temp\ras-bathy-demo
python -m bathymetry_calibration --config C:\Temp\ras-bathy-demo\config.json --hdf C:\Temp\ras-bathy-demo\synthetic.p01.hdf
```

Use an empty demo folder. The fixture has a 10 m bed width, 200 m domain length,
and +1 m elevation change: **+2000 m³** model and observed totals. Local contributions
are `[500,1000,500] m³`; longitudinal prefixes are `[500,1500,2000] m³`.
The fixture's HDF layout is intentionally synthetic, not an asserted RAS layout.

Headless processing/export:

```powershell
python -m bathymetry_calibration --config C:\Temp\ras-bathy-demo\config.json --hdf C:\Temp\ras-bathy-demo\synthetic.p01.hdf --headless --before-survey baseline --after-survey target --output C:\Temp\ras-bathy-exports
python -m pytest -q tests/test_bathymetry_calibration.py
```

## Local setup and input contracts

Copy `examples/local.example.json` to a personal configuration location and replace
its placeholders. Do not set verification flags to true just to bypass an error.
They record actual geometry, datum, time, and dataset verification.

Keep the GUI/scientific environment separate from ArcGIS Pro's managed Python
environment. Set `arcpy_python` to a locally verified ArcGIS Python executable;
the bridge uses only stdlib and ArcPy, writing JSON to temporary files. Do not
install this repository's pinned NumPy/PySide6 requirements into the default
ArcGIS Pro environment. If the GUI interpreter already has working ArcPy,
`arcpy_python: null` uses that interpreter. The GUI does not require importing
ArcPy itself. Test license availability and environment activation locally.

`transects.csv` requires one row per common lateral sample:

| Column | Meaning |
| --- | --- |
| xs_id | Unique text XS identity within one selected river/reach |
| model_column | Verified zero-based HDF result/profile column |
| chainage_m | Strictly increasing downstream physical chainage; not raw river-station subtraction |
| length_to_next_m | Verified downstream sediment/channel length; blank only on the final XS |
| u_m | Lateral station along the oriented model XS, in metres |
| x_m, y_m | Coordinates on the actual model XS in the configured projected metre CRS |

The same XS metadata repeats on every lateral sample row. The starter selects one
contiguous reach. Use explicit river/reach/XS identities when building this manifest;
do not merge repeated station labels from different reaches or tributaries.

Normalized profile CSVs require `xs_id,u_m,z_m`. They already contain **bed elevations
in metres in the common datum**. Blank `z_m` represents missing data; duplicate
lateral stations are rejected until an explicit QA/QC rule resolves them.

For SB geodatabase point features, add a survey configuration entry with:

```json
{
  "kind": "gdb_points",
  "path": "E:\\LMR Comp Phase 2\\Calibration_2004_2025\\sediment_calibration\\Bathymetry_Files\\LMR_Bathy.gdb",
  "layer": "REPLACE_WITH_DISCOVERED_SB_LAYER",
  "date": "REPLACE_WITH_ACTUAL_SURVEY_DATE",
  "fields": {"xs_id": "REPLACE", "u": "REPLACE", "z": "REPLACE"},
  "transect_station_mapping_verified": false,
  "vertical_datum": "REPLACE",
  "vertical_alignment_verified": false,
  "u_scale_to_m": 1,
  "z_scale_to_m": 1,
  "z_offset_m": 0
}
```

This adapter needs preverified SB-to-model XS identities and lateral stations. It
does not assume irregular historic survey transects coincide with model XS or infer
bed elevations from an unlabelled depth field. That mapping is a local completion
task. A vertical offset is permitted only for a documented datum correction; it
cannot silently stand in for a spatially varying vertical transformation.

The initial HDF profile adapter accepts verified numeric `z[time,XS,knot]` with
`u[knot]` or `u[XS,knot]`, and a 1-D date-stamp dataset. Actual RAS evolving profiles
may be ragged, stored in groups by output date, absent from the plan HDF, or need
companion geometry/result outputs. Extend the adapter after inspection; never
use static initial geometry as both evolving profiles or infer volume from invert
alone. Only selected XS and two time slices are read.

An optional `native_volume` configuration supports a verified `[time,XS]` dataset:
`verified`, a nonempty documented `evidence`, `dataset`, `basis: "bulk_geometric"`,
`scale_to_m3`, `deposition_sign: 1 or -1`, and `semantics` equal to
`local_temporally_cumulative` or `spatial_temporally_cumulative`. The latter also
requires the full reach's verified `spatial_order_columns`. Solid-sediment volumes
are rejected; conversion needs a separately verified porosity contract.

## Cache, outputs, and current limits

Processed observations are cached outside the geodatabase. Keys include SHA-256
content fingerprints, layer/field/unit/datum configuration, geometry/grid contents,
and adapter version. Cache payloads include a checksum and are committed atomically.
No pickle is loaded. Changed survey/geometry/settings invalidate the cache; corrupt
entries are recomputed. Missing-data profiles may be cached as extracted data, but
they do not bypass comparison coverage checks. Sources changed during extraction
are rejected before a cache entry is committed.

The conservative starter hashes the entire GDB and uses per-point raster sampling.
Both can be slow on large data. Local completion should improve these without
weakening invalidation, coordinate correctness, or read-only source handling.

Exports contain per-XS area change, local and cumulative volume, coverage, control
lengths, per-interval volumes/residuals, metrics, and provenance. The GUI adds a plot.
Each export creates a new timestamped directory. Cumulative RMSE is descriptive;
its errors are strongly correlated. Evaluate local/interval errors and total bias
too. The tool currently compares results; it does not edit RAS parameters or run
an automatic calibration optimizer.

Unimplemented local tasks include exact native RAS accounting verification, real
HDF profile layouts, common model/SB transect construction, large-GDB performance,
date-window treatment, full vertical transformations, uncertainty envelopes,
cancellation, and integration into the existing workbench's tabs. The starter runs
as a separate GUI so existing workflows remain available.
