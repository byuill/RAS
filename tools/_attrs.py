import sys
import h5py
f = h5py.File(sys.argv[1], "r")
xs = f["Results/Sediment/Output Blocks/Sediment/Sediment Time Series/Cross Sections"]
for n in ["Sediment Concentration", "Sediment Concentration 1", "Sediment Concentration 8", "Vol Out 3", "Rouse # 4", "Fall Velocity 4"]:
    print(n, {k: str(v)[:60] for k, v in xs[n].attrs.items()})
