# HEC-RAS Sediment Calibration Workbench

A desktop PySide6 application for analyzing, inspecting, and calibrating HEC-RAS sediment transport models.

## Purpose
The workbench simplifies the comparison of HEC-RAS 2D/1D sediment output against observed USGS and USACE data. It calculates derived quantities like sediment load, handles grain class aggregation, and produces presentation-ready plots.

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
- Caches observed data via local SQLite/Parquet for performance

## Model Assumptions
- Assumes sediment concentrations are recorded in HDF output.
- HEC-RAS version >= 6.0 results format.
