# Collect and mosaic downloaded bathymetry

Run `process_bathymetry.py` after downloading your survey packages. It recursively
finds ZIP archives below the master folder, extracts each package, inventories
rasters inside its file geodatabases, copies selected bathymetry to a new file
geodatabase, and creates one **GeoTIFF** from the collected rasters. The original
ZIPs and source geodatabases are retained. Each extraction, copy, projection and
mosaic stage reports progress to the terminal; long ArcGIS operations also print
elapsed-time messages every 30 seconds.

## Requirements and Windows commands

Use **ArcGIS Pro 3.x's Python environment** (Python 3.9+) with a valid ArcGIS Pro license. ArcPy is
required because the open-source FileGDB drivers available in this project do
not support reading and writing these geodatabase rasters. The script otherwise
uses only Python's standard library; do not install the workbench's pinned
requirements into your ArcGIS Pro environment.

Some inspected MVK/MVM packages contain vector-only geodatabases and a bathymetry
**TIN**, rather than an existing raster. Add `--tin-to-raster` to convert those
TINs, which additionally requires **3D Analyst**. It uses linear interpolation,
floating-point output and a Z factor of 1. Without this option, packages without
selected rasters are reported as skipped. If nothing can be copied, the script
exits with an error and creates no mosaic.

In PowerShell, run this from your local RAS checkout:

```powershell
& "$env:ProgramFiles\ArcGIS\Pro\bin\Python\scripts\propy.bat" .\eHydro\process_bathymetry.py --tin-to-raster
```

The folder picker asks for the **master folder**, for example
`E:\LMR\ehydro_lmr_2025`. Select this parent folder containing `files`, where
the downloaded ZIP archives reside. The script automatically scans `files/`
and any deeper subfolders. Outputs are saved in the selected master folder.
Canceling the picker exits without processing. If a folder picker is unavailable,
an interactive terminal prompts for the path instead.

If your packages already contain rasters, omit `--tin-to-raster`. For a
non-default ArcGIS installation, adjust the `propy.bat` path. From ArcGIS Pro's
Python Command Prompt, the equivalent is:

```bat
python eHydro\process_bathymetry.py --tin-to-raster
```

You can still supply the master path to bypass the picker, including in
automated runs:

```bat
python eHydro\process_bathymetry.py "E:\LMR\ehydro_lmr_2025" --tin-to-raster
```

An extraction and inventory pass can be useful before processing. This creates
the extracted packages and processing report, but no output geodatabase or TIFF:

```bat
python eHydro\process_bathymetry.py "E:\LMR\ehydro_lmr_2025" --inventory-only
```

## Outputs

For a master folder named `ehydro_lmr_2025`, the outputs are:

```text
ehydro_lmr_2025/
  files/                         original downloaded ZIPs
  bathymetry_extracted/          extracted packages in short, hash-named folders
  bathymetry_processing.json     inventory, source paths, parameters, outcomes
  ehydro_lmr_2025.gdb/           individual projected bathymetry rasters
  ehydro_lmr_2025.tif            final single-band, floating-point mosaic
```

Archive names may also be anywhere else under the master folder. The script's
extraction folder, processing workspaces and `.gdb` directories are excluded
from the ZIP search, so embedded ZIPs are not extracted repeatedly. ZIP paths
are validated, and files are extracted to a temporary directory before the
completed extraction is published.

The report lists raster names, metadata, selection reasons, TINs, skipped
packages and errors. Dataset names include a source/configuration hash so that
different packages with the same raster name do not collide. Complete source
paths and dates are retained in the report.

## Selection, grid and overlap

The script selects single-band rasters with bathymetry, elevation, terrain,
depth, DEM/DTM or MB/SB names. It excludes obvious hillshade, slope, intensity,
uncertainty, quality and other ancillary products. A single remaining
unclassified raster is accepted; multiple unclassified rasters require an
explicit selection, for example:

```bat
python eHydro\process_bathymetry.py "E:\LMR\ehydro_lmr_2025" --raster-pattern "*Bathymetry*"
```

Repeat `--raster-pattern` to match additional names. Matching is case-insensitive;
`*` and `?` are supported and underscores are literal. These are name heuristics,
so inspect the inventory to confirm the selected products. Optional TIN selection
uses bathymetry/elevation names, or a single non-ancillary TIN if no name matches;
multiple unclassified TINs require inspection and isolation before conversion.

