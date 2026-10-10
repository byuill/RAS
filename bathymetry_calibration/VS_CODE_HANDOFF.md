> The `new_bathy_compare` workflow now includes matched spatial-pattern metrics,
> survey QA/QC, direct raster/XYZ CSV input, and comparisons across multiple dates.
> See [README.md](README.md) for current commands, configuration, and validation.
> The local-data/ArcGIS verification tasks below remain relevant; descriptions of
> features in the earlier starter are historical.

# Paste this prompt into the AI chat in VS Code on your local computer

You are working locally in my `byuill/RAS` Python project. Complete and personalize
the initial `bathymetry_calibration` package already present in this repository.
Inspect the repository and these files before editing. Work through implementation,
real-data validation, and a concise handoff, rather than stopping at a plan.

My purpose is to calibrate **1-D HEC-RAS quasi-unsteady sediment bed change** against
measured bathymetry change, using **signed longitudinal cumulative bed-volume
change**. "Cumulative" includes both accumulation **over time** and a spatial sum
**upstream to downstream**. Invert change is related but is not itself volume.
I have ArcGIS Pro / **ArcPy installed locally**. Do not assume its Python path,
HEC-RAS version, survey CRS, vertical datum, actual survey dates, or HDF layouts.

My survey parent directory is:

```
E:\LMR Comp Phase 2\Calibration_2004_2025\sediment_calibration\Bathymetry_Files
```

The geodatabase is expected to be `LMR_Bathy.gdb` there. The 2012 and 2025 surveys
are multibeam bathymetry rasters named `MB_2012` and `MB_2025`. Earlier surveys are
single-beam point surveys arranged as cross-section transects and named `SB_YYYY`.
Discover their actual years, feature-dataset nesting, names, fields, CRS, extents,
elevation/depth conventions, and date metadata. Do not invent missing survey years
or assume a GDB raster can be opened like a GeoTIFF.

Preserve my original HEC-RAS projects, geometry, plan/results files, source GDB,
existing settings, and unrelated code changes. Read original survey/model inputs
only. Place generated data, personal configuration, cache, and exports in explicit
local folders outside the source GDB. Do not reset or overwrite my work. Never
silently edit survey elevations, delete QA/QC observations, or adjust RAS parameters.

## 1. Inspect the local environment and existing implementation

Read `bathymetry_calibration/README.md`, `core.py`, `sources.py`, `arcpy_bridge.py`,
`cache.py`, `workflow.py`, `gui.py`, the demo, example configuration, and tests.
Inspect `ras/hdf_reader.py`, `ras/hdf_discovery.py`, existing workers, plotting,
settings, exports, and GUI integration patterns before adding competing abstractions.

Find the actual repository and RAS project directories using local evidence. Inspect
the available ArcGIS Pro Python executable and verify `import arcpy`, license status,
and necessary raster/geodatabase capabilities. Keep the scientific/PySide6 GUI
environment separate from ArcGIS Pro's default managed environment. Use the existing
subprocess bridge, or an equally well-tested isolation design. Do not install the
repository's NumPy/PySide6 pins into ArcGIS Pro's default environment. Read geodatabase
metadata with ArcPy. Avoid requiring Spatial Analyst/3D Analyst where a supported
base ArcGIS operation works; report any genuine license requirement.

The cloud tests used Python 3.12 and PyArrow 21.0.0 with the repository's NumPy 1.26.4.
PyArrow 26 failed at import with that NumPy version even though pip installation
succeeded. Preserve a compatible GUI stack, run dependency/import checks, and record
reproducible local installation commands. Do not trust pip success alone or transfer
that pin to ArcGIS Pro's environment without checking ArcGIS's requirements.

Run the synthetic demo and existing tests first to establish a baseline. Replace
example placeholders only after local verification. Ask me concise questions only
for information not discoverable locally that is necessary for correct progress;
continue independent inspection and development while awaiting answers. Do not
ask me for secret values, network tokens, or uploads of large local model files.

## 2. Establish the exact native HEC-RAS volume accounting

This is essential; the cloud starter could not access my HDF or the official HEC
documentation host. Do not treat its half-distance control lengths as proven native
HEC-RAS behavior. Identify my installed version and the exact candidate bed-volume
change outputs in the actual plan HDF. Use metadata-only inspection first, then
bounded reads at selected XS and two output times. Inspect compound attributes and
identify River/Reach/Station keys and the true HDF column order. Avoid loading entire
large time-by-XS arrays.

Consult the **official HEC-RAS 1-D sediment technical/reference and results manuals
for my version**, and inspect an actual RAS GUI/table export for a small reach.
Write `docs/bathymetry-native-accounting.md` with:

- Exact native display name, HDF dataset path, version, units, and verified sign.
- Whether values are incremental or cumulative in time, local or already cumulative
  longitudinally, and whether spatial accumulation resets by river/reach or crosses
  branch boundaries. Resolve each dimension separately with numerical evidence.
