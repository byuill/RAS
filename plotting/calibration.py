"""Calibration diagnostics: 1:1 scatter, residuals, observed/model ratio."""
from __future__ import annotations

import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from matplotlib.figure import Figure

from analysis.rating_curve import valid_xy
from plotting.styles import OBS_COLOR, DisplayUnits


def draw_calibration(fig: Figure, paired: pd.DataFrame, quantity: str, name: str, du: DisplayUnits,
                     log: bool, stats_text: str, title: str, subtitle: str) -> None:
    """``paired`` has DateTime index and canonical columns ``obs`` and ``mod``."""
    fig.clear()
    gs = fig.add_gridspec(2, 2, height_ratios=[1.0, 1.0], width_ratios=[1.0, 1.15])
    ax1 = fig.add_subplot(gs[:, 0])
    ax2 = fig.add_subplot(gs[0, 1])
    ax3 = fig.add_subplot(gs[1, 1], sharex=ax2)
    unit = du.label(quantity)
    o = np.asarray(du.convert(paired["obs"].values, quantity), dtype=float)
    m = np.asarray(du.convert(paired["mod"].values, quantity), dtype=float)
    ok, rep = valid_xy(o, m, log, log)
    ax1.scatter(o[ok], m[ok], s=28, color=OBS_COLOR, edgecolor="black", linewidth=0.5, zorder=3)
    if ok.any():
        lo = min(o[ok].min(), m[ok].min())
        hi = max(o[ok].max(), m[ok].max())
        ax1.plot([lo, hi], [lo, hi], color="#444444", lw=1, label="1:1")
        if log:
            ax1.plot([lo, hi], [lo * 2, hi * 2], color="#999999", lw=0.8, ls=":", label="2:1 / 1:2")
            ax1.plot([lo, hi], [lo / 2, hi / 2], color="#999999", lw=0.8, ls=":")
    if log:
        ax1.set_xscale("log")
        ax1.set_yscale("log")
    ax1.set_xlabel(f"Observed {name} ({unit})")
    ax1.set_ylabel(f"HEC-RAS {name} ({unit})")
    ax1.grid(True, which="both", alpha=0.25)
    ax1.legend(fontsize=7, loc="upper left")
    ax1.text(0.99, 0.01, stats_text, transform=ax1.transAxes, ha="right", va="bottom", fontsize=7,
             bbox=dict(boxstyle="round", fc="white", ec="#cccccc", alpha=0.9))
    ax1.set_title("Observed vs modelled", fontsize=9, loc="left")

    t = paired.index
    ax2.axhline(0, color="#444444", lw=0.8)
    ax2.scatter(t, m - o, s=14, color="#1f77b4", alpha=0.8)
    ax2.set_ylabel(f"Residual (model - obs) ({unit})")
    ax2.grid(True, alpha=0.25)
    ax2.set_title("Residuals", fontsize=9, loc="left")
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(o > 0, m / o, np.nan)
    ax3.axhline(1, color="#444444", lw=0.8)
    ax3.scatter(t, ratio, s=14, color="#2ca02c", alpha=0.8)
    ax3.set_yscale("log")
    ax3.set_ylabel("Model / observed")
    ax3.grid(True, which="both", alpha=0.25)
    loc = mdates.AutoDateLocator()
    ax3.xaxis.set_major_locator(loc)
    ax3.xaxis.set_major_formatter(mdates.ConciseDateFormatter(loc))
    fig.suptitle(title, fontsize=11, x=0.01, ha="left")
    fig.text(0.01, 0.005, subtitle, fontsize=7, color="#444444", ha="left", va="bottom")
    fig.subplots_adjust(left=0.08, right=0.97, top=0.9, bottom=0.1, wspace=0.28, hspace=0.35)
