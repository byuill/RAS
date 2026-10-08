import io
import requests
import pandas as pd

url = "https://waterservices.usgs.gov/nwis/site/"
frames = []
for bbox in ["-92.2,30.9,-90.0,32.0", "-92.2,29.3,-89.5,31.0", "-91.5,32.0,-90.5,33.5", "-90.5,33.5,-89.0,36.5", "-91.0,36.5,-89.0,38.9"]:
    r = requests.get(url, params={"format": "rdb", "bBox": bbox, "siteType": "ST", "siteOutput": "expanded", "siteStatus": "all"}, timeout=90)
    if r.status_code != 200:
        print("bbox fail", bbox, r.status_code)
        continue
    lines = [l for l in r.text.splitlines() if not l.startswith("#")]
    frames.append(pd.read_csv(io.StringIO("\n".join(lines)), sep="\t", dtype=str).iloc[1:])
df = pd.concat(frames).drop_duplicates("site_no")
m = df[df["station_nm"].str.contains("MISSISSIPPI R", case=False, na=False)]
print(m[["site_no", "station_nm", "dec_lat_va", "dec_long_va", "alt_va", "alt_datum_cd"]].to_string())
