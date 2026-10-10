"""Inspect HDF layout/units without reading result arrays."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.hdf_metadata import main

if __name__ == '__main__':
    main()
