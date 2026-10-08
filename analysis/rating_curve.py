"""Rating-curve regression.

Origin of reused logic
----------------------
``fit_rating_curve_legacy`` and ``_r_squared`` are refactored from
``Sediment Boundary Conditions/SedRatingCurve/sed_rating/analysis.py`` (``fit_rating_curve``): power law
fitted by ordinary least squares in log-log space (``np.polyfit`` on ln x, ln y), linear,
logarithmic and exponential alternatives, R^2 reported in log space (and linear space for the power
law).  The numerical method is unchanged.  ``fit_power_law`` adds confidence intervals and
residual metrics on top of the same regression; ``fit_loglog_poly`` implements the log-quadratic
form used in the "advanced" rating-curve reports (ln C = a0 + a1 ln q* + a2 (ln q*)^2, q* = Q/Qref).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import stats


@dataclass
class DropReport:
    """Why points are not drawn / fitted (so removal is never silent)."""
    n_total: int = 0
    n_nan: int = 0
    n_nonpositive_x: int = 0
    n_nonpositive_y: int = 0
    n_used: int = 0

    def text(self) -> str:
        if self.n_total == self.n_used:
            return f"n={self.n_used}"
        parts = [f"{self.n_used}/{self.n_total} plotted"]
        if self.n_nan:
            parts.append(f"{self.n_nan} missing")
        if self.n_nonpositive_x:
            parts.append(f"{self.n_nonpositive_x} x\u22640 omitted (log x)")
        if self.n_nonpositive_y:
            parts.append(f"{self.n_nonpositive_y} y\u22640 omitted (log y)")
        return ", ".join(parts)


def valid_xy(x, y, log_x: bool = False, log_y: bool = False) -> tuple[np.ndarray, DropReport]:
    """Boolean mask of usable points for the chosen axis scaling, with a drop report."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    finite = np.isfinite(x) & np.isfinite(y)
    mask = finite.copy()
    rep = DropReport(n_total=len(x), n_nan=int((~finite).sum()))
    if log_x:
        bad = finite & ~(x > 0)
        rep.n_nonpositive_x = int(bad.sum())
        mask &= x > 0
    if log_y:
        bad = finite & ~(y > 0)
        rep.n_nonpositive_y = int(bad.sum())
        mask &= y > 0
    rep.n_used = int(mask.sum())
    return mask, rep


@dataclass
class PowerLawFit:
    a: float
    b: float
    n: int
    r2_log: float
    r2_linear: float
    a_ci: tuple[float, float]
    b_ci: tuple[float, float]
    rmse_log10: float            # RMS of log10 residuals (a multiplicative error measure)
    bias_factor: float           # Duan (1983) smearing factor; multiply predictions to estimate the mean
    confidence: float = 0.95
    label: str = ""

    def predict(self, x, smear: bool = False):
        x = np.asarray(x, dtype=float)
        y = self.a * np.power(np.where(x > 0, x, np.nan), self.b)
        return y * self.bias_factor if smear else y

    def equation(self, y_name: str = "Qs", x_name: str = "Q") -> str:
        return f"{y_name} = {self.a:.4g} {x_name}^{self.b:.4f}"

    def summary(self) -> dict:
        return {"a": self.a, "b": self.b, "n": self.n, "R2_log": self.r2_log, "R2_linear": self.r2_linear,
                "a_CI_low": self.a_ci[0], "a_CI_high": self.a_ci[1], "b_CI_low": self.b_ci[0],
                "b_CI_high": self.b_ci[1], "RMSE_log10": self.rmse_log10, "smearing_factor": self.bias_factor,
                "confidence": self.confidence}


def _r_squared(y_actual: np.ndarray, y_predicted: np.ndarray) -> float:
    """Coefficient of determination (from SedRatingCurve/analysis.py)."""
    y_actual = np.asarray(y_actual, dtype=float)
    y_predicted = np.asarray(y_predicted, dtype=float)
    ss_res = np.sum((y_actual - y_predicted) ** 2)
    ss_tot = np.sum((y_actual - np.mean(y_actual)) ** 2)
    if ss_tot == 0:
        return 0.0
    return float(1.0 - ss_res / ss_tot)


