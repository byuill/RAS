import pandas as pd
import pytest

from core.exceptions import ObservationError
from observations.local_import import ColumnChoice, to_observation_set


def test_imported_multi_station_table_requires_one_sampling_location():
    table=pd.DataFrame({'date':['2004-01-01','2004-01-02'],'ssc':[100,200],
                        'site':['07290880','07374000']})
    mapping={'datetime':ColumnChoice('date',''),'ssc':ColumnChoice('ssc','mg/L'),
             'station':ColumnChoice('site','')}
    with pytest.raises(ObservationError,match='multiple sampling stations'):
        to_observation_set(table,mapping,'local','Imported sediment','archive')
    table['site']='07290880'
    obs=to_observation_set(table,mapping,'local','Imported sediment','archive')
    assert obs.df.sample_station_id.eq('07290880').all()
