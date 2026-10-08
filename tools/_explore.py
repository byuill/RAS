import re
import collections
import sys
import h5py

path = sys.argv[1]
f = h5py.File(path, "r")
base = "Results/Sediment/Output Blocks/"
for blk in f[base]:
    print("BLOCK", blk, {a: str(b)[:100] for a, b in f[base + blk].attrs.items()})
    for k in f[base + blk]:
        print("  child", k)
ts = f[base + "Sediment/Sediment Time Series"]
for k, o in ts.items():
    if isinstance(o, h5py.Dataset):
        print("TS", k, o.shape, o.dtype, {a: str(b)[:80] for a, b in o.attrs.items()})
    else:
        print("TSG", k, len(o), {a: str(b)[:80] for a, b in o.attrs.items()})
xs = ts["Cross Sections"]
names = collections.OrderedDict()
for k, o in xs.items():
    b = re.sub(r" \d+$", "", k)
    names.setdefault(b, []).append(k)
for b, l in names.items():
    print(len(l), b, xs[l[0]].shape, {a: str(x)[:60] for a, x in xs[l[0]].attrs.items()})
