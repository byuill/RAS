"""Launch the HEC-RAS sediment bathymetry calibration GUI workbench.

Usage:
    python launch_sed_calibration.py
"""
import os
import sys
from pathlib import Path

# Resolve base directories
script_dir = Path(__file__).resolve().parent

# Support running either from project root or inside Bathy_compare
if (script_dir / "Bathy_compare").is_dir():
    bathy_compare_dir = script_dir / "Bathy_compare"
    parent_dir = script_dir
else:
    bathy_compare_dir = script_dir
    parent_dir = script_dir.parent

for path_dir in (str(parent_dir), str(bathy_compare_dir)):
    if path_dir not in sys.path:
        sys.path.insert(0, path_dir)

# Find default configuration file
default_config = bathy_compare_dir / "real_config.json"
if not default_config.is_file():
    candidates = list(bathy_compare_dir.glob("*.json"))
    default_config = candidates[0] if candidates else None


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Launch HEC-RAS Bathymetry Calibration Workbench",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--config",
        default=str(default_config) if default_config else "",
        help="Path to configuration JSON file (pre-populated by default)",
    )
    parser.add_argument(
        "--hdf",
        default="",
        help="Path to HEC-RAS results HDF file (optional; defaults from config)",
    )
    parser.add_argument("--before-survey", default="", help="Baseline survey name (optional)")
    parser.add_argument("--after-survey", default="", help="Target survey name (optional)")
    parser.add_argument("--before-index", type=int, default=None, help="Baseline model output index (optional)")
    parser.add_argument("--after-index", type=int, default=None, help="Target model output index (optional)")
    args = parser.parse_args()

    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        sys.exit(
            "Error: PySide6 is not installed in this Python environment.\n"
            "Please run using your virtual environment:\n"
            r'  & "C:\Temp\bathy_env\Scripts\python.exe" launch_sed_calibration.py'
        )

    try:
        from Bathy_compare.gui import CalibrationWindow
    except ImportError:
        from gui import CalibrationWindow

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("HEC-RAS Bathymetry Calibration")

    window = CalibrationWindow(
        config_path=args.config,
        hdf_path=args.hdf,
        before_survey=args.before_survey or None,
        after_survey=args.after_survey or None,
        before_index=args.before_index,
        after_index=args.after_index,
    )
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
