"""Verify the guide's numerical examples using the authoritative calculation engine.

Run from the RAS checkout with its scientific environment, for example:
  python bathymetry_calibration/docs/user_guide_source/verify_guide_examples.py
All fixture inputs enter the package in canonical SI units. Assertions compare
the returned engine quantities in the guide's international-foot / cubic-yard
presentation units. No source data, figures, or tracked files are modified.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

from guide_paths import REPO, ROOT
sys.path.insert(0, str(REPO))

from bathymetry_calibration.core import compare_profiles
from bathymetry_calibration.calculation_audit import (
    run_sensitivity, support_signature, volume_uncertainty,
)
from bathymetry_calibration.display_units import (
    FT_PER_M, FT2_PER_M2, YD3_PER_M3,
)

FT = 0.3048
REPORT = ROOT / "qa" / "guide_example_verification.json"


def fixture(changes_ft, *, stations_ft=(0.0, 100.0), lengths_ft=None,
            model_changes_ft=None, method="average_end_area", spacing_ft=10.0):
    """Build minimal reviewed profiles; changes can be scalars or knot vectors."""
    n = len(changes_ft)
    lengths = np.asarray(lengths_ft if lengths_ft is not None else [1000.0]*(n-1), float)
    if len(lengths) != n-1:
        raise ValueError("One verified reach length is required between each pair of XS.")
    stations = np.asarray(stations_ft, float)
    chainage = np.r_[0.0, lengths.cumsum()]
    manifest, baseline, observed, model = [], [], [], []
    if model_changes_ft is None:
        model_changes_ft = changes_ft
    for i, (obs, mod) in enumerate(zip(changes_ft, model_changes_ft)):
        xs = chr(ord("A")+i)
        obs = np.broadcast_to(np.asarray(obs, float), stations.shape)
        mod = np.broadcast_to(np.asarray(mod, float), stations.shape)
        for j, u in enumerate(stations):
            manifest.append(dict(xs_id=xs, model_column=i, chainage_m=chainage[i]*FT,
                length_to_next_m=lengths[i]*FT if i < n-1 else np.nan,
                u_m=u*FT, x_m=u*FT, y_m=-chainage[i]*FT))
            base = dict(xs_id=xs, u_m=u*FT, z_m=0.0)
            baseline.append(base)
            observed.append(dict(base, z_m=obs[j]*FT))
            model.append(dict(base, z_m=mod[j]*FT))
    return compare_profiles(pd.DataFrame(manifest), pd.DataFrame(baseline),
        pd.DataFrame(model), pd.DataFrame(baseline), pd.DataFrame(observed),
        max_gap_m=(stations[-1]-stations[0]+1.0)*FT, min_coverage=1.0,
        grid_spacing_m=spacing_ft*FT, longitudinal_method=method)


def close(actual, expected, *, atol=1e-8):
    np.testing.assert_allclose(actual, expected, rtol=1e-10, atol=atol)


def verify_cancellation():
    result = fixture([[-3, 3, -3], [-3, 3, -3]], stations_ft=[0, 50, 100])
    s = result.sections
    close(s.observed_signed_area_m2*FT2_PER_M2, [0, 0])
    close(s.observed_deposition_area_m2*FT2_PER_M2, [75, 75])
    close(s.observed_erosion_area_m2*FT2_PER_M2, [75, 75])
    close(s.observed_lateral_std_m*FT_PER_M, [np.sqrt(3)]*2)
    close(s.observed_second_moment_m3*FT_PER_M**3, [300, 300])
    close(s.observed_cancellation_fraction, [1, 1])
    close(result.metrics["observed_gross_turnover_m3"]*YD3_PER_M3, 150000/27)
    flat = fixture([0, 0])
    assert flat.sections.observed_cancellation_fraction.isna().all()
    assert flat.metrics["observed_cancellation_fraction"] is None
    close(flat.metrics["observed_gross_turnover_m3"], 0)
    return dict(net_area_ft2=0.0, deposition_area_ft2=75.0, erosion_area_ft2=75.0,
        gross_area_ft2=150.0, lateral_std_ft=np.sqrt(3), second_moment_ft3=300.0,
        cancellation_fraction=1.0, flat_cancellation=None)


def verify_endpoint_methods():
    values = {}
    for method, expected in [("upstream", 1000), ("average_end_area", 2000), ("downstream", 3000)]:
        result = fixture([0.27, 0.81], method=method)
        close(result.metrics["observed_total_m3"]*YD3_PER_M3, expected)
        close(result.sections.observed_cumulative_m3.iloc[-1]*YD3_PER_M3, expected)
        close(result.sections.observed_interval_prefix_m3.iloc[-1]*YD3_PER_M3, expected)
        values[method] = float(result.metrics["observed_total_m3"]*YD3_PER_M3)
    return values


def verify_disconnected_segments():
    result = fixture([0.27, 0.27, np.nan, 0.54, 0.54])
    assert result.sections.xs_id.tolist() == ["A", "B", "D", "E"]
    assert result.sections.segment_id.tolist() == [0, 0, 1, 1]
    assert result.intervals.upstream_xs.tolist() == ["A", "D"]
    assert result.intervals.downstream_xs.tolist() == ["B", "E"]
    assert "C" in result.excluded.xs_id.tolist()
    close(result.sections.observed_cumulative_m3*YD3_PER_M3, [500, 1000, 1000, 2000])
    close(result.sections.observed_interval_prefix_m3*YD3_PER_M3, [0, 1000, 0, 2000])
    close(result.intervals.observed_volume_change_m3*YD3_PER_M3, [1000, 2000])
    close(result.metrics["observed_total_m3"]*YD3_PER_M3, 3000)
    return dict(node_cumulative_yd3=[500, 1000, 1000, 2000],
        completed_reach_prefix_yd3=[0, 1000, 0, 2000],
        segment_totals_yd3=[1000, 2000], all_supported_total_yd3=3000,
        final_plotted_node_yd3=2000, unsupported_xs="C")


def uncertainty_customary(value):
    return {k.replace("_m3", "_yd3"): (v*YD3_PER_M3 if k.endswith("_m3") and v is not None else v)
            for k, v in value.items() if k.endswith("_m3") or k=="bias_exceeds_survey_error_95"}


def verify_uncertainty_and_shift():
    result = fixture([0, 0, 0], model_changes_ft=[0.405]*3)
    close(result.sections.effective_width_m*FT_PER_M, [100]*3)
    close(result.sections.control_length_m*FT_PER_M, [500, 1000, 500])
    close(result.metrics["sampled_bed_area_m2"]*FT2_PER_M2, 200000)
    close(result.metrics["total_bias_m3"]*YD3_PER_M3, 3000)
    values = {}
    for rho, sigma, lower, upper in [
        (0, 1283.0005981991685, 485.3188275296297, 5514.68117247037),
        (1, 2095.131203515696, -1106.457158890764, 7106.457158890764),
    ]:
        error = volume_uncertainty(result, before_sigma_m=0.2*FT, after_sigma_m=0.2*FT,
                                  temporal_correlation=0, spatial_correlation=rho)
        close(error["change_sigma_m"]*FT_PER_M, np.sqrt(0.2**2+0.2**2))
        close(error["observed_volume_sigma_m3"]*YD3_PER_M3, sigma)
        close(error["bias_lower_95_m3"]*YD3_PER_M3, lower)
        close(error["bias_upper_95_m3"]*YD3_PER_M3, upper)
        assert error["bias_exceeds_survey_error_95"] is (rho==0)
        values[f"spatial_correlation_{rho}"] = uncertainty_customary(error)
    absent = volume_uncertainty(result)
    assert absent["observed_volume_sigma_m3"] is None
    assert absent["bias_exceeds_survey_error_95"] is None
    zero_change = volume_uncertainty(result, before_sigma_m=0.2*FT, after_sigma_m=0.2*FT,
                                    temporal_correlation=1, spatial_correlation=1)
    close(zero_change["observed_volume_sigma_m3"], 0)
    close(zero_change["bias_lower_95_m3"]*YD3_PER_M3, 3000)
    assert zero_change["bias_exceeds_survey_error_95"] is None
    sensitivity = run_sensitivity(result, [dict(name="Target +0.1 ft",
                                    overrides=dict(observed_target_shift_m=0.1*FT))])
    shifted = sensitivity.scenarios[0][1]
    close(shifted.metrics["observed_total_m3"]*YD3_PER_M3, 20000/27)
    close((shifted.metrics["total_bias_m3"]-result.metrics["total_bias_m3"])*YD3_PER_M3,
          -20000/27)
    assert sensitivity.summary.support_changed.tolist() == [False, False]
    values.update(sampled_bed_area_ft2=200000.0, bias_yd3=3000.0,
                  uniform_target_shift_ft=0.1, observed_shift_delta_yd3=20000/27,
                  bias_shift_delta_yd3=-20000/27, no_error_declared_significance=None,
                  zero_change_error_significance=None)
    return values


def verify_grid():
    change = [0, 0, 3, 0, 0]
    stations = [0, 8, 10, 12, 20]
    coarse = fixture([change]*2, stations_ft=stations, spacing_ft=5)
    fine = fixture([change]*2, stations_ft=stations, spacing_ft=2)
    for result in [coarse, fine]:
        close(result.sections.observed_area_change_m2*FT2_PER_M2, [6]*2)
        close(result.sections.effective_width_m*FT_PER_M, [20]*2)
        for xs, group in result.profiles.groupby("xs_id"):
            for knot in stations:
                assert np.isclose(group.u_m.to_numpy(), knot*FT, rtol=0, atol=1e-12).any(), (xs, knot)
    assert support_signature(coarse) == support_signature(fine)
    close(coarse.metrics["observed_total_m3"], fine.metrics["observed_total_m3"])
    close(coarse.metrics["observed_gross_turnover_m3"], fine.metrics["observed_gross_turnover_m3"])
    close(coarse.metrics["observed_spatial_std_change_m"], fine.metrics["observed_spatial_std_change_m"])
    return dict(source_knots_ft=stations, coarse_added_spacing_ft=5, fine_added_spacing_ft=2,
                exact_area_ft2=6.0, support_equal=True,
                coarse_profile_rows=len(coarse.profiles), fine_profile_rows=len(fine.profiles))


def main():
    report = dict(status="PASS", engine="bathymetry_calibration/core.py and calculation_audit.py",
        unit_basis="Canonical SI inputs; international foot and cubic yard comparisons",
        opposing_lateral_change=verify_cancellation(),
        endpoint_methods_yd3=verify_endpoint_methods(),
        disconnected_segments=verify_disconnected_segments(),
        conditional_uncertainty_and_shift=verify_uncertainty_and_shift(),
        preserved_source_knots=verify_grid())
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2)+"\n")
    print(f"PASS: Five guide example groups verified with the authoritative engine.\n{REPORT}")


if __name__ == "__main__":
    main()