**Default horizontal grid:** NAD83 / UTM zone 15N (`EPSG:26915`), 5-metre square
cells. Sampled MVK/MVM packages use different source projections, so the script
projects them onto this common grid before mosaicking. It uses bilinear
resampling and 32-bit floating-point storage, retaining NoData without treating
zero as missing. Values can change through interpolation. TIN spacing is
converted from output horizontal units to source horizontal units first.

To use a coarser grid or another projected CRS:

```bat
python eHydro\process_bathymetry.py "E:\LMR\ehydro_lmr_2025" --tin-to-raster --cell-size 10 --output-crs EPSG:26915
```

`--output-crs` also accepts an ESRI code or `.prj` path. When source and output
geographic coordinate systems differ, specify an ArcGIS
`--geographic-transformation`; the error reports available transformations.

**Vertical values are not converted.** Horizontal output coordinates in metres
do not imply that source elevations/depths are in metres. Confirm that all
inputs use compatible Z units, depth/elevation conventions and vertical datums.
Known conflicting vertical CRS names stop the mosaic. Missing vertical metadata
produces a warning; the script cannot infer or reconcile an undocumented datum
or distinguish signed elevation from positive depth by its values alone.

The default overlap rule is `LAST`: surveys are sorted oldest to newest using
acquisition dates from the downloader manifest, then archive filename dates.
For shared package URLs, the latest matching manifest acquisition date is used.
Undated packages are placed first; ties use archive/source paths. The exact
order is printed. A newer survey takes precedence where it has valid data;
NoData gaps can retain older survey data. Use `--overlap FIRST`, `MEAN`,
`MINIMUM` or `MAXIMUM` to change the rule. An annual mosaic combines surveys
collected on different days; it is not a simultaneous riverbed survey.

The terminal reports the estimated rectangular mosaic dimensions, uncompressed
size and free disk space. A river corridor can have a large bounding rectangle.
The default limit is 10 billion cells (`--max-cells`); choose a coarser grid or
explicitly increase the limit if necessary. Allow space for the extracted
packages, collected geodatabase, temporary rasters and final TIFF together.

## Reruns and failures

Rerun the same command after an interruption. Completed extractions are reused
after checking the archive hash, extracted file presence and sizes. Completed
raster copies are reused after validating their grid and checking that they
are not entirely NoData. Incomplete copies recorded as belonging to this script
are replaced. These checks do not compare every copied pixel or detect
same-size edits to extracted files; keep extracted sources unchanged. Changed
archives/configurations create new raster datasets. Old collected datasets are
retained for provenance, but only inputs selected in the current run enter the
new mosaic.

An unchanged, validated mosaic is skipped. If its inputs change, use `--rebuild`
to create a new TIFF; the previous TIFF is retained as a uniquely named backup.
Existing GDBs/rasters/TIFFs that are not recorded as this script's outputs are
preserved. Keep the processing report with its outputs. If Windows locks the
report, the script retries, then saves a `bathymetry-processing-recovery-*.json`
snapshot. Reruns read the newest valid report/snapshot. If both destinations are
unwritable, processing stops rather than losing restart records.

Archive failures are logged while other packages continue. By default any
failure prevents the final mosaic, retaining successful copies for a rerun.
`--allow-partial` explicitly permits a mosaic from successful copies despite
failures; its exit code remains 1. Packages with no selected rasters are counted
as skips, including TIN-only packages when conversion is disabled. Review the
skip/error counts before treating a mosaic as complete. Exit code 0 means the
requested inventory/processing completed without failures; 1 means processing
failed or a partial run had failures; 2 means invalid command-line arguments.

ArcGIS locks may leave a `bathy_work_*` directory or an unfinished
`bathy_mosaic_work_*.tif` after an interruption. Close ArcGIS and remove these
temporary products when no process is using them. They are not input sources.

## Verification

The cloud tests exercise ZIP extraction/protection, selection, restart records,
tool arguments, date ordering, failure handling and mosaic replacement using an
ArcPy test double. `tests/test_process_bathymetry_arcpy.py` additionally creates
small real geodatabase rasters and checks output pixel values, overlap and
NoData when run in a licensed ArcGIS Pro environment with NumPy and pytest.
That test is skipped where ArcPy is unavailable. Native ArcGIS execution is
required to validate actual geodatabase drivers, licensing and projection tools
on your workstation.
