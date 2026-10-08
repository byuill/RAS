# HEC-RAS Sediment Calibration Workbench

A desktop PySide6 application for analyzing, inspecting, and calibrating HEC-RAS
quasi-unsteady **1-D sediment** plan results.

## Purpose
The workbench compares cross-section sediment output with observed USGS/USACE
data or local tables. It derives class mass flux from concentration and discharge,
handles grain-class aggregation, and produces plots and calibration diagnostics.
This reader does not implement 2-D cell/face sediment result analysis.

See the [large-file user guide and validation notes](docs/user-guide.md) for memory
settings, interpretation limits and inspecting an HDF without sharing result arrays.

## Installation
1. Create a virtual environment:
   ```bash
   python -m venv .venv
   ```
2. Activate it:
   - Windows: `.venv\Scripts\activate`
   - Mac/Linux: `source .venv/bin/activate`
3. Install requirements:
   ```bash
   pip install -r requirements.txt
   ```

## Usage
Run the main application:
```bash
python main.py
```

## Features
- Inspect HEC-RAS results directly from `.hdf` files
- Plot Time Series and Rating Curves
- Export plots (PNG, SVG, PDF) and CSV data
- Calibrate model vs observed data
- Time Series Calibration: measured sediment points and fitted rating-derived
  concentration/load series, residual plots, RMSE/bias/NSE/KGE, and comparison CSVs
- Linear, power-law, logarithmic and polynomial transport functions with explicit
  discharge drivers, fit-range limits and optional power-law bias correction
- Byte-bounded HDF and analysis caches; large matrices read by cross section
- Background file/cross-section reads and visible integrity/provenance diagnostics
- Caches observed data in local Parquet files with JSON coverage metadata

## Model Assumptions
- Targets the HEC-RAS 7.x cross-section HDF layout documented in this repository.
  Fallback discovery supports some related layouts; other versions need verification.
- Uses per-class concentrations, or per-class volume-out with known US customary
  class unit weights. Rates reconstructed from output snapshots are estimates.
- Rouse classifications are estimates of transport mode, not measured suspended/bed-load fractions.
- The regression suite uses generated HDF fixtures, including a sparse 2 GB logical
  result dataset. Real project compatibility has not been verified in this review.

## Tests

```bash
python -m pip install pytest
python -m pytest -q
```

Tests create small temporary files; no large model files are required or committed.
