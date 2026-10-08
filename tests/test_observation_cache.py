from concurrent.futures import ThreadPoolExecutor
import threading
import pandas as pd
import pytest
from observations.cache import ObservationCache
from core.exceptions import CacheError


def test_concurrent_cache_stores_keep_both_records_and_coverage(tmp_path):
    cache=ObservationCache(tmp_path);barrier=threading.Barrier(2)
    def store(day):
        stamp=pd.Timestamp(day)
        barrier.wait()
        cache.store('provider','station','flow',pd.DataFrame({'DateTime':[stamp],'value':[1.0]}),
                    stamp,stamp,units={'value':'cfs'})
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(store,['2004-01-01','2004-01-02']))
    lookup=cache.lookup('provider','station','flow','2004-01-01','2004-01-02')
    assert lookup.complete and len(lookup.df)==2
    assert lookup.meta.coverage==[['2004-01-01','2004-01-02']]


def test_changed_cache_units_refused_before_modifying_data(tmp_path):
    cache=ObservationCache(tmp_path)
    frame=pd.DataFrame({'DateTime':[pd.Timestamp('2004-01-01')],'value':[1.0]})
    cache.store('provider','station','flow',frame,'2004-01-01','2004-01-01',units={'value':'cfs'})
    with pytest.raises(CacheError,match='units changed'):
        cache.store('provider','station','flow',frame,'2004-01-01','2004-01-01',units={'value':'m3/s'})
    assert cache.read_meta('provider','station','flow').units=={'value':'cfs'}
    with pytest.raises(CacheError):cache.store('..','..','flow',frame,'2004-01-01','2004-01-01')


def test_parser_migration_resets_old_rows_and_old_coverage(tmp_path):
    cache=ObservationCache(tmp_path)
    old=pd.DataFrame({'DateTime':pd.to_datetime(['2004-01-01','2005-01-01']), 'value':[1.,2.]})
    cache.store('usgs_wqp','station','samples',old,'2004-01-01','2005-12-31',revision='old')
    current=pd.DataFrame({'DateTime':pd.to_datetime(['2004-01-01']), 'value':[3.]})
    cache.store('usgs_wqp','station','samples',current,'2004-01-01','2004-01-01',revision='new',reset=True)
    assert cache.lookup('usgs_wqp','station','samples','2004-01-01','2004-01-01').df.value.tolist()==[3.]
    later=cache.lookup('usgs_wqp','station','samples','2005-01-01','2005-01-01')
    assert not later.complete and later.df.empty
