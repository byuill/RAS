"""Reversible observation QA/QC: flag suspect cells and mask reviewed exclusions."""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from observations.processing import OBS_VARIABLES


@dataclass
class QaqcReview:
    flags: pd.DataFrame
    reasons: pd.DataFrame
    notes: list[str]
    options: dict


def excluded_mask(df, column):
    if 'qaqc_excluded_fields' not in df:
        return np.zeros(len(df), dtype=bool)
    return df.qaqc_excluded_fields.fillna('').map(lambda x: column in str(x).split(';')).to_numpy(bool)


def review_observations(df, variable='ssc_mg_l', method='mad', threshold=6., log=True,
                        lower=None, upper=None, flag_censored=True):
    """Detect candidates, without modifying values or treating floods as known errors."""
    if variable not in OBS_VARIABLES or method not in ('none', 'mad', 'iqr', 'rating_residual'):
        raise ValueError('Choose a supported observation variable and review method.')
    if not np.isfinite(threshold) or threshold <= 0:
        raise ValueError('Outlier threshold must be finite and positive.')
    if (lower is not None and not np.isfinite(lower)) or (upper is not None and not np.isfinite(upper)):
        raise ValueError('Bounds must be finite.')
    if lower is not None and upper is not None and lower > upper:
        raise ValueError('The lower bound must not exceed the upper bound.')
    columns = [c for c in OBS_VARIABLES if c in df]
    flags = pd.DataFrame(False, index=df.index, columns=columns)
    reasons = pd.DataFrame('', index=df.index, columns=columns)
    notes = []
    def flag(column, mask, reason):
        if column not in flags: return
        positions = np.flatnonzero(np.asarray(mask, bool))
        ci = flags.columns.get_loc(column)
        flags.iloc[positions, ci] = True
        existing = reasons.iloc[positions, ci].to_numpy()
        reasons.iloc[positions, ci] = [f'{old}; {reason}'.strip('; ') for old in existing]
    for column in columns:
        values = pd.to_numeric(df[column], errors='coerce').to_numpy(float)
        flag(column, np.isinf(values), 'nonfinite numeric value')
        if column in ('ssc_mg_l', 'sand_mg_l', 'fines_mg_l'):
            flag(column, values < 0, 'negative sediment concentration')
        if column == 'ssl_kg_s' and 'discharge_m3s' in df:
            q = pd.to_numeric(df.discharge_m3s, errors='coerce').to_numpy(float)
            flag(column, (values < 0) & np.isfinite(q) & (q >= 0), 'negative sediment load at nonnegative discharge')
        if column == 'pct_fines': flag(column, (values < 0) | (values > 100), 'percent outside 0–100')
        if flag_censored and 'censored_fields' in df:
            mask = df.censored_fields.fillna('').map(lambda text: column in str(text).split(';'))
            flag(column, mask, 'censored/detection-limit result; not an exact measurement')
    if variable not in df:
        notes.append(f'No {variable} column to review.')
    else:
        values = pd.to_numeric(df[variable], errors='coerce').to_numpy(float)
        if lower is not None: flag(variable, values < lower, 'below user bound')
        if upper is not None: flag(variable, values > upper, 'above user bound')
        valid = np.isfinite(values) & ~flags[variable].to_numpy() & ~excluded_mask(df, variable)
        transformed = values.copy()
        if log:
            valid &= values > 0
            with np.errstate(divide='ignore', invalid='ignore'): transformed = np.log10(values)
        if method == 'rating_residual':
            q = pd.to_numeric(df.get('discharge_m3s', pd.Series(np.nan, index=df.index)), errors='coerce').to_numpy(float)
            valid &= np.isfinite(q) & (q > 0) & (values > 0)
            if valid.sum() >= 10 and np.ptp(np.log(q[valid])) > 0:
                b, a = np.polyfit(np.log(q[valid]), np.log(values[valid]), 1)
                transformed[valid] = np.log(values[valid]) - (a + b*np.log(q[valid]))
            else:
                valid[:] = False
                notes.append('Rating-residual review needs 10 positive sediment/discharge pairs with discharge variation.')
        if method != 'none' and valid.sum() >= 10:
            sample = transformed[valid]
            if method in ('mad', 'rating_residual'):
                median = np.median(sample); mad = np.median(np.abs(sample-median))
                if mad > np.finfo(float).eps:
                    flag(variable, valid & (np.abs(transformed-median)*.67448975/mad > threshold), 'robust MAD outlier candidate')
                else: notes.append('MAD is zero: no statistical outliers flagged; use explicit bounds and review manually.')
            else:
                low, high = np.quantile(sample, [.25, .75]); spread = high-low
                if spread > 0:
                    flag(variable, valid & ((transformed < low-threshold*spread) | (transformed > high+threshold*spread)), 'IQR outlier candidate')
                else: notes.append('IQR is zero: no statistical outliers flagged.')
        elif method != 'none' and method != 'rating_residual':
            notes.append('Statistical review needs at least 10 usable values; only physical/qualifier/bound flags applied.')
    notes.append('Statistical flags are review candidates: floods, hysteresis and grain-size shifts can be real. No values are discarded until you apply exclusions.')
    return QaqcReview(flags, reasons, notes, {'variable': variable, 'method': method, 'threshold': threshold,
        'log': log, 'lower_canonical': lower, 'upper_canonical': upper, 'flag_censored': flag_censored})


def apply_exclusions(obs, masks, review=None):
    """Mask cells on a copy, retain raw input externally and prevent fallback resurrection."""
    d = obs.df.copy(deep=True)
    affected = [set(str(x).split(';')) - {''} for x in d.get('qaqc_excluded_fields', pd.Series('', index=d.index))]
    for column in masks:
        if column not in d: continue
        mask = np.asarray(masks[column], dtype=bool)
        if mask.shape != (len(d),): raise ValueError('QA/QC masks must match the observation row count.')
        for i in np.flatnonzero(mask): affected[i].add(column)
    # Remove downstream quantities only when their provenance identifies a derivation.
    qualifiers = d.get('qualifier', pd.Series('', index=d.index)).fillna('').astype(str).to_numpy()
    for i, fields in enumerate(affected):
        if ('ssc_mg_l' in fields or 'discharge_m3s' in fields) and 'ssl=derived' in qualifiers[i]:
            fields.add('ssl_kg_s')
        if ('ssc_mg_l' in fields or 'pct_fines' in fields) and 'fractions=derived' in qualifiers[i]:
            fields.update(['sand_mg_l', 'fines_mg_l'])
        for column in fields:
            if column in d: d.iat[i, d.columns.get_loc(column)] = np.nan
    d['qaqc_excluded_fields'] = [';'.join(sorted(fields)) for fields in affected]
    changes = sum(bool(fields) for fields in affected)
    notes = list(obs.notes) + [f'QA/QC excluded values in {changes} records; raw observations/cache remain unchanged.']
    out = replace(obs, df=d, notes=notes, derivations=list(obs.derivations), sources=list(obs.sources),
                  cache_status=list(obs.cache_status), qaqc={'excluded_records': changes,
                    'excluded_cells': sum(len(fields) for fields in affected),
                    'options': review.options if review else {}, 'notes': review.notes if review else []})
    return out
