import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import time
import numpy as np
import pandas as pd
from ras.hdf_reader import open_results
from analysis.model_data import ModelDataService
from sediment.rouse import RouseConfig
from sediment.units import convert, sediment_conversion_factor

print("factor", sediment_conversion_factor())
r = open_results(sys.argv[1])
svc = ModelDataService(r)
cfg = RouseConfig()
for rs in ["437.1", "229.9", "75", "-19.6"]:
    j = [x.station for x in r.info.xs].index(rs)
    t = time.time()
    out = {}
    for g in ["total", "sand", "fines", "class:7", "suspended_est", "bedload_est", "rouse_mixed"]:
        mf = svc.frame(j, g, cfg)
        f = convert(mf.df["Flux"].values, "kg/s", "tons/day")
        out[g] = np.nanmean(f)
    mf = svc.frame(j, "total", cfg)
    print(rs, "t=%.2fs" % (time.time() - t), {k: round(v, 1) for k, v in out.items()})
    print("   sand+fines-total:", out["sand"] + out["fines"] - out["total"], " susp+bed-total:", out["suspended_est"] + out["bedload_est"] - out["total"])
    print("   integrity", mf.meta["integrity"])
    print("   warnings", mf.meta["warnings"])
    print("   conc check", np.nanmax(np.abs(svc.concentration_from_flux_check(mf) - mf.df["Conc"].values)))
mf = svc.frame(145, "total", cfg)
print(mf.df.head(3).T)
print(mf.meta["provenance"])
print(svc.rouse_table(145, cfg).to_string())
print("computed rouse vs HEC-RAS (class 8):")
cfg2 = RouseConfig(source="computed")
tr = svc.transport(145, cfg2)
tr1 = svc.transport(145, cfg)
print(np.nanmedian(tr.rouse[:, 7]), np.nanmedian(tr1.rouse[:, 7]), np.nanmedian(tr.rouse[:, 5]), np.nanmedian(tr1.rouse[:, 5]), np.nanmedian(tr.rouse[:, 2]), np.nanmedian(tr1.rouse[:, 2]))
