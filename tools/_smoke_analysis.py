import sys
import os
from pathlib import Path
import pandas as pd
import numpy as np

# Add project root to path
sys.path.insert(0, str(Path(r"E:\LMR Comp Phase 2\Calibration_2004_2025\sediment_calibration\hecras_sediment_calibrator")))

from analysis.rating_curve import fit_power_law
from analysis.hysteresis import classify_limbs, detect_events, event_hysteresis
from analysis.calibration_metrics import interpolate_model_to_times, filter_date_range, periodic_loads, cumulative_load
from ras.hdf_reader import open_results
from analysis.model_data import ModelDataService
from sediment.rouse import RouseConfig

def test_fit_power_law():
    print("\n--- test_fit_power_law ---")
    x = np.array([1, 10, 100])
    y = np.array([2.5, 250, 25000]) # y = 2.5 * x^2
    fit = fit_power_law(x, y)
    print(f"Expected a=2.5, b=2.0 | Got a={fit.a:.3f}, b={fit.b:.3f}")

def test_dates_loads():
    print("\n--- test_dates_loads ---")
    hdf_path = r"E:\LMR Comp Phase 2\Calibration_2004_2025\sediment_calibration\model_template_Ver2\R1_Dyn_SLR1.p01.hdf"
    res = open_results(hdf_path)
    svc = ModelDataService(res)
    cfg = RouseConfig()
    mf = svc.frame(100, "total", cfg)
    df = mf.df
    
    # filter_date_range
    filtered = filter_date_range(df, "2005-01-01", "2005-12-31")
    print(f"filter_date_range '2005': n={len(filtered)} steps, min={filtered.index.min()}, max={filtered.index.max()}")
    
    # cumulative_load
    cum, _ = cumulative_load(df["Flux"], df["dt_days"])
    # verify Mass Out Cum
    mass_out_cum = res.var_column("Mass Out Cum", 100)
    print(f"cumulative_load end value: {cum.iloc[-1]:.3e}")
    print(f"HEC-RAS Mass Out Cum end: {mass_out_cum[-1]:.3e}")
    
    # periodic_loads
    wy = periodic_loads(df["Flux"], df["dt_days"], "water_year")
    print(f"periodic_loads (water_year): {len(wy)} years")
    print(wy.head())
    
    # interpolate_model_to_times
    q_i = interpolate_model_to_times(df["Q"], pd.to_datetime(["2005-01-01 12:00", "2006-05-15 06:00"]))
    flux_i = interpolate_model_to_times(df["Flux"], pd.to_datetime(["2005-01-01 12:00", "2006-05-15 06:00"]))
    interp = pd.DataFrame({"Q": q_i, "Flux": flux_i})
    print(f"interpolate_model_to_times:\n{interp}")

def test_hysteresis():
    print("\n--- test_hysteresis ---")
    times = pd.date_range("2005-01-01", periods=100, freq="D")
    q = pd.Series(np.sin(np.linspace(0, 2*np.pi, 100)) * 500000 + 600000, index=times)
    limbs = classify_limbs(q)
    events = detect_events(q)
    print(f"classify_limbs counts: {pd.Series(limbs).value_counts().to_dict()}")
    print(f"detect_events: found {len(events)} events")
    if events:
        e1 = events[0]
        ev_q = q[e1["start"]:e1["end"]]
        c = event_hysteresis(ev_q, ev_q * 1.5)
        print(f"event_hysteresis stats for event 1: loop_area_norm={c.get('loop_area_norm', 0):.3f}")

if __name__ == "__main__":
    test_fit_power_law()
    test_dates_loads()
    test_hysteresis()