- Whether volume is **bulk/geometric bed volume** or sediment-solid volume; whether
  porosity is already included; whether grain classes can be summed safely.
- The exact sediment control-volume length at interior XS and boundaries, which
  channel/overbank lengths it uses, active-bed versus movable-bed limits, width
  definitions, cross-section geometry representation, bed-change distribution,
  bank movement/erosion treatment, and any endpoint half-volume rules.
- How the native volume relates to evolving full station-elevation profiles and
  average-end-area reconstruction. Distinguish a native numerical accounting volume
  from a geometrically reconstructed volume if they differ.
- Equations and a small numerical example matching a native RAS GUI export, with
  official document titles, version, section/page, links when available, and measured
  numerical agreement/tolerance. Distinguish documented facts from tested inference.

Implement the exact accounting without double integration:

```
# Native LOCAL and time-cumulative:
dV_i(t0,t1) = B_i(t1) - B_i(t0)
C_k(t0,t1) = sum(dV_i, upstream boundary through XS k)

# Native ALREADY spatial- and time-cumulative:
C_k(t0,t1) = S_k(t1) - S_k(t0)
# For a subreach, subtract the interval prefix just upstream of its start.
# Recover local contributions by adjacent spatial differences if needed.
```

Do not sum time-cumulative snapshots over time, apply reach-length weighting to
stored volumes again, sum absolute deposition/erosion, or spatially sum an already
spatially cumulative variable. Preserve net deposition positive / erosion negative
in the application, converting the native convention only after verification.
Preserve sign reversals and cumulative decreases downstream where erosion occurs.
Never assume raw river-station labels are metres, actual distances, or trustworthy
sort keys across reaches. Explicitly handle river/reach ordering and branches.

Enable a native curve for actual calibration only after its period, domain,
footprint, basis, and prefix convention match the observation reconstruction.
If this cannot be established, label the discrepancy and retain a common-profile
comparison rather than claiming exact native agreement. Do not mark a verification
flag true simply to unblock the GUI.

## 3. Build a shared spatial and temporal comparison contract

Create a verified canonical representation of model XS identity, georeferenced
cut lines, downstream order/chainage, true sediment/channel reach lengths, lateral
station orientation and origin, and the common sediment-bed footprint. Derive these
from actual model geometry or an explicit verified mapping, not an assumed river
centerline distance. Convert horizontal coordinates to a suitable projected CRS
with metre units; distinguish international feet from US survey feet. Use actual
left/right bed limits and maintain consistent footprint rules at both survey dates.
Keep tributaries and repeated station labels from being merged accidentally.

Identify actual survey dates or acquisition windows, not January 1 guessed from
the year. Provide baseline and target selectors and match the model output period.
If survey windows span multiple model outputs, implement and document the approved
temporal matching method (including per-point dates if available). Expose the chosen
model timestamps, alignment tolerance, and limitations. Never silently select a
nearest output outside a tolerance or use first/last output as universal defaults.

Resolve horizontal CRS, vertical datum, elevation units, depth-versus-elevation,
water-level corrections, offsets, and vertical transformations before differencing.
A horizontal reprojection does not align vertical datums. Do not fit a datum offset
to make calibration match. Use a documented transformation or request the genuinely
missing datum information. Record every conversion and datum uncertainty.

Volume comparison requires bed **profiles**, not only invert elevations. Locate
actual evolving model profiles in plan/geometry/sediment outputs; implement adapters
for the real layouts, including ragged profiles and date-named groups as necessary.
If evolving profiles were not output, identify a supported RAS output/export route
and clearly state what must be supplied/regenerated. Never synthesize evolving
profiles from invert changes without an independently verified bed-distribution rule.

## 4. Normalize MB and SB using one integration method

For MB rasters, extract bed-elevation profiles along the canonical XS, using validated
coordinate transformations, an explicit nearest/bilinear sampling choice, consistent
NoData handling, and controlled sample spacing. Process bounded raster windows or
batches. Do not rasterize the entire reach at excessive resolution or use a direct
pixel-area volume as the sole comparison against an unrelated 1-D integration.
A pixel-area result can be an independent diagnostic on a matched footprint.

For SB points, inspect transect IDs, stationing, XY/Z fields, survey dates, duplicates,
outliers, and coverage. Historic survey transects may not coincide with model XS.
Validate their spatial relation, orientation, lateral station origin, and projection
distance. Implement a defensible mapping/interpolation to the canonical XS with
explicit transverse and longitudinal limits; show diagnostics. Do not associate
points solely by nearest model XS across bends, channels, islands, tributaries, or
long unsurveyed gaps. Do not invent dense observations between sparse transects.
If a shared coarser set of sections is needed, apply exactly the same support and
integration to model, MB, and SB and explain the resolution tradeoff.

Use all sources on a fixed common lateral support and the **same verified native
longitudinal/control-volume assumptions**. Start from signed bed-area differences:

```
dA_i = integral_over_shared_bed [z_target_i(u)-z_baseline_i(u)] du
```

