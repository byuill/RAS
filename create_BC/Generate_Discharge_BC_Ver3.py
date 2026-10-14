"""Compatible launcher for the audited boundary-condition workbench.

Run this file to open the GUI, or add --headless (and optionally --dss) for
noninteractive exports. The original implementation is retained in legacy/ for
review; calculation is now shared by the desktop and command-line workflows.
"""
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from create_BC.__main__ import main


if __name__ == '__main__':
    raise SystemExit(main())
