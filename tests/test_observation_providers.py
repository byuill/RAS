import numpy as np
import pandas as pd
import pytest

from core.exceptions import ProviderError
from observations.station_catalog import Station
from observations.usgs import parse_wqp_samples
from observations.usgs_api import fetch_values
from observations.usace import UsaceCwmsProvider, discover_series
from observations.processing import build_observation_set


def station(**kwargs):
    return Station(id='USGS-07374000',site_no='07374000',name='Baton Rouge',short_name='Baton Rouge',agency='USGS',**kwargs)


class Response:
    status_code=200
    def __init__(self,payload):self.payload=payload
    def json(self):return self.payload


def test_wqp_converts_units_censoring_clocks_and_conflicting_results():
    rows=[]
    for code,value,unit,detect in [('80154','0.2','g/L','Below detection limit'),('00061','100','m3/s',''),
                                 ('80155','100','kg/s',''),('70331','75','%','')]:
        rows.append({'ActivityIdentifier':'sample1','ActivityStartDate':'2020-07-01','ActivityStartTime/Time':'18:00',
            'ActivityStartTime/TimeZoneCode':'UTC','USGSPCode':code,'ResultMeasureValue':value,
            'ResultMeasure/MeasureUnitCode':unit,'ResultDetectionConditionText':detect})
    parsed=parse_wqp_samples(pd.DataFrame(rows))
    assert parsed.DateTime.iloc[0]==pd.Timestamp('2020-07-01 13:00')
    assert parsed.ssc_mg_l.iloc[0]==200
    assert parsed.discharge_cfs.iloc[0]==pytest.approx(3531.466672)
    assert 'ssc_mg_l' in parsed.censored_fields.iloc[0]
    obs=build_observation_set(station(),{'usgs_wqp_samples':(parsed,{})})
    assert obs.df.sand_mg_l.iloc[0]==50 and 'fractions=derived' in obs.df.qualifier.iloc[0]
    assert 'ssc_mg_l' in obs.df.censored_fields.iloc[0]
    q_censored=pd.DataFrame(rows)
    q_censored.loc[q_censored.USGSPCode=='00061','ResultDetectionConditionText']='Below detection limit'
    assert 'discharge_m3s' in parse_wqp_samples(q_censored).censored_fields.iloc[0]
    duplicate=pd.concat([pd.DataFrame(rows),pd.DataFrame([dict(rows[0],ResultMeasureValue='5')])],ignore_index=True)
    parsed=parse_wqp_samples(duplicate)
    assert np.isnan(parsed.ssc_mg_l.iloc[0]) and 'conflicting' in parsed.qualifier.iloc[0]
    rows[0]['ResultMeasure/MeasureUnitCode']='cfs'
    with pytest.raises(ProviderError,match='incompatible'):parse_wqp_samples(pd.DataFrame(rows))


def test_modern_usgs_pagination_units_and_subdaily_clock(monkeypatch):
    import observations.usgs_api as api
    calls=[]
    def get(url,params=None):
        calls.append((url,params))
        page=2 if url.endswith('page2') else 1
        return Response({'features':[{'properties':{'monitoring_location_id':'USGS-07374000','parameter_code':'00060',
            'time':f'2020-01-0{page}T12:00:00Z','value':100*page,'unit_of_measure':'m3/s'}}],
            'links':[{'rel':'next','href':'page2'}] if page==1 else []})
    monkeypatch.setattr(api,'http_get',get)
    result=fetch_values(station(),'00060','cfs',pd.Timestamp('2020-01-01'),pd.Timestamp('2020-01-02'),daily=False)
    assert len(result.df)==2 and result.df.DateTime.iloc[0]==pd.Timestamp('2020-01-01 06:00')
    assert result.df.value.iloc[0]==pytest.approx(3531.466672)
    assert calls[0][1]['datetime'].startswith('2020-01-01T06:00')
    monkeypatch.setattr(api,'http_get',lambda *args:Response({'features':[{'properties':{'value':2,'date':'2020-01-01'}}]}))
    with pytest.raises(ProviderError,match='units'):fetch_values(station(),'00060','cfs',pd.Timestamp('2020-01-01'),pd.Timestamp('2020-01-02'))


