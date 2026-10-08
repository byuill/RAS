"""Rating-curve / hysteresis / seasonal scatter plots (pure Matplotlib)."""
from __future__ import annotations

from dataclasses import dataclass, field

import matplotlib
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from matplotlib.collections import LineCollection
from matplotlib.figure import Figure

from analysis.rating_curve import DropReport, PowerLawFit, fit_power_law, valid_xy
from analysis.seasonality import HYDRO_LABELS, MONTH_NAMES, SEASON_ORDER
from plotting.styles import (CURRENT_COLOR, HYDRO_COLORS, LIMB_COLORS, OBS_COLOR, SEASON_COLORS, DisplayUnits,
                             PinnedDataset)
from sediment import units as U

SCALES = {"linear-linear": (False, False), "log x - linear y": (True, False),
          "linear x - log y": (False, True), "log-log": (True, True)}


@dataclass
class RatingRequest:
    x: np.ndarray
    y: np.ndarray
    times: pd.DatetimeIndex
    x_quantity: str
    y_quantity: str
    x_name: str
    y_name: str
    scale: str = "log-log"
    color_by: str = "none"           # none | time | month | season | limb | hydro
    categories: np.ndarray | None = None   # labels aligned with x (month=1..12, season, limb, hydro)
    connect: bool = False
    arrows: bool = False
    fit: bool = False
    fit_by_category: bool = False
    current_label: str = "HEC-RAS Model"
    pinned: list[PinnedDataset] = field(default_factory=list)
    obs_x: np.ndarray | None = None
    obs_y: np.ndarray | None = None
    obs_label: str = "Observed"
    obs_times: pd.DatetimeIndex | None = None
    bins: pd.DataFrame | None = None  # columns q_median, y_median, y_q25, y_q75 (canonical)
    title: str = ""
    subtitle: str = ""


@dataclass
class RatingResult:
    fits: dict[str, PowerLawFit] = field(default_factory=dict)
    drop: DropReport = field(default_factory=DropReport)
    notes: list[str] = field(default_factory=list)
    fit_lines: dict[str, tuple[np.ndarray, np.ndarray]] = field(default_factory=dict)   # canonical x, y


def _category_style(color_by: str, cats: np.ndarray):
    """Return (ordered labels, color per label, display name per label)."""
    if color_by == "month":
        cm = matplotlib.colormaps["twilight_shifted"]
        order = list(range(1, 13))
        return order, {m: cm((m - 1) / 12.0) for m in order}, {m: MONTH_NAMES[m - 1] for m in order}
    if color_by == "season":
        return SEASON_ORDER, SEASON_COLORS, {s: s for s in SEASON_ORDER}
    if color_by == "limb":
        order = ["Rising", "Falling", "Other"]
        return order, LIMB_COLORS, {k: f"{k} limb" if k != "Other" else "Other" for k in order}
    order = ["FIRST_RISING", "Rising", "Falling", "BEFORE_PEAK_OTHER", "AFTER_PEAK_OTHER", "Other"]
    return order, HYDRO_COLORS, HYDRO_LABELS


def _line_over(xmin: float, xmax: float, log_x: bool, n: int = 120) -> np.ndarray:
    if log_x and xmin > 0:
        return np.geomspace(xmin, xmax, n)
    return np.linspace(xmin, xmax, n)


