import io
import requests
import pandas as pd

u = "https://www.waterqualitydata.us/data/Result/search"
for prof in ["narrowResult", "resultPhysChem"]:
    r = requests.get(u, params={"siteid": "USGS-07289000", "pCode": "80154;80155;70331;00061;00060;00065;00010", "startDateLo": "01-01-2000", "startDateHi": "12-31-2008",
                                "mimeType": "csv", "zip": "no", "dataProfile": prof}, timeout=120)
    print(prof, r.status_code, len(r.text))
    df = pd.read_csv(io.StringIO(r.text), low_memory=False)
    print(list(df.columns))
    print(df.head(4).T.to_string()[:3000])
    print(df["USGSPCode"].value_counts() if "USGSPCode" in df else "no USGSPCode")
    break

base = "https://cwms-data.usace.army.mil/cwms-data"
r = requests.get(base + "/timeseries", params={"name": "Vicksburg.Flow.Inst.1Day.0.DCP-rev", "office": "MVK", "begin": "2004-01-01T00:00:00Z", "end": "2013-01-02T00:00:00Z", "unit": "EN"},
                 headers={"Accept": "application/json;version=2"}, timeout=60)
j = r.json()
print({k: (v if k != "values" else len(v)) for k, v in j.items() if k not in ("value-columns", "vertical-datum-info")})
