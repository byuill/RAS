"""Shared portable paths for rebuilding the guide from a RAS checkout."""
from pathlib import Path
import os

SOURCE = Path(__file__).resolve().parent
REPO = SOURCE.parents[2]
if not (REPO / 'bathymetry_calibration' / 'core.py').is_file():
    raise RuntimeError('Keep user_guide_source inside the RAS checkout.')
ROOT = Path(os.environ.get('BATHY_GUIDE_OUTPUT', str(SOURCE / 'build'))).expanduser().resolve()
for directory in (ROOT, ROOT / 'qa', ROOT / 'figures'):
    directory.mkdir(parents=True, exist_ok=True)