def draw_rating(fig: Figure, req: RatingRequest, du: DisplayUnits) -> RatingResult:
    fig.clear()
    res = RatingResult()
    ax = fig.add_subplot(111)
    log_x, log_y = SCALES[req.scale]
    xd = np.asarray(du.convert(req.x, req.x_quantity), dtype=float)
    yd = np.asarray(du.convert(req.y, req.y_quantity), dtype=float)
    mask, res.drop = valid_xy(xd, yd, log_x, log_y)
    xv, yv, tv = xd[mask], yd[mask], req.times[mask]
    cats = req.categories[mask] if req.categories is not None else None
    ux, uy = du.label(req.x_quantity), du.label(req.y_quantity)

    # pinned datasets first (behind the current data)
    for pin in req.pinned:
        pts = [s for s in pin.series if s.role == "model" and s.x_quantity == req.x_quantity and s.y_quantity == req.y_quantity]
        if not pts:
            res.notes.append(f"Pinned '{pin.label}' not shown: different X/Y variables.")
            continue
        s = pts[0]
        px, py = du.convert(s.x, s.x_quantity), du.convert(s.y, s.y_quantity)
        pm, _ = valid_xy(px, py, log_x, log_y)
        ax.scatter(px[pm], py[pm], s=9, color=pin.color, alpha=0.35, linewidths=0, label=pin.label, zorder=2)
        for f in (x for x in pin.series if x.role == "fit"):
            ax.plot(du.convert(f.x, f.x_quantity), du.convert(f.y, f.y_quantity), color=pin.color, lw=1.6, ls="--",
                    zorder=3, label=f.label)

    # current data
    if len(xv) == 0:
        ax.text(0.5, 0.5, "No valid points for this scale / selection", transform=ax.transAxes, ha="center")
    elif req.color_by == "time" and len(xv):
        t_num = mdates.date2num(tv.to_pydatetime())
        sc = ax.scatter(xv, yv, c=t_num, cmap="viridis", s=12, alpha=0.8, linewidths=0, zorder=3)
        cb = fig.colorbar(sc, ax=ax, pad=0.02, fraction=0.04)
        loc = mdates.AutoDateLocator()
        cb.ax.yaxis.set_major_locator(loc)
        cb.ax.yaxis.set_major_formatter(mdates.ConciseDateFormatter(loc))
        cb.set_label("Date")
        ax.scatter([], [], s=12, color="#440154", label=req.current_label)
    elif req.color_by in ("month", "season", "limb", "hydro") and cats is not None:
        order, colors, names = _category_style(req.color_by, cats)
        for k in order:
            m = cats == k
            if m.any():
                ax.scatter(xv[m], yv[m], s=13, color=colors[k], alpha=0.75, linewidths=0, zorder=3,
                           label=f"{req.current_label}: {names[k]} (n={int(m.sum())})")
    else:
        ax.scatter(xv, yv, s=11, color=CURRENT_COLOR, alpha=0.45, linewidths=0, zorder=3, label=req.current_label)

    # chronological connection / arrows (hysteresis)
    if (req.connect or req.arrows) and len(xv) > 2:
        order_idx = np.argsort(tv.values)
        xo, yo, to = xv[order_idx], yv[order_idx], tv[order_idx]
        pts = np.column_stack([xo, yo])
        segs = np.stack([pts[:-1], pts[1:]], axis=1)
        gap_ok = np.diff(to.values).astype("timedelta64[h]").astype(float) <= 24 * 10   # do not bridge long gaps
        segs = segs[gap_ok]
        if req.connect and len(segs):
            lc = LineCollection(segs, colors="#555555" if req.color_by != "time" else
                                matplotlib.colormaps["viridis"](np.linspace(0, 1, len(gap_ok))[gap_ok]),
                                linewidths=0.6, alpha=0.6, zorder=2)
            ax.add_collection(lc)
        if req.arrows and len(segs):
            step = max(1, len(segs) // 120)
            for sgm in segs[::step]:
                ax.annotate("", xy=tuple(sgm[1]), xytext=tuple(sgm[0]),
                            arrowprops=dict(arrowstyle="->", color="#222222", lw=0.8, alpha=0.8), zorder=4)

    # regression
    if req.fit and len(xv) >= 3:
        groups = {"all": np.ones(len(xv), bool)}
        if req.fit_by_category and cats is not None and req.color_by in ("month", "season", "limb", "hydro"):
            order, colors, names = _category_style(req.color_by, cats)
            groups = {k: cats == k for k in order if (cats == k).sum() >= 3}
        for key, m in groups.items():
            f = fit_power_law(xv[m], yv[m])
            if f is None:
                continue
            f.label = str(key)
            res.fits[str(key)] = f
            xl = _line_over(float(np.nanmin(xv[m])), float(np.nanmax(xv[m])), log_x)
            yl = f.predict(xl)
            col = CURRENT_COLOR if key == "all" else _category_style(req.color_by, cats)[1].get(key, "#444444")
            ax.plot(xl, yl, color=col, lw=2.0, zorder=5,
                    label=f"{'Fit' if key == 'all' else 'Fit ' + str(_category_style(req.color_by, cats)[2].get(key, key))}: "
                          f"y={f.a:.3g}x^{f.b:.3f}, R\u00b2(log)={f.r2_log:.2f}, n={f.n}")
            # canonical-unit copy of the fit line for pinning
            res.fit_lines[str(key)] = (np.asarray(_inv(du, xl, req.x_quantity)), np.asarray(_inv(du, yl, req.y_quantity)))

    # binned medians
    if req.bins is not None and not req.bins.empty:
        bx = du.convert(req.bins["q_median"].values, req.x_quantity)
        by = du.convert(req.bins["y_median"].values, req.y_quantity)
        lo = by - du.convert(req.bins["y_q25"].values, req.y_quantity)
        hi = du.convert(req.bins["y_q75"].values, req.y_quantity) - by
        ax.errorbar(bx, by, yerr=[np.clip(lo, 0, None), np.clip(hi, 0, None)], fmt="s-", color="#1b9e77", ms=5, lw=1.3,
                    capsize=2, zorder=6, label="Model binned median (IQR)")

    # observations
    if req.obs_x is not None and len(req.obs_x):
        ox = du.convert(req.obs_x, req.x_quantity)
        oy = du.convert(req.obs_y, req.y_quantity)
        om, odrop = valid_xy(ox, oy, log_x, log_y)
        ax.scatter(ox[om], oy[om], s=38, color=OBS_COLOR, edgecolor="black", linewidth=0.6, zorder=7,
                   label=f"{req.obs_label} (n={int(om.sum())})")
        if odrop.n_used != odrop.n_total:
            res.notes.append(f"Observations: {odrop.text()}")

    ax.set_xscale("log" if log_x else "linear")
    ax.set_yscale("log" if log_y else "linear")
    ax.set_xlabel(f"{req.x_name} ({ux})")
    ax.set_ylabel(f"{req.y_name} ({uy})")
    ax.grid(True, which="both", alpha=0.25)
    ax.legend(loc="best", fontsize=7, framealpha=0.9)
    ax.set_title(req.title, fontsize=11, loc="left")
    ax.text(0.99, 0.01, res.drop.text(), transform=ax.transAxes, ha="right", va="bottom", fontsize=7, color="#555555")
    fig.text(0.01, 0.005, req.subtitle, fontsize=7, color="#444444", ha="left", va="bottom")
    fig.subplots_adjust(left=0.1, right=0.96 if req.color_by != "time" else 0.92, top=0.92, bottom=0.13)
    return res


def _inv(du: DisplayUnits, values, quantity: str):
    """Display unit -> canonical (inverse of DisplayUnits.convert)."""
    return values if quantity == "dimensionless" else U.to_canonical(values, du.unit(quantity))
