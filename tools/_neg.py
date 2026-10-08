import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np
from ras.hdf_reader import open_results

r = open_results(sys.argv[1])
rs = [x.station for x in r.info.xs]
for st in ["437.1", "304.4", "229.9", "75"]:
    j = rs.index(st)
    Q = r.var_column("Flow", j)
    C = np.column_stack([r.var_column("Sediment Concentration", j, k) for k in range(1, 21)])
    tot = r.var_column("Sediment Concentration", j)
    qs = r.var_column("Sediment Discharge", j)
    print("==", st, "total conc neg frac", (tot < 0).mean(), "qs neg frac", (qs < 0).mean(), " sum(C) == total conc max abs diff:", np.abs(C.sum(axis=1) - tot).max())
    for k in range(20):
        c = C[1:, k]
        neg = c < 0
        print(f"  class {k+1:2d} neg_frac={neg.mean():.3f} min={c.min():10.4g} max={c.max():10.4g} mean={c.mean():10.4g}  mean_neg={c[neg].mean() if neg.any() else 0:10.4g}")
    # relation of negatives to Q?
    k = np.argmax((C[1:] < 0).mean(axis=0))
    neg = C[1:, k] < 0
    print("  worst class", k + 1, "Q median when neg", np.median(Q[1:][neg]), "when pos", np.median(Q[1:][~neg]))
    # dc neighbors
    print("  sample series class", k + 1, np.round(C[200:215, k], 3))
