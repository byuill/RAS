import sys
import h5py
import numpy as np

f = h5py.File(sys.argv[1], "r")
xs = f["Results/Sediment/Output Blocks/Sediment/Sediment Time Series/Cross Sections"]
a = f["Geometry/Cross Sections/Attributes"][:]
rs = [x.decode().strip() for x in a["RS"]]
uw = f["Sediment/Grain Class Data/Density Data"][:, 2]
sg = f["Sediment/Grain Class Data/Density Data"][:, 0]
por = f["Sediment/Grain Class Data/Density Data"][:, 1]
Q = xs["Flow"][:, :].astype(np.float64)
Qs = xs["Sediment Discharge"][:, :].astype(np.float64)
Ct = xs["Sediment Concentration"][:, :].astype(np.float64)
C = np.stack([xs[f"Sediment Concentration {k}"][:, :] for k in range(1, 21)], axis=0).astype(np.float64)
V = np.stack([xs[f"Vol Out {k}"][:, :] for k in range(1, 21)], axis=0).astype(np.float64)
Vt = xs["Vol Out"][:, :].astype(np.float64)
K = 28.316846592 * 86400.0 / 1e6 / 0.90718474  # (mg/L * cfs) -> short tons/day
print("exact factor mg/L*cfs -> short tons/day:", K)
for rsn in ["437.1", "433.5", "316.8", "304.4", "229.9", "75", "-9.7"]:
    if rsn not in rs:
        print("no", rsn)
        continue
    i = rs.index(rsn)
    m = Qs[1:, i] > 1000
    r_sum = (C[:, 1:, i].sum(axis=0) * Q[1:, i] * K)[m] / Qs[1:, i][m]
    r_tot = (Ct[1:, i] * Q[1:, i] * K)[m] / Qs[1:, i][m]
    m3 = (V[:, 1:, i] * uw[:, None] / 2000.0).sum(axis=0)[m] / Qs[1:, i][m]
    m4 = (V[:, 1:, i] * (sg[:, None] * 62.4 * (1 - por[:, None])) / 2000.0).sum(axis=0)[m] / Qs[1:, i][m]
    print(rsn, "n", m.sum(), "C*Q*K/Qs med %.5f p5 %.5f p95 %.5f" % (np.median(r_sum), np.percentile(r_sum, 5), np.percentile(r_sum, 95)),
          "| Ct/Qs med %.5f" % np.median(r_tot),
          "| VolOut*UW/2000/Qs med %.4f p5 %.4f p95 %.4f" % (np.median(m3), np.percentile(m3, 5), np.percentile(m3, 95)),
          "| VolOut*sg*62.4*(1-n) med %.4f" % np.median(m4))
# sand fraction of flux, by method
i = rs.index("437.1")
sand = slice(5, 20)
fs_c = (C[sand, 1:, i].sum(axis=0) / np.maximum(C[:, 1:, i].sum(axis=0), 1e-9))
fs_v = (V[sand, 1:, i] * uw[sand, None]).sum(axis=0) / np.maximum((V[:, 1:, i] * uw[:, None]).sum(axis=0), 1e-9)
print("sand fraction at 437.1: by conc median %.3f ; by VolOut*UW median %.3f" % (np.median(fs_c), np.median(fs_v)))
print("Vol Out total vs sum classes:", np.median(Vt[1:, i] / V[:, 1:, i].sum(axis=0)))
print("Mass Out Cum last/ sum Qs:", xs["Mass Out Cum"][-1, i], Qs[:, i].sum())
bad = (C < 0).sum(), (Qs < 0).sum(), (Ct < -1e3).sum()
print("neg counts C, Qs, Ct<-1e3:", bad)
cols = np.where((Ct < -1e3).any(axis=0))[0]
print("cols with huge neg conc:", cols[:20], [rs[c] for c in cols[:10]])
print("zero-Q cols (min Q<1):", [rs[c] for c in np.where(Q[1:].min(axis=0) < 1)[0]][:10])
