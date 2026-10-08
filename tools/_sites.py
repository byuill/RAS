import io
import sys
import requests
import pandas as pd

url = "https://waterservices.usgs.gov/nwis/site/"


def rdb(params):
    r = requests.get(url, params=params, timeout=60)
    if r.status_code != 200:
        return None
    lines = [l for l in r.text.splitlines() if not l.startswith("#")]
    return pd.read_csv(io.StringIO("\n".join(lines)), sep="\t", dtype=str).iloc[1:]


for s in sys.argv[1].split(","):
    d = rdb({"format": "rdb", "sites": s, "siteOutput": "expanded", "siteStatus": "all"})
    if d is None or d.empty:
        print(s, "NOT FOUND")
        continue
    row = d.iloc[0]
    print(s, "|", row["station_nm"], "|", row["dec_lat_va"], row["dec_long_va"], "| alt", row["alt_va"], row["alt_datum_cd"], "| DA", row.get("drain_area_va"))
    c = rdb({"format": "rdb", "sites": s, "seriesCatalogOutput": "true", "siteStatus": "all"})
    if c is not None and not c.empty:
        c = c[c["parm_cd"].isin(["00060", "00065", "80154", "80155", "70331", "70333", "00010", "63680", "99409", "99408", "00061", "80225"])]
        for _, x in c.sort_values(["parm_cd", "data_type_cd"]).iterrows():
            print("    ", x["parm_cd"], x["data_type_cd"], x["stat_cd"], x["begin_date"], x["end_date"], x["count_nu"])
