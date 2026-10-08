import requests

base = "https://cwms-data.usace.army.mil/cwms-data"
tests = [
    base + "/catalog/TIMESERIES?office=MVK&like=Vicksburg.*&page-size=20",
    base + "/catalog/TIMESERIES?office=MVN&like=Belle%20Chasse.*&page-size=20",
    base + "/catalog/TIMESERIES?office=MVK&like=Natchez.*Stage.*&page-size=20",
    base + "/catalog/TIMESERIES?office=MVN&like=Red%20River%20Landing.*&page-size=20",
]
for u in tests:
    try:
        r = requests.get(u, headers={"Accept": "application/json;version=2"}, timeout=40)
        print(r.status_code, u)
        print(r.text[:1200])
    except Exception as e:
        print("ERR", u, repr(e)[:200])
    print("-" * 60)
