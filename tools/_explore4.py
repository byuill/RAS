import sys
import time
import h5py
import numpy as np

f = h5py.File(sys.argv[1], "r")
xs = f["Results/Sediment/Output Blocks/Sediment/Sediment Time Series/Cross Sections"]
t0 = time.time()
names = ["Flow", "Velocity", "Shear Stress", "Shear Velocity", "Water Surface", "Sediment Discharge", "Sediment Concentration", "Temperature", "Rouse #", "Fall Velocity", "Mass Out Cum", "Vol Out", "Vol Out Cum", "Vol Capacity"]
idx = 4 + [r for r in range(281)][0]
a = f["Geometry/Cross Sections/Attributes"][:]
rs = [x.decode().strip() for x in a["RS"]]
i437 = rs.index("437.1")
print("index of 437.1:", i437)
d = {}
for n in names:
    if n in xs:
        d[n] = xs[n][:, :]
        x = d[n]
        print(f"{n:25s} shape={x.shape} nan={np.isnan(x).sum()} min={np.nanmin(x):.4g} max={np.nanmax(x):.4g} col437 mean={np.nanmean(x[:, i437]):.5g} first3={x[:3, i437]}")
    else:
        print("MISSING", n)
print("load time", time.time() - t0)
for n in ("Sediment Concentration", "Rouse #", "Fall Velocity", "Mass Out Cum", "Vol Out", "Vol Out Cum", "Vol Capacity"):
    print(n, {k: str(v) for k, v in xs[n].attrs.items() if k in ("Grain Class", "Units")})
C = np.stack([xs[f"Sediment Concentration {k}"][:, i437] for k in range(1, 21)], axis=1)
Q = d["Flow"][:, i437]
print("Conc total (base) col:", d["Sediment Concentration"][:5, i437], " sum of classes:", C.sum(axis=1)[:5])
print("Qs total (tons/day):", d["Sediment Discharge"][:5, i437])
print("Sum C*Q*0.0027:", (C.sum(axis=1) * Q * 0.0027)[:5], "ratio to Qs:", ((C.sum(axis=1) * Q * 0.0027) / d["Sediment Discharge"][:, i437])[:5])
r = (d["Sediment Concentration"][:, i437] * Q * 0.0027) / d["Sediment Discharge"][:, i437]
print("ratio via base conc: median", np.nanmedian(r), "min", np.nanmin(r), "max", np.nanmax(r))
r2 = (C.sum(axis=1) * Q * 0.0027) / d["Sediment Discharge"][:, i437]
print("ratio via sum: median", np.nanmedian(r2), "p5", np.nanpercentile(r2, 5), "p95", np.nanpercentile(r2, 95))
print("per-class conc means:", np.round(C.mean(axis=0), 3))
Ro = np.stack([xs[f"Rouse # {k}"][:, i437] for k in range(1, 21)], axis=1)
print("Rouse mean per class:", np.round(np.nanmean(Ro, axis=0), 3))
Fv = np.stack([xs[f"Fall Velocity {k}"][:, i437] for k in range(1, 21)], axis=1)
print("Fall vel ft/s mean per class:", np.round(np.nanmean(Fv, axis=0), 5))
print("Rouse check: ws/(0.4 u*) vs reported:", np.nanmean(Fv[:, 7] / (0.4 * d["Shear Velocity"][:, i437])), np.nanmean(Ro[:, 7]))
print("tau/(rho): u* check:", np.nanmean(np.sqrt(d["Shear Stress"][:, i437] / 1.94)), np.nanmean(d["Shear Velocity"][:, i437]))
print("Temp sample", d["Temperature"][:3, i437])
print("Mass Out Cum", d["Mass Out Cum"][:3, i437], d["Mass Out Cum"][-1, i437])
print("Vol Out cls8", xs["Vol Out 8"][:3, i437], xs["Vol Out Cum 8"][-1, i437])