def test_cwms_discovery_refuses_ambiguous_or_wrong_quantity_and_converts_clock(monkeypatch):
    import observations.usace as usace
    entries=[{'name':'Tarbert.Flow.Inst.1Day.0.rev','units':'cfs'}]
    monkeypatch.setattr(usace,'http_get',lambda *args,**kwargs:Response({'entries':entries}))
    assert discover_series('MVN','Tarbert.*Flow.*','flow',pd.Timestamp('2020-01-01'),pd.Timestamp('2020-01-02'))==entries[0]['name']
    entries.append({'name':'Tarbert.Flow.Inst.1Day.0.other','units':'cfs'})
    with pytest.raises(ProviderError,match='2 compatible'):discover_series('MVN','pattern','flow',pd.Timestamp('2020-01-01'),pd.Timestamp('2020-01-02'))
    calls=[]
    def get(url,params,headers,**kwargs):
        calls.append(params)
        return Response({'units':'mg/L','time-zone':'UTC','values':[[pd.Timestamp('2020-07-01 18:00',tz='UTC').value//1000000,200,0]]})
    monkeypatch.setattr(usace,'http_get',get)
    result=UsaceCwmsProvider().fetch(station(cwms={'office':'MVN','ssc':'configured.SSC.Inst.1Day.0.rev'}),
        'cwms_ssc',pd.Timestamp('2020-07-01'),pd.Timestamp('2020-07-02'))
    assert result.df.DateTime.iloc[0]==pd.Timestamp('2020-07-01 13:00')
    assert calls[0]['begin'].startswith('2020-07-01T05:00')
    obs=build_observation_set(station(),{'cwms_ssc':(result.df,result.units)})
    assert obs.df.ssc_mg_l.iloc[0]==200 and obs.df['kind'].iloc[0]=='cwms'
    with pytest.raises(ProviderError,match='incompatible'):UsaceCwmsProvider().fetch(station(cwms={'office':'MVN','flow':'wrong'}),
        'cwms_flow',pd.Timestamp('2020-07-01'),pd.Timestamp('2020-07-02'))


def test_subdaily_provider_mixed_modern_legacy_windows_preserve_dates_and_provenance(monkeypatch):
    import observations.usgs_api as api
    import observations.usgs_instantaneous as iv
    from observations.providers import FetchResult
    def modern(station,code,unit,start,end,daily=False):
        if start.month==2:raise ProviderError('Modern endpoint unavailable')
        return FetchResult(pd.DataFrame({'DateTime':[pd.Timestamp('2004-01-01 12:00')],
            'value':[100.],'qualifier':['A'],'agency':['USGS']}),{'value':'cfs'},api.API+'/continuous/items')
    monkeypatch.setattr(api,'fetch_values',modern)
    monkeypatch.setattr(iv,'http_get',lambda *args:Response({'value':{'timeSeries':[{'variable':{
        'unit':{'unitCode':'cfs'},'noDataValue':-999999},'values':[{'value':[{'dateTime':'2004-02-01T12:00:00-06:00',
            'value':'200','qualifiers':['P']}]}]}]}}))
    result=iv.UsgsInstantaneousProvider().fetch(station(),'usgs_iv_discharge',pd.Timestamp('2004-01-01'),pd.Timestamp('2004-02-02'))
    assert result.df.DateTime.tolist()==[pd.Timestamp('2004-01-01 12:00'),pd.Timestamp('2004-02-01 12:00')]
    assert result.df.value.tolist()==[100,200]
    assert api.API in result.endpoint and iv.NWIS_IV in result.endpoint
