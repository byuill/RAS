"""CLI wrapper for ras.hdf_discovery.dump_tree."""
import sys
from pathlib import Path
import h5py

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from ras.hdf_discovery import dump_tree

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python hdf_tree.py <path_to_hdf>")
        sys.exit(1)
        
    path = sys.argv[1]
    try:
        with h5py.File(path, "r") as f:
            dump_tree(f)
    except Exception as e:
        print(f"Error reading {path}: {e}")
