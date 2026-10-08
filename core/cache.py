"""Small byte-bounded LRU for derived analysis objects."""
from collections import OrderedDict
from dataclasses import fields, is_dataclass
import numpy as np
import pandas as pd


def memory_bytes(value, seen=None):
    seen = set() if seen is None else seen
    if id(value) in seen:
        return 0
    seen.add(id(value))
    if isinstance(value, np.ndarray):
        return value.nbytes
    if isinstance(value, (pd.DataFrame,pd.Series)):
        usage = value.memory_usage(deep=True)
        return int(usage.sum() if hasattr(usage,'sum') else usage)
    if is_dataclass(value):
        return sum(memory_bytes(getattr(value,f.name),seen) for f in fields(value))
    if isinstance(value, dict):
        return sum(memory_bytes(v,seen) for v in value.values())
    if isinstance(value, (list,tuple)):
        return sum(memory_bytes(v,seen) for v in value)
    return 0


class BoundedCache:
    def __init__(self, cache_mb):
        if not np.isfinite(cache_mb) or cache_mb < 0:
            raise ValueError('Cache budget must be finite and nonnegative.')
        self.limit = int(cache_mb * 1024 * 1024)
        self.bytes = 0
        self.entries = OrderedDict()

    def get(self,key):
        if key not in self.entries:
            return None
        self.entries.move_to_end(key)
        return self.entries[key][0]

    def put(self,key,value):
        previous = self.entries.pop(key,None)
        if previous:
            self.bytes -= previous[1]
        size = memory_bytes(value)
        if size <= self.limit and self.limit > 0:
            while self.entries and self.bytes + size > self.limit:
                _, (_,old_size) = self.entries.popitem(last=False)
                self.bytes -= old_size
            self.entries[key] = (value,size)
            self.bytes += size
        return value

    def clear(self):
        self.entries.clear()
        self.bytes = 0
