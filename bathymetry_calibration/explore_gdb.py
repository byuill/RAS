"""Inventory geodatabase layers in a separately configured ArcGIS interpreter."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bathymetry_calibration.sources import arcpy_request


def explore_gdb(gdb_path, python_executable=None):
    return arcpy_request({'operation': 'inventory', 'gdb': str(gdb_path)}, python_executable)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gdb')
    parser.add_argument('--arcpy-python')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        inventory = json.dumps(explore_gdb(args.gdb, args.arcpy_python), indent=2)
        if args.output:
            args.output.write_text(inventory+'\n', encoding='utf-8')
        else:
            print(inventory)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'Geodatabase inventory failed: {exc}\n')


if __name__ == '__main__':
    main()
