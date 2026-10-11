"""Inspect HDF layout/units without reading result arrays."""
from pathlib import Path
import sys

try:
    from .hdf_metadata import main
except ImportError:
    from hdf_metadata import main

if __name__ == '__main__':
    main()
