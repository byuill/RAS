import sys
import h5py
import numpy as np

f = h5py.File(sys.argv[1], "r")
a = f["Geometry/Cross Sections/Attributes"][:]
rv = [x.decode().strip() for x in a["River"]]
rc = [x.decode().strip() for x in a["Reach"]]
rs = [x.decode().strip() for x in a["RS"]]
prev = None
start = 0
for i, key in enumerate(zip(rv, rc)):
    if key != prev:
        if prev is not None:
            print(prev, start, i - 1, rs[start], "->", rs[i - 1])
        prev, start = key, i
print(prev, start, len(rs) - 1, rs[start], "->", rs[-1])
print("LMR stations sample:", [r for r, c in zip(rs, rc) if c == "LMR"][:15])
print("Root attrs:", dict(f.attrs))
print("Geometry attrs:", {k: str(v)[:200] for k, v in f["Geometry"].attrs.items()})
pl = f["Geometry/Cross Sections/Polyline Points"][:3]
print("poly pts", pl)
for k in f["Plan Data/Plan Information"].attrs:
    print("PI", k, str(f["Plan Data/Plan Information"].attrs[k])[:150])
print("Plan Info extra keys:", list(f["Plan Data/Plan Information"].attrs.keys()))
