import requests, sys

tests = {
    "site rdb": "https://waterservices.usgs.gov/nwis/site/?format=rdb&sites=07289000,07374000,07374525,07010000&siteOutput=expanded",
    "dv json": "https://waterservices.usgs.gov/nwis/dv/?format=json&sites=07289000&parameterCd=00060&startDT=2020-01-01&endDT=2020-01-05",
    "wqp": "https://www.waterqualitydata.us/data/Result/search?siteid=USGS-07289000&pCode=80154&mimeType=csv&zip=no&startDateLo=01-01-2004&startDateHi=01-31-2004",
    "ogc": "https://api.waterdata.usgs.gov/ogcapi/v0/collections/monitoring-locations/items?id=USGS-07289000&f=json",
}
for k, u in tests.items():
    try:
        r = requests.get(u, timeout=40)
        print(k, r.status_code, len(r.text))
        print(r.text[:1500].replace("\r", ""))
    except Exception as e:
        print(k, "ERR", repr(e)[:300])
    print("=" * 60)
