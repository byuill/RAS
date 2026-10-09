import h5py
import sys

def print_structure(name, obj):
    print(name)
    if isinstance(obj, h5py.Dataset):
        print(f"  Shape: {obj.shape}, Type: {obj.dtype}")

def main():
    hdf_path = sys.argv[1]
    with h5py.File(hdf_path, 'r') as h5:
        print("Groups in Results/Sediment:")
        try:
            h5['Results/Sediment'].visititems(print_structure)
        except KeyError:
            print("No Results/Sediment")
        
        print("\nGroups in Results/Unsteady/Output:")
        try:
            h5['Results/Unsteady/Output'].visititems(print_structure)
        except KeyError:
            print("No Results/Unsteady/Output")

if __name__ == '__main__':
    main()
