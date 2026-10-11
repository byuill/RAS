"""Customary presentation without changing the canonical SI calculations.

River station labels identify location, not the length used to integrate volume.
Only an entire numeric station token (optionally HEC-RAS's trailing *) is parsed.
Text IDs require an explicit river_mile manifest column or use distance in miles.
"""
import re

import numpy as np
import pandas as pd

FT_PER_M = 1 / 0.3048
FT2_PER_M2 = FT_PER_M ** 2
YD3_PER_M3 = 1 / (0.9144 ** 3)
M_PER_MILE = 1609.344


def set_customary_spin(spin, canonical_value, factor=FT_PER_M):
    """Preserve exact reference assumptions despite rounded GUI decimals."""
    display_value = canonical_value*factor
    if display_value < spin.minimum():
        spin.setMinimum(display_value)
    if display_value > spin.maximum():
        spin.setMaximum(display_value)
    spin.setValue(display_value)
    spin.setProperty('canonical_reference', float(canonical_value))
    spin.setProperty('display_reference', spin.value())


def read_customary_spin(spin, factor=FT_PER_M):
    reference = spin.property('display_reference')
    if reference is not None and spin.value() == reference:
        return spin.property('canonical_reference')
    return spin.value()/factor


def station_river_mile(xs_id):
    token = str(xs_id).rsplit(':', 1)[-1].strip()
    if re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)\*?', token):
        return float(token.rstrip('*'))
    return np.nan


def river_miles(table):
    if 'river_mile' in table:
        return pd.to_numeric(table.river_mile, errors='raise').to_numpy(float)
    if 'xs_id' in table:
        return table.xs_id.map(station_river_mile).to_numpy(float)
    return np.full(len(table), np.nan)


def uses_river_miles(table):
    return len(table) > 0 and np.isfinite(river_miles(table)).all()


def longitudinal_x(table):
    return river_miles(table) if uses_river_miles(table) else table.chainage_m.to_numpy() / M_PER_MILE


def longitudinal_axis(axis, table, *, midpoint=False):
    """Keep upstream on the left even with decreasing or negative station labels."""
    from matplotlib.ticker import FuncFormatter, MaxNLocator
    is_rm = uses_river_miles(table)
    label = 'River mile (model XS; downstream →)' if is_rm else 'Downstream distance (mi; RM unavailable)'
    if midpoint and is_rm:
        label = 'Reach midpoint river mile (downstream →)'
    axis.set_xlabel(label)
    x = longitudinal_x(table)
    if len(x) > 1:
        lo, hi = min(x), max(x)
        pad = max((hi-lo)*.025, .001)
        axis.set_xlim((hi+pad, lo-pad) if is_rm and x[0] > x[-1] else (lo-pad, hi+pad))
        if is_rm:
            class RiverMileLocator(MaxNLocator):
                # Show exact end stations while retaining useful ticks when zooming.
                def __call__(self):
                    left, right = sorted(self.axis.get_view_interval())
                    ticks = self.tick_values(left, right)
                    ticks = ticks[(ticks >= left) & (ticks <= right)]
                    endpoints = [station for station in (lo, hi) if left <= station <= right]
                    for station in endpoints:
                        ticks = ticks[abs(ticks-station) > (right-left)*.06]
                    return np.unique(np.r_[ticks, endpoints])
            axis.xaxis.set_major_locator(RiverMileLocator(nbins=5))
            axis.xaxis.set_major_formatter(FuncFormatter(lambda value, position: f'{value:g}'))
    if not is_rm:
        axis.ticklabel_format(axis='x', style='plain', useOffset=False)


def customary_column(column):
    """Return unambiguous customary column name and physical scale factor."""
    # Lateral second moment is integral Δz² du, not a bed-volume estimate.
    rules = [('_second_moment_m3', '_second_moment_ft3', FT_PER_M**3),
             ('_m_per_km2', '_ft_per_mi2', FT_PER_M*(M_PER_MILE/1000)**2),
             ('_m_per_km', '_ft_per_mi', FT_PER_M*M_PER_MILE/1000),
             ('_m_per_m', '_ft_per_ft', 1.),
             ('_m3_per_year', '_yd3_per_year', YD3_PER_M3),
             ('_m_per_year', '_ft_per_year', FT_PER_M),
             ('_m3', '_yd3', YD3_PER_M3), ('_m2', '_ft2', FT2_PER_M2),
             ('_m', '_ft', FT_PER_M)]
    for suffix, replacement, scale in rules:
        if column.endswith(suffix):
            return column[:-len(suffix)]+replacement, scale
    return column, 1.


def customary_frame(frame, station_table=None):
    """Copy and convert display/export tables; never mutate calculation inputs."""
    out = frame.copy()
    if 'xs_id' in out and 'river_mile' not in out:
        if station_table is not None:
            lookup = dict(zip(station_table.xs_id, river_miles(station_table)))
            values = out.xs_id.map(lookup)
        else:
            values = out.xs_id.map(station_river_mile)
        if values.notna().all() and len(values):
            out.insert(1, 'river_mile', values)
    if station_table is not None and uses_river_miles(station_table):
        lookup = dict(zip(station_table.xs_id, river_miles(station_table)))
        if {'upstream_xs', 'downstream_xs'} <= set(out):
            out['upstream_river_mile'] = out.upstream_xs.map(lookup)
            out['downstream_river_mile'] = out.downstream_xs.map(lookup)
            out['mid_river_mile'] = (out.upstream_river_mile+out.downstream_river_mile)/2
    for column in list(out):
        if column.endswith('chainage_m'):
            # Retain a clearly labelled distance companion; never relabel as RM.
            out[column[:-len('chainage_m')]+'downstream_distance_mi'] = out.pop(column) / M_PER_MILE
        else:
            renamed, scale = customary_column(column)
            if renamed != column:
                out[renamed] = out.pop(column)*scale
    return out


