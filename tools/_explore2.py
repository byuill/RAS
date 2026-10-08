import sys
import h5py
import numpy as np

f = h5py.File(sys.argv[1], "r")
base = "Results/Sediment/Output Blocks/"
se = f[base + "Sediment SE/Sediment Time Series"]
print("SE children:", len(se), list(se.keys())[:10])
for k, o in se.items():
    if isinstance(o, h5py.Group):
        names = list(o.keys())
        print("SE group", k, len(names), names[:6])
    else:
        print("SE ds", k, o.shape)

ts = f[base + "Sediment/Sediment Time Series"]
print("Stamp:", ts["Time Date Stamp"][:3], ts["Time Date Stamp"][-2:])
print("Time:", ts["Time"][:5], ts["Time"][-3:])
for g in ("Plan Data/Plan Information", "Plan Data/Plan Parameters", "Plan Data/Sediment/Sediment Run Parameters"):
    print(g, {a: str(b)[:120] for a, b in f[g].attrs.items()})
print("Plan Data keys", list(f["Plan Data"].keys()))
print("Custom vars:", [x.decode() for x in f["Plan Data/Sediment/Output Parameters/Custom Variables"][:]])

gi = f["Results/Sediment/Geometry Info"]
a = gi["Cross Section Attributes"][:]
print("XS attrs first/last:", a[:3], a[-3:])
print("XS Only first:", gi["Cross Section Only"][:3], gi["Cross Section Only"][-3:])
print("Node info first:", gi["Node Info"][:4])
sg = f["Sediment/Grain Class Data"]
for k in sg:
    print(k, sg[k][:], {a: str(b)[:80] for a, b in sg[k].attrs.items()})
print("Geometry XS attr:", f["Geometry/Cross Sections/Attributes"][:2][["River", "Reach", "RS", "Name"]])
print("Event Sediment grains:", f["Event Conditions/Sediment/Grain Class Names"][:])