Then apply verified native lengths/weights and the native spatial prefix convention
to get local bulk volumes and downstream cumulative volume. The starter's nodal
`ell_i` weighting and average-end-area interval totals are an initial explicit
quadrature only. Adjust them consistently if local native verification requires
other lengths, widths, end rules, or geometric integration. Explain node-prefix
versus interval-prefix curve locations and ensure overlays use the same convention.

Do not extrapolate outside supported survey extents, bridge NoData/large gaps,
convert missing values to zero, or silently truncate to a shorter river domain.
Compute coverage for both dates and both model outputs, flag excluded lateral
segments and longitudinal intervals, and show a coverage summary/map. Full-footprint
native comparison requires full common support or a verified consistent restriction
of native model volume. Partial-footprint results must be explicitly labelled.
Do not compare whole-model bed volumes with only the surveyed channel strip.

Add uncertainty/sensitivity checks for survey vertical bias, point spacing, raster
resolution, interpolation gap limits, XS spacing, coverage, endpoint assumptions,
and native-versus-reconstructed volumes. Identify which are quantified and which
remain unverified. Prefer defensible error bounds; do not present fabricated confidence
intervals or independently fitted corrections as survey uncertainty.

## 5. Complete the GUI and caching

Finish the standalone GUI, or integrate as a bed-change tab if that better fits
existing architecture without disrupting other tabs. Provide:

- Browse/select a `.p##.hdf`, the GDB, a baseline survey and target survey, and actual
  model baseline/target output times; dynamically discover MB/SB datasets.
- River/reach/domain and XS selections, mapping/CRS/datum/footprint controls, sampling
  and coverage controls, clear validation status, and a first-class provenance view.
- Background processing with meaningful progress, safe cancellation and resource
  cleanup, useful error messages, cache-hit indicators, and cache management.
- Overlaid comparable signed downstream cumulative-volume curves, local/interval
  deposition/erosion and residual plots, units, matched dates and domain, uncertainty
  if supported, and coverage diagnostics. A native audit must be visibly distinguished
  until verified comparable. Add invert-change diagnostics separately if useful.
- Export reproducible figures, CSV tables and metadata/settings. Retain multiple
  model comparisons for manual calibration. Comparison is the initial scope; do not
  introduce an optimizer or modify RAS plans unless I separately request it.

Cache processed observation profiles/coverage/provenance outside the GDB. Cache
keys must include dataset identity and trustworthy source content/version state,
survey dates, CRS and vertical transformations, units and sign convention, XS
geometry and bed footprint, grid resolution, interpolation/QA-QC rules, and algorithm
version. Avoid hashing a many-GB geodatabase repeatedly where an equally trustworthy
dataset-specific fingerprint can be proven. File timestamps alone cannot guarantee
validity. Exclude volatile locks, detect input changes during processing, atomically
commit successful results, validate cached schema/checksums, and prevent partial or
corrupt caches from being shown as valid comparisons. Retain enough derived data
that repeat comparisons do not resample/reproject the source surveys unnecessarily.
Do not execute pickle from cache. Allow explicit invalidation and explain why a
request misses the cache. Never delete original datasets when clearing cache.

## 6. Validate, document, and finish

Preserve and extend synthetic tests for known prism/wedge volumes; unequal reach
lengths; erosion/deposition signs; nonzero initial temporal accumulation; both native
cumulative semantics; upstream/subreach prefix origins; variable widths; endpoints;
NaNs and gap rejection; mismatched support; duplicate points; units/datum/date errors;
reversed survey/XS orientation; native-solid/bulk distinctions; branch isolation;
cache hits, invalidation/corruption; and responsive GUI loading/export/cancellation.

Run a small real-data pilot, preferably `MB_2012 -> MB_2025` if their actual dates and
model outputs support that period, then at least one observed SB comparison. Use
the **same** normalization/integration pipeline for each. Validate native time-interval
volumes and the longitudinal sum against RAS GUI/exported tables on selected XS and
one short reach. Compare a known-area/pixel diagnostic only on an explicitly matching
footprint. Confirm cache reuse reproduces results, changed settings invalidate them,
and a fresh application process can reopen valid cached observations. Confirm all
outputs belong to the current model, surveys, and configuration; no zero-test or
metadata-only run establishes the bathymetric workflow.

Acceptance requires documented native semantics; verified ordering, periods, units,
datums, footprints and lengths; comparable model/MB/SB volume curves; meaningful
coverage and residual metrics; source preservation; working GUI and cache; real-data
pilot evidence; and repeatable startup instructions with my actual local paths.
Cumulative residuals are correlated: report local/interval metrics and total bias
along with descriptive cumulative metrics, not an unjustified statistical fit.

Finish by reporting what changed, exact local startup commands, observed native
variable/accounting and evidence, tests/pilot results, cache/output locations, and
any concrete remaining blocker. Distinguish an inaccessible/missing prerequisite
from an application defect and from a scientific assumption. If a key requirement
remains unresolved, explain it precisely and do not claim the calibration is complete.