def customary_header(column):
    if column == 'xs_id':
        return 'Cross section'
    for suffix, unit in [('_ft_per_mi2', 'ft / downstream mi²'), ('_ft_per_mi', 'ft / downstream mi'),
                         ('_ft_per_ft', 'ft/ft'), ('_yd3_per_year', 'yd³/year'),
                         ('_ft_per_year', 'ft/year'), ('_ft3', 'ft³'), ('_yd3', 'yd³'),
                         ('_ft2', 'ft²'), ('_ft', 'ft'), ('_mi', 'mi')]:
        if column.endswith(suffix):
            return column[:-len(suffix)].replace('_', ' ').capitalize()+f' ({unit})'
    return column.replace('_', ' ').capitalize()


def customary_mapping(values):
    """Convert dimensional fields in a human-readable report."""
    out = {}
    for key, value in values.items():
        renamed, scale = customary_column(key)
        out[renamed] = customary_mapping(value) if isinstance(value, dict) else (
            value*scale if value is not None and isinstance(value, (int, float)) else value)
    return out


def select_river_mile_range(transects, bounds):
    """Select consecutive existing XS, preserving channel lengths and HDF columns."""
    from .core import CalibrationError, validate_transects
    frame, sections = validate_transects(transects)
    if bounds is None:
        return frame
    try:
        upstream, downstream = float(bounds['upstream']), float(bounds['downstream'])
    except (KeyError, TypeError, ValueError) as exc:
        raise CalibrationError('River-mile range needs numeric upstream and downstream bounds.') from exc
    rm = river_miles(sections)
    if not np.isfinite([upstream, downstream]).all() or upstream <= downstream:
        raise CalibrationError('Upstream river mile must exceed downstream river mile; negative stations are valid.')
    if not np.isfinite(rm).all() or (np.diff(rm) >= 0).any():
        raise CalibrationError('River-mile selection requires finite, downstream-decreasing model station labels or a river_mile column.')
    if upstream > rm[0]+1e-8 or downstream < rm[-1]-1e-8:
        raise CalibrationError(f'River-mile bounds must stay within the manifest: RM {rm[0]:g} to {rm[-1]:g}.')
    ids = sections.loc[(rm <= upstream+1e-8) & (rm >= downstream-1e-8), 'xs_id']
    if len(ids) < 2:
        raise CalibrationError('River-mile range must contain at least two model cross sections.')
    selected = frame[frame.xs_id.isin(ids)].copy()
    selected.loc[selected.xs_id == ids.iloc[-1], 'length_to_next_m'] = np.nan
    return selected


CUSTOMARY_GUIDE = """1. Review baseline and target surveys on the same lateral bed footprint.
   Elevations, lateral stations and verified channel lengths display in ft.
   River mile comes from the model XS station label (including negative RM).
   It locates the section; it does not replace the verified channel length.
2. Interpolate linearly between supported source knots. Keep NaN/gap barriers;
   no extrapolation. Every source must support each accepted lateral interval.
3. Δz = target − baseline [ft]; positive deposition, negative erosion.
   ΔA = Σ width × (Δz_left + Δz_right)/2 [ft²].
4. Default reach volume = L × (ΔA_upstream + ΔA_downstream)/2 / 27 [yd³].
   L is the verified channel length [ft]. 27 ft³ = 1 yd³.
5. XS control length is half each neighboring accepted reach length.
   Local volume = ΔA × control length / 27 [yd³]. Node cumulative sums start
   with the first half-reach contribution. Completed-reach prefixes start at
   zero. Intermediate values differ; totals at segment ends agree.
   Upstream/downstream estimators instead hold the selected endpoint area.
6. Unsupported XS disconnect segments; cumulative sums restart at each gap.
   Partial footprints remain partial. Changing a range changes end weights.
7. Split linear changes at zero into erosion and deposition magnitudes.
   Gross = deposition + erosion; net = deposition − erosion [yd³].
   Cancellation = 1 − |net|/gross (undefined when gross is zero).
   Width/control-length-weighted standard deviations display in ft.
   These are sampled two-date indicators, not continuous 2-D morphology,
   intervening activity, sediment transport or porosity-corrected solids.
8. Derivatives use verified downstream-increasing chainage; displayed units
   are ft per downstream mile and ft per downstream mile², even when RM decreases.
9. Hypothetical shifts explore assumptions; independent benchmark evidence
   is required for a real datum correction. Compare footprints before totals.
   Error intervals describe supplied survey errors, with model treated as exact.

Calculations, source mappings, saved configuration and reproducible scenario
instructions retain SI units. Customary CSV companions and plots match the GUI.
"""
