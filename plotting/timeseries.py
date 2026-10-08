"""Time-series style plots (pure Matplotlib, no Qt)."""
from __future__ import annotations

from dataclasses import dataclass, field

import matplotlib
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from matplotlib.figure import Figure

from plotting.styles import CURRENT_COLOR, OBS_COLOR, SECONDARY_COLOR, DisplayUnits, PinnedDataset, SeriesData


@dataclass
class TimeSeriesRequest:
    left: list[SeriesData]
    right: list[SeriesData] = field(default_factory=list)
    pinned: list[PinnedDataset] = field(default_factory=list)
    title: str = ""
    subtitle: str = ""
    log_left: bool = False
    log_right: bool = False
    left_name: str = ""
    right_name: str = ""
    xlim: tuple | None = None


@dataclass
class DrawInfo:
    notes: list[str] = field(default_factory=list)


def _times(x) -> np.ndarray:
    return np.asarray(x).astype("datetime64[ns]")


def _plot_series(ax, s: SeriesData, du: DisplayUnits, color: str, ls: str, lw: float, alpha: float, log: bool,
                 info: DrawInfo, zorder: int = 3):
    y = np.asarray(du.convert(s.y, s.y_quantity), dtype=float)
    x = _times(s.x)
    if log:
        bad = np.isfinite(y) & ~(y > 0)
        if bad.any():
            info.notes.append(f"{s.label}: {int(bad.sum())} values \u2264 0 omitted on log axis")
        y = np.where(y > 0, y, np.nan)
    if s.role == "obs":
        kind = s.meta.get("kind", "sample")
        if kind == "sample":
            ax.scatter(x, y, s=34, marker="o", facecolor=color, edgecolor="black", linewidth=0.6, label=s.label,
                       zorder=6, alpha=0.95)
        else:
            ax.scatter(x, y, s=7, marker=".", color=color, label=s.label, zorder=5, alpha=0.6)
        return
    ax.plot(x, y, color=color, linestyle=ls, linewidth=lw, alpha=alpha, label=s.label, zorder=zorder)


def draw_timeseries(fig: Figure, req: TimeSeriesRequest, du: DisplayUnits) -> DrawInfo:
    fig.clear()
    info = DrawInfo()
    ax = fig.add_subplot(111)
    ax2 = ax.twinx() if req.right else None
    lq = req.left[0].y_quantity if req.left else None
    rq = req.right[0].y_quantity if req.right else None

    for s in req.left:
        if s.role == "obs":
            _plot_series(ax, s, du, OBS_COLOR, "-", 1, 1, req.log_left, info)
        else:
            _plot_series(ax, s, du, CURRENT_COLOR, "-", 1.3, 1.0, req.log_left, info)
    if ax2 is not None:
        for s in req.right:
            if s.role == "obs":
                _plot_series(ax2, s, du, "#7570b3", "-", 1, 1, req.log_right, info)
            else:
                _plot_series(ax2, s, du, SECONDARY_COLOR, "--", 1.0, 0.9, req.log_right, info, 2)

    for pin in req.pinned:
        for s in pin.series:
            if s.y_quantity == lq:
                _plot_series(ax, s, du, pin.color, "-", 1.2, 0.9, req.log_left, info, 4)
            elif ax2 is not None and s.y_quantity == rq:
                _plot_series(ax2, s, du, pin.color, ":", 1.0, 0.8, req.log_right, info, 4)
            else:
                info.notes.append(f"Pinned '{s.label}' not shown: its quantity is not on the current axes.")

    if req.log_left:
        ax.set_yscale("log")
    left_label = req.left_name or (f'{lq}' if lq else '')
    ax.set_ylabel(f'{left_label} ({du.label(lq)})' if lq else left_label)
    if ax2 is not None:
        if req.log_right:
            ax2.set_yscale("log")
        ax2.set_ylabel(f'{req.right_name} ({du.label(rq)})' if rq else req.right_name)
    ax.grid(True, alpha=0.3)
    loc = mdates.AutoDateLocator()
    ax.xaxis.set_major_locator(loc)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(loc))
    if req.xlim:
        ax.set_xlim(req.xlim)

    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = (ax2.get_legend_handles_labels() if ax2 is not None else ([], []))
    if h1 or h2:
        ax.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=8, framealpha=0.9, ncol=1)
    ax.set_title(req.title, fontsize=11, loc="left")
    fig.text(0.01, 0.005, req.subtitle, fontsize=7, color="#444444", ha="left", va="bottom")
    fig.subplots_adjust(left=0.09, right=0.91 if ax2 is not None else 0.97, top=0.92, bottom=0.12)
    return info


