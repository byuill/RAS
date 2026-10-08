import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import time
import numpy as np
from ras.hdf_reader import open_results
from ras.geo import haversine_km

t = time.time()
r = open_results(sys.argv[1])
i = r.info
print("open", round(time.time() - t, 2), "s", i.hec_version, i.units_system, i.plan_file, i.plan_name, i.sim_start, i.sim_end, i.n_steps)
print("warnings:", i.warnings)
print("classes:", [(c.name, c.d_rep_mm) for c in i.grain_classes][:8])
print("n vars", len(i.layout.variables), [ (k, v.units, len(v.class_paths)) for k, v in list(i.layout.variables.items())[:6]])
for st, lat, lon in [("Vicksburg", 32.31464, -90.90584), ("Natchez", 31.56044, -91.41872), ("Tarbert", 31.00851, -91.62373),
                     ("RedRiverLdg", 30.96101, -91.66456), ("StFrancisville", 30.75852, -91.39595), ("BatonRouge", 30.44567, -91.19156),
                     ("Donaldsonville", 30.10853, -90.98760), ("BelleChasse", 29.85715, -89.97785), ("Thebes", 37.22025, -89.46317), ("UnionPt", 31.21625, -91.62197)]:
    d = [haversine_km(lon, lat, x.lon, x.lat) if np.isfinite(x.lon) else 1e9 for x in i.xs]
    j = int(np.argmin(d))
    print(f"{st:15s} nearest {i.xs[j].label:35s} idx {j} dist {d[j]:.2f} km")
print("xs0", i.xs[0], i.xs[4], i.xs[-1])
t = time.time()
q = r.var_column("Flow", 145)
print("Flow col", q[:3], time.time() - t)
