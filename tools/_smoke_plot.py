import sys
import os
from pathlib import Path
import pandas as pd
import numpy as np

# Add project root to path
sys.path.insert(0, str(Path(r"E:\LMR Comp Phase 2\Calibration_2004_2025\sediment_calibration\hecras_sediment_calibrator")))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from ras.hdf_reader import open_results
from analysis.model_data import ModelDataService
from sediment.rouse import RouseConfig
from plotting.styles import DisplayUnits, SeriesData, PinnedDataset
from plotting.timeseries import draw_timeseries, TimeSeriesRequest, draw_stacked_contribution
from plotting.rating_curve import draw_rating, RatingRequest

hdf_path = r"E:\LMR Comp Phase 2\Calibration_2004_2025\sediment_calibration\model_template_Ver2\R1_Dyn_SLR1.p01.hdf"

print(f"Opening {hdf_path}")
res = open_results(hdf_path)
svc = ModelDataService(res)
cfg = RouseConfig()

xs_index = 100
group_key = "total"
mf = svc.frame(xs_index, group_key, cfg)

from config.settings import AppSettings
du = DisplayUnits(AppSettings())

# 1. Time series Q+flux
req1 = TimeSeriesRequest(
    left=[SeriesData(mf.df.index, mf.df["Q"].values, "time", "discharge", "model")],
    right=[SeriesData(mf.df.index, mf.df["Flux"].values, "time", "mass_flux", "model")],
    left_name="Flow (cfs)", right_name="Flux (tons/day)", title="Time Series Test", subtitle="Subtitle"
)
fig1 = plt.figure(figsize=(10, 6))
info1 = draw_timeseries(fig1, req1, du)
fig1.savefig(r"E:\LMR Comp Phase 2\Calibration_2004_2025\sediment_calibration\hecras_sediment_calibrator\tools\smoke_test_timeseries.png")
print("Saved smoke_test_timeseries.png")

# 2. Rating curve loglog with fit
df_valid = mf.df[["Q", "Flux"]].dropna()
req2 = RatingRequest(
    x=df_valid["Q"].values, y=df_valid["Flux"].values,
    times=df_valid.index,
    x_quantity="discharge", y_quantity="mass_flux", x_name="Flow (cfs)", y_name="Flux (tons/day)",
    title="Rating Curve Test", subtitle="Subtitle", color_by="none", fit=True
)
fig2 = plt.figure(figsize=(8, 6))
draw_rating(fig2, req2, du)
fig2.savefig(r"E:\LMR Comp Phase 2\Calibration_2004_2025\sediment_calibration\hecras_sediment_calibrator\tools\smoke_test_rating_curve.png")
print("Saved smoke_test_rating_curve.png")

# 2.5 Color by month
req2_month = RatingRequest(
    x=df_valid["Q"].values, y=df_valid["Flux"].values,
    times=df_valid.index,
    x_quantity="discharge", y_quantity="mass_flux", x_name="Flow", y_name="Flux",
    title="Rating Curve Month", subtitle="", color_by="month", fit=True, categories=df_valid.index.month.values
)
fig2m = plt.figure(figsize=(8, 6))
draw_rating(fig2m, req2_month, du)
fig2m.savefig(r"E:\LMR Comp Phase 2\Calibration_2004_2025\sediment_calibration\hecras_sediment_calibrator\tools\smoke_test_rating_curve_month.png")
print("Saved smoke_test_rating_curve_month.png")

# 3. Stacked contribution
cff = svc.class_flux_frame(xs_index, cfg)
fig3 = plt.figure(figsize=(10, 6))
draw_stacked_contribution(fig3, cff, du, relative=False, title="Stacked Contribution", subtitle="")
fig3.savefig(r"E:\LMR Comp Phase 2\Calibration_2004_2025\sediment_calibration\hecras_sediment_calibrator\tools\smoke_test_stacked.png")
print("Saved smoke_test_stacked.png")

print("Smoke test done.")