def draw_stacked_contribution(fig: Figure, class_flux_kg_s: pd.DataFrame, du: DisplayUnits, relative: bool,
                              title: str, subtitle: str, resample: str | None = "30D") -> DrawInfo:
    """Stacked contribution of grain classes to total flux (positive contributions only)."""
    fig.clear()
    info = DrawInfo()
    ax = fig.add_subplot(111)
    df = class_flux_kg_s.copy()
    neg = (df < 0).sum().sum()
    if neg:
        info.notes.append(f'{int(neg)} negative signed class-flux values are omitted from the positive contribution stack.')
    df = df.clip(lower=0).dropna(how="all")
    df = df.loc[:, (df.sum() > 0)]
    if resample and len(df) > 400:
        df = df.resample(resample).mean()
    disp = pd.DataFrame(du.convert(df.values, "mass_flux"), index=df.index, columns=df.columns)
    if disp.empty or not len(disp.columns):
        ax.text(.5,.5,'No positive class flux is available to stack.',transform=ax.transAxes,ha='center')
        ax.set_title(title,loc='left')
        info.notes.append('No positive class flux is available to stack.')
        return info
    if relative:
        tot = disp.sum(axis=1).replace(0, np.nan)
        disp = disp.div(tot, axis=0).fillna(0)
    cmap = matplotlib.colormaps["viridis_r"]
    colors = [cmap(i / max(len(disp.columns) - 1, 1)) for i in range(len(disp.columns))]
    ax.stackplot(disp.index, disp.T.values, labels=list(disp.columns), colors=colors, alpha=0.9)
    ax.set_ylabel("Fraction of total flux" if relative else f"Sediment flux ({du.label('mass_flux')})")
    if relative:
        ax.set_ylim(0, 1)
    ax.grid(True, alpha=0.3)
    loc = mdates.AutoDateLocator()
    ax.xaxis.set_major_locator(loc)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(loc))
    ax.legend(loc="center left", bbox_to_anchor=(1.0, 0.5), fontsize=7, title="Grain class", ncol=1)
    ax.set_title(title, fontsize=11, loc="left")
    fig.text(0.01, 0.005, subtitle, fontsize=7, color="#444444", ha="left", va="bottom")
    fig.subplots_adjust(left=0.09, right=0.86, top=0.92, bottom=0.12)
    return info


def draw_periodic_loads(fig: Figure, loads: pd.DataFrame, du: DisplayUnits, label: str, title: str,
                        subtitle: str, obs_loads: pd.DataFrame | None = None) -> DrawInfo:
    """Bar chart of annual / water-year loads (index = year)."""
    fig.clear()
    info = DrawInfo()
    ax = fig.add_subplot(111)
    mass = du.convert(loads["load_kg"].values, "mass")
    ax.bar(loads.index.astype(str), mass, color="#4c78a8", label=label)
    for i, (m, n) in enumerate(zip(mass, loads["n_steps"].values)):
        if np.isfinite(m):
            ax.text(i, m, f"n={int(n)}", ha="center", va="bottom", fontsize=7, color="#444444")
    ax.set_ylabel(f"Load ({du.label('mass')})")
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend(fontsize=8)
    ax.set_title(title, fontsize=11, loc="left")
    fig.text(0.01, 0.005, subtitle, fontsize=7, color="#444444", ha="left", va="bottom")
    fig.subplots_adjust(left=0.1, right=0.97, top=0.92, bottom=0.14)
    return info
