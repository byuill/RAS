import requests

base = "https://cwms-data.usace.army.mil/cwms-data"
H = {"Accept": "application/json;version=2"}
for nm in ["Vicksburg.Elev.Inst.1Day.0.DCP-rev", "Vicksburg.Flow.Inst.1Day.0.DCP-rev"]:
    r = requests.get(base + "/timeseries", params={"name": nm, "office": "MVK", "begin": "2008-04-25T00:00:00Z", "end": "2008-05-02T00:00:00Z", "unit": "EN"}, headers=H, timeout=60)
    print(r.status_code, nm)
    print(r.text[:900])
r = requests.get(base + "/catalog/TIMESERIES", params={"office": "MVK", "like": "Vicksburg.*", "page-size": 60}, headers=H, timeout=60)
for e in r.json()["entries"]:
    print(e["name"], e["units"], e["extents"][0]["earliest-time"], e["extents"][0]["latest-time"])
try:
    r = requests.get(base + "/catalog/TIMESERIES", params={"office": "MVN", "like": ".*(Belle|Red River|Donaldson|Baton).*", "page-size": 60}, headers=H, timeout=60)
    print(r.status_code, r.text[:300])
    for e in r.json().get("entries", [])[:30]:
        print(e["name"], e["units"])
except Exception as e:
    print("MVN err", repr(e)[:200])
