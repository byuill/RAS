import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import logging
import tempfile
import time
import pandas as pd
from observations.cache import ObservationCache
from observations.service import ObservationService
from observations.station_catalog import StationCatalog

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
cat = StationCatalog.load()
print(len(cat), [s.short_name for s in cat.all()])
root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp())
cache = ObservationCache(root)
svc = ObservationService(cat, cache)
for sid in ["USGS-07289000", "USGS-07374000", "USGS-07374525"]:
    st = cat.get(sid)
    t = time.time()
    obs, rep = svc.load(st, "2004-01-01", "2013-01-01", progress=print)
    print(f"== {st.short_name}  {time.time()-t:.1f}s  rows={obs.n_records}  vars={obs.available_variables()}")
    for l in rep.lines():
        print("   ", l)
    print("   notes", obs.notes, obs.derivations)
    t = time.time()
    obs2, rep2 = svc.load(st, "2004-01-01", "2013-01-01")
    print(f"   second load {time.time()-t:.2f}s all_from_cache={rep2.all_from_cache}")
    if obs.n_records:
        print(obs.df.dropna(axis=1, how="all").head(3).T)