def fit_power_law(x, y, min_points: int = 3, confidence: float = 0.95) -> PowerLawFit | None:
    """Fit y = a x^b by OLS on (ln x, ln y).  Only points with x>0, y>0 are used.

    Returns ``None`` when fewer than ``min_points`` usable points exist or x has no spread.  A power law
    is a statistical description only; it does not imply a single relation is physically adequate.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y) & (x > 0) & (y > 0)
    n = int(ok.sum())
    if n < max(min_points, 3):
        return None
    lx, ly = np.log(x[ok]), np.log(y[ok])
    if np.ptp(lx) == 0:
        return None
    res = stats.linregress(lx, ly)
    b, ln_a = float(res.slope), float(res.intercept)
    tcrit = stats.t.ppf(0.5 + confidence / 2.0, df=n - 2) if n > 2 else np.nan
    b_ci = (b - tcrit * res.stderr, b + tcrit * res.stderr)
    a_ci = (float(np.exp(ln_a - tcrit * res.intercept_stderr)), float(np.exp(ln_a + tcrit * res.intercept_stderr)))
    resid = ly - (ln_a + b * lx)
    y_hat = np.exp(ln_a) * x[ok] ** b
    return PowerLawFit(
        a=float(np.exp(ln_a)), b=b, n=n, r2_log=float(res.rvalue ** 2), r2_linear=_r_squared(y[ok], y_hat),
        a_ci=a_ci, b_ci=(float(b_ci[0]), float(b_ci[1])), rmse_log10=float(np.sqrt(np.mean(resid ** 2)) / np.log(10)),
        bias_factor=float(np.mean(np.exp(resid))), confidence=confidence)


def fit_loglog_poly(x, y, degree: int = 2, q_ref: float | None = None, min_points: int = 6) -> dict | None:
    """ln y = sum_i c_i (ln q*)^i, q* = x / q_ref (default geometric-mean x).  Returns coefficients
    (highest power first as in ``np.polyfit``), R^2 in log space and a predict callable."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y) & (x > 0) & (y > 0)
    if ok.sum() < max(min_points, degree + 2):
        return None
    q_ref = float(np.exp(np.mean(np.log(x[ok])))) if q_ref is None else q_ref
    lq, ly = np.log(x[ok] / q_ref), np.log(y[ok])
    coeffs = np.polyfit(lq, ly, degree)
    r2 = _r_squared(ly, np.polyval(coeffs, lq))
    return {"coeffs": coeffs, "q_ref": q_ref, "r2_log": r2, "n": int(ok.sum()), "degree": degree,
            "predict": lambda xv: np.exp(np.polyval(coeffs, np.log(np.asarray(xv, dtype=float) / q_ref)))}


def fit_rating_curve_legacy(x, y, min_points: int = 3) -> dict:
    """Power / linear / logarithmic / exponential fits (refactored from the original SedRatingCurve tool)."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    fits: dict = {}
    pos = (x > 0) & (y > 0)
    if pos.sum() >= min_points:
        xb, yb = x[pos], y[pos]
        b, ln_a = np.polyfit(np.log(xb), np.log(yb), 1)
        a = np.exp(ln_a)
        yp = a * xb ** b
        fits["power"] = {"params": {"a": a, "b": b}, "r_squared": _r_squared(np.log(yb), np.log(yp)),
                         "r_squared_linear": _r_squared(yb, yp), "n": int(pos.sum()),
                         "predict": lambda xv, a=a, b=b: a * np.maximum(np.asarray(xv, float), 1e-9) ** b}
    if len(x) >= min_points:
        a1, b1 = np.polyfit(x, y, 1)
        fits["linear"] = {"params": {"a": a1, "b": b1}, "r_squared": _r_squared(y, a1 * x + b1), "n": len(x),
                          "predict": lambda xv, a=a1, b=b1: a * np.asarray(xv, float) + b}
    px = x > 0
    if px.sum() >= min_points:
        a2, b2 = np.polyfit(np.log(x[px]), y[px], 1)
        fits["logarithmic"] = {"params": {"a": a2, "b": b2}, "r_squared": _r_squared(y[px], a2 * np.log(x[px]) + b2),
                               "n": int(px.sum()),
                               "predict": lambda xv, a=a2, b=b2: a * np.log(np.maximum(np.asarray(xv, float), 1e-9)) + b}
    py = y > 0
    if py.sum() >= min_points:
        b3, ln_a3 = np.polyfit(x[py], np.log(y[py]), 1)
        a3 = np.exp(ln_a3)
        fits["exponential"] = {"params": {"a": a3, "b": b3}, "r_squared": _r_squared(y[py], a3 * np.exp(b3 * x[py])),
                               "n": int(py.sum()), "predict": lambda xv, a=a3, b=b3: a * np.exp(b * np.asarray(xv, float))}
    if not fits:
        return {"fits": {}, "best_by_r2": None, "power_ok": False}
    return {"fits": fits, "best_by_r2": max(fits, key=lambda k: fits[k]["r_squared"]), "power_ok": "power" in fits}
