"""Read-only orchestration, auditable survey review, matched time series, and exports."""
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .cache import ProfileCache, cache_key, fingerprint
from .core import CalibrationError, compare_profiles, validate_transects
from .qaqc import datum_shift_review, review_survey
from .sources import model_times, native_volume_audit, read_model_snapshots, read_survey


def load_config(path):
    path = Path(path).resolve()
    try:
        settings = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(settings, dict) or not isinstance(settings['surveys'], dict):
            raise ValueError('Configuration and surveys must be JSON objects.')
        for field in ('transects', 'cache_dir'):
            value = Path(settings[field])
            settings[field] = str(value if value.is_absolute() else path.parent/value)
        for source in [*settings['surveys'].values(), settings.get('model', {}), settings.get('native_volume', {})]:
            if 'path' in source:
                value = Path(source['path'])
                source['path'] = str(value if value.is_absolute() else path.parent/value)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise CalibrationError(f'Could not load configuration {path}: {exc}') from exc
    return settings


def _cancelled(cancel):
    if cancel is not None and cancel.is_set():
        raise CalibrationError('Operation cancelled; no comparison result was published.')


def _load_surveys(settings, names, *, cancel=None):
    if not names or any(name not in settings['surveys'] for name in names):
        raise CalibrationError('Select configured survey names.')
    from rasterio.crs import CRS
    from rasterio.errors import CRSError
    try:
        analysis = CRS.from_user_input(settings['analysis_crs'])
        if not analysis.is_projected or abs(analysis.linear_units_factor[1]-1) > 1e-9:
            raise ValueError('Use projected metre horizontal units.')
    except (ValueError, KeyError, CRSError) as exc:
        raise CalibrationError(f'Invalid analysis_crs: {exc}') from exc
    transects, _ = validate_transects(pd.read_csv(settings['transects'], dtype={'xs_id': str}))
    geometry = fingerprint(settings['transects'])
    sources = {name: settings['surveys'][name] for name in names}
    cache_path = Path(settings['cache_dir']).resolve()
    for source in sources.values():
        path = Path(source['path']).resolve()
        if path.is_dir() and (cache_path == path or path in cache_path.parents):
            raise CalibrationError('The cache must be outside the source geodatabase.')
    fingerprints = {path: fingerprint(path) for path in {s['path'] for s in sources.values()}}
    cache = ProfileCache(cache_path)
    integration = settings.get('integration', {})
    extraction = {'analysis_crs': settings['analysis_crs'], 'adapter_version': 3,
                  'sample_spacing_m': integration.get('sample_spacing_m', 10),
                  'longitudinal_limit_m': integration.get('longitudinal_limit_m', 50)}
    raw, statuses = {}, []
    for name, source in sources.items():
        _cancelled(cancel)
        key = cache_key(source, settings['transects'], extraction,
                        source_fingerprint=fingerprints[source['path']], transect_fingerprint=geometry)
        profile = cache.get(key)
        hit = profile is not None
        if not hit:
            profile = read_survey(source, transects, settings)
            # Do not commit extraction from inputs that changed during processing.
            if fingerprint(source['path']) != fingerprints[source['path']] or fingerprint(settings['transects']) != geometry:
                raise CalibrationError('Survey or geometry changed during extraction; no cache result was committed.')
            cache.put(key, profile)
        raw[name] = profile
        statuses.append({'survey': name, 'key': key, 'hit': hit, 'mapping': profile.attrs.get('mapping')})
    return transects, raw, statuses, geometry, fingerprints


def _verify_inputs(settings, geometry, fingerprints):
    if fingerprint(settings['transects']) != geometry or any(fingerprint(path) != value for path, value in fingerprints.items()):
        raise CalibrationError('Survey or geometry changed during processing.')


def run_survey_qaqc(settings, names=None, *, cancel=None):
    """Survey review also works before selecting model dates or resolving duplicates."""
    names = list(names or settings['surveys'])
    _, raw, statuses, geometry, fingerprints = _load_surveys(settings, names, cancel=cancel)
    reviews = {name: review_survey(raw[name], settings['surveys'][name].get('qaqc'),
                                  max_gap_m=settings.get('integration', {}).get('max_gap_m', 25),
                                  allow_unresolved_duplicates=True) for name in names}
    _verify_inputs(settings, geometry, fingerprints)
    return reviews, {'cache': statuses, 'settings': settings}


def _validate_alignment(settings, names, times, indices):
    if len(set(names)) != len(names):
        raise CalibrationError('Select distinct baseline and target surveys.')
    if settings.get('spatial_mapping_verified') is not True or settings.get('temporal_alignment_verified') is not True:
        raise CalibrationError('Local XS geometry/reach-length mapping and survey/model time alignment must be verified.')
    datum = settings.get('vertical_datum')
    if not isinstance(datum, str) or not datum.strip():
        raise CalibrationError('A common verified vertical datum is required.')
    for source in [settings['surveys'][name] for name in names]+[settings['model']]:
        if source.get('vertical_datum') != datum or source.get('vertical_alignment_verified') is not True:
            raise CalibrationError('All sources require verified bed-elevation units and alignment to the common vertical datum.')
    try:
        dates = pd.DatetimeIndex([pd.Timestamp(settings['surveys'][name]['date']) for name in names])
    except (ValueError, KeyError, TypeError) as exc:
        raise CalibrationError('Enter actual survey dates on the common local clock.') from exc
    if dates.hasnans or dates.tz is not None or dates.has_duplicates or not dates.is_monotonic_increasing:
        raise CalibrationError('Survey dates must be present, unique, increasing, and on the common local clock.')
    if any(isinstance(i, bool) or not isinstance(i, (int, np.integer)) or not 0 <= i < len(times) for i in indices) or (np.diff(indices) <= 0).any():
        raise CalibrationError('Select distinct ordered model baseline and target outputs.')
    tolerance = float(settings.get('survey_alignment_tolerance_days', 0))
    if not np.isfinite(tolerance) or tolerance < 0:
        raise CalibrationError('Date alignment tolerance must be finite and nonnegative.')
    for survey_date, model_date in zip(dates, times[indices]):
        if abs((survey_date-model_date).total_seconds()) > tolerance*86400:
            raise CalibrationError(f'Model date {model_date} exceeds survey-date alignment tolerance {tolerance} days for {survey_date}.')
    return dates


def match_survey_times(settings, times, names):
    indices = []
    for name in names:
        try:
            date = pd.Timestamp(settings['surveys'][name]['date'])
            if pd.isna(date) or date.tz is not None:
                raise ValueError('Use an actual date on the common local clock.')
            indices.append(int(np.argmin(abs(times-date))))
        except (KeyError, ValueError, TypeError) as exc:
            raise CalibrationError(f'{name}: an actual survey date is required.') from exc
    _validate_alignment(settings, names, times, indices)
    return indices


def _pair_result(settings, hdf_path, names, indices, times, transects, reviews, statuses,
                 model, model_fingerprint, *, support_profiles=None):
    sources = [settings['surveys'][name] for name in names]
    diagnostics = dict(settings.get('diagnostics', {}))
    datum_threshold = diagnostics.pop('datum_shift_threshold_m', 0.5)
    stable_controls = diagnostics.pop('stable_controls', None)
    uncertainty = [float(source.get('vertical_uncertainty_m', 0)) for source in sources]
    if not np.isfinite(uncertainty).all() or min(uncertainty) < 0:
        raise CalibrationError('Survey vertical_uncertainty_m must be a finite nonnegative one-sigma uncertainty.')
    detection_limit = 1.96*float(np.linalg.norm(uncertainty))
    diagnostics['change_threshold_m'] = max(float(diagnostics.get('change_threshold_m', 0.05)), detection_limit)
    integration = dict(settings.get('integration', {}))
    result = compare_profiles(transects, model[indices[0]], model[indices[1]],
                              reviews[names[0]].profile, reviews[names[1]].profile,
                              support_profiles=support_profiles, diagnostics=diagnostics, **integration)
    survey_dates = [pd.Timestamp(source['date']) for source in sources]
    model_years = (times[indices[1]]-times[indices[0]]).total_seconds()/(365.25*86400)
    survey_years = (survey_dates[1]-survey_dates[0]).total_seconds()/(365.25*86400)
    for prefix, years in [('model', model_years), ('observed', survey_years)]:
        result.sections[f'{prefix}_mean_change_m_per_year'] = result.sections[f'{prefix}_mean_change_m']/years
        result.metrics[f'{prefix}_duration_years'] = float(years)
        result.metrics[f'{prefix}_volume_change_m3_per_year'] = result.metrics[f'{prefix}_total_m3']/years
    result.metrics['survey_change_detection_limit_95_m'] = detection_limit
    warnings = []
    for name in names:
        count = reviews[name].summary['retained_flagged_points']
        if count:
            warnings.append(f'{name}: {count} flagged survey points retained; review the QA/QC audit before interpreting results.')
    if result.metrics['sections_excluded']:
        warnings.append('Unsupported sections are excluded; disconnected reaches are never bridged.')
    if result.metrics['minimum_footprint_coverage'] < 1-1e-10:
        warnings.append('Common sampled footprint is smaller than the full manifest transect. Volumes describe that footprint only.')
    native_status = 'not configured'
    native = settings.get('native_volume')
    if native:
        if native.get('path') and Path(native['path']).resolve() != Path(hdf_path).resolve():
            raise CalibrationError('Native volume path must refer to the selected model HDF; select and verify matching outputs.')
        if (result.sections.footprint_coverage.min() < 1-1e-10 or result.metrics['supported_segments'] != 1 or
                result.metrics['sections_excluded'] or native.get('footprint_verified') is not True or not native.get('time_dataset')):
            native_status = 'skipped: full footprint, contiguous XS, and explicit native date mapping must be verified'
            warnings.append(native_status)
        else:
            native_times = model_times(hdf_path, native)
            native_indices = native_times.get_indexer(times[indices])
            if (native_indices < 0).any():
                raise CalibrationError('Selected profile dates are absent from the native volume output dates.')
            local = native_volume_audit(hdf_path, native, result.sections, *native_indices)
            result.sections['native_local_m3'] = local
            result.sections['native_cumulative_m3'] = np.cumsum(local)
            result.sections['native_minus_reconstructed_local_m3'] = local-result.sections.model_local_control_volume_m3
            result.metrics['native_minus_reconstructed_total_m3'] = float(local.sum()-result.metrics['model_total_m3'])
            native_status = 'audited; native agreement is a separate check'
    audits = []
    for name in names:
        audit = reviews[name].audit.copy()
        audit.insert(0, 'survey', name)
        audits.append(audit)
    result.qaqc = pd.concat(audits, ignore_index=True)
    datum_review = datum_shift_review(result.profiles, threshold_m=datum_threshold, stable_controls=stable_controls)
    if datum_review['uniform_shift_candidate']:
        warnings.append('A coherent observed vertical shift needs review against benchmarks; it may also be real channel change.')
    provenance = {'algorithm': 'matched-profile-segmented-average-end-area-v2',
                  'sign': 'deposition positive; erosion negative', 'settings': settings,
                  'model_fingerprint': model_fingerprint,
                  'model_before_time': str(times[indices[0]]), 'model_after_time': str(times[indices[1]]),
                  'survey_before_time': str(survey_dates[0]), 'survey_after_time': str(survey_dates[1]),
                  'survey_before': names[0], 'survey_after': names[1], 'cache': statuses,
                  'qaqc': {name: reviews[name].summary for name in names}, 'datum_review': datum_review,
                  'native_audit': native_status, 'warnings': warnings,
                  'interpretation': 'Derivatives are unsmoothed on matched mean bed elevations and downstream chainage. '
                                    'Lateral footprints can vary by XS; slopes can reflect changing sampled support. '
                                    'Zone thresholds do not remove sub-threshold volume. Undefined skill is null, not perfect agreement.'}
    return result, provenance


def run_comparison(settings, hdf_path, before_name, after_name, before_index, after_index, *, cancel=None):
    names, indices = [before_name, after_name], [before_index, after_index]
    if any(name not in settings['surveys'] for name in names):
        raise CalibrationError('Select configured baseline and target survey names.')
    times = model_times(hdf_path, settings['model'])
    _validate_alignment(settings, names, times, indices)
    transects, raw, statuses, geometry, fingerprints = _load_surveys(settings, names, cancel=cancel)
    reviews = {name: review_survey(raw[name], settings['surveys'][name].get('qaqc'),
                                  max_gap_m=settings.get('integration', {}).get('max_gap_m', 25)) for name in names}
    _cancelled(cancel)
    model_fingerprint = fingerprint(hdf_path)
    model = read_model_snapshots(hdf_path, settings['model'], transects, indices)
    result = _pair_result(settings, hdf_path, names, indices, times, transects, reviews, statuses, model, model_fingerprint)
    _verify_inputs(settings, geometry, fingerprints)
    if fingerprint(hdf_path) != model_fingerprint:
        raise CalibrationError('Model results changed during processing.')
    _cancelled(cancel)
    return result


@dataclass
class TimeSeriesComparison:
    comparisons: list
    summary: pd.DataFrame
    sections: pd.DataFrame


def run_time_series(settings, hdf_path, names=None, *, cancel=None):
    """Consecutive survey intervals, all on one support mask across every epoch."""
    names = list(names or settings['surveys'])
    try:
        names.sort(key=lambda name: pd.Timestamp(settings['surveys'][name]['date']))
    except (KeyError, TypeError, ValueError) as exc:
        raise CalibrationError('Time-series surveys require actual acquisition dates.') from exc
    if len(names) < 2:
        raise CalibrationError('Time-series comparison requires at least two surveys.')
    times = model_times(hdf_path, settings['model'])
    indices = match_survey_times(settings, times, names)
    transects, raw, statuses, geometry, fingerprints = _load_surveys(settings, names, cancel=cancel)
    reviews = {name: review_survey(raw[name], settings['surveys'][name].get('qaqc'),
                                  max_gap_m=settings.get('integration', {}).get('max_gap_m', 25)) for name in names}
    model_fingerprint = fingerprint(hdf_path)
    model = read_model_snapshots(hdf_path, settings['model'], transects, indices)
    support = list(model.values())+[review.profile for review in reviews.values()]
    comparisons, summary, sections = [], [], []
    for i in range(len(names)-1):
        _cancelled(cancel)
        result, provenance = _pair_result(settings, hdf_path, names[i:i+2], indices[i:i+2], times,
                                          transects, reviews, statuses, model, model_fingerprint,
                                          support_profiles=support)
        provenance['support'] = 'fixed common support across all selected survey and model epochs'
        comparisons.append((result, provenance))
        identity = {'interval': i, 'survey_before': names[i], 'survey_after': names[i+1],
                    'survey_before_time': provenance['survey_before_time'], 'survey_after_time': provenance['survey_after_time']}
        summary.append({**identity, **result.metrics})
        table = result.sections.copy()
        for key, value in identity.items():
            table[key] = value
        sections.append(table)
    _verify_inputs(settings, geometry, fingerprints)
    if fingerprint(hdf_path) != model_fingerprint:
        raise CalibrationError('Model results changed during time-series processing.')
    _cancelled(cancel)
    return TimeSeriesComparison(comparisons, pd.DataFrame(summary), pd.concat(sections, ignore_index=True))


def _output_directory(parent, prefix, settings):
    parent = Path(parent).resolve()
    for source in settings.get('surveys', {}).values():
        path = Path(source['path']).resolve()
        if path.is_dir() and (parent == path or path in parent.parents):
            raise CalibrationError('Exports must stay outside the source geodatabase/dataset directory.')
    directory = Path(parent)/datetime.now(timezone.utc).strftime(prefix+'-%Y%m%dT%H%M%S%fZ')
    directory.mkdir(parents=True, exist_ok=False)
    return directory


def export_comparison(result, provenance, directory):
    directory = _output_directory(directory, 'comparison', provenance['settings'])
    for name in ('sections', 'intervals', 'excluded', 'profiles', 'zones', 'confusion', 'qaqc'):
        table = getattr(result, name)
        if table is not None and len(table):
            filename = {'excluded': 'excluded_sections', 'qaqc': 'survey_qaqc', 'confusion': 'zone_confusion'}.get(name, name)
            table.to_csv(directory/(filename+'.csv'), index=False)
    (directory/'report.json').write_text(json.dumps({'metrics': result.metrics, 'provenance': provenance},
                                                   indent=2, allow_nan=False), encoding='utf-8')
    from matplotlib.figure import Figure
    from .plots import draw_comparison, draw_diagnostics
    figure = Figure(figsize=(11, 7), constrained_layout=True)
    draw_comparison(figure, result, provenance)
    figure.savefig(directory/'comparison.png', dpi=150)
    figure.clear()
    figure = Figure(figsize=(12, 11), constrained_layout=True)
    draw_diagnostics(figure, result)
    figure.savefig(directory/'diagnostics.png', dpi=150)
    figure.clear()
    return directory


def export_time_series(series, directory):
    directory = _output_directory(directory, 'time-series', series.comparisons[0][1]['settings'])
    series.summary.to_csv(directory/'interval_skill.csv', index=False)
    series.sections.to_csv(directory/'section_time_series.csv', index=False)
    for i, (result, provenance) in enumerate(series.comparisons):
        export_comparison(result, provenance, directory/f'interval-{i:03d}')
    from matplotlib.figure import Figure
    from .plots import draw_time_series
    figure = Figure(figsize=(12, 8), constrained_layout=True)
    draw_time_series(figure, series)
    figure.savefig(directory/'time_series.png', dpi=150)
    figure.clear()
    return directory


def export_survey_qaqc(reviews, provenance, directory):
    directory = _output_directory(directory, 'survey-qaqc', provenance['settings'])
    audits, sections = [], []
    for name, review in reviews.items():
        audits.append(review.audit.assign(survey=name))
        sections.append(review.sections.assign(survey=name))
    pd.concat(audits, ignore_index=True).to_csv(directory/'survey_qaqc.csv', index=False)
    pd.concat(sections, ignore_index=True).to_csv(directory/'survey_coverage.csv', index=False)
    (directory/'report.json').write_text(json.dumps({'surveys': {name: review.summary for name, review in reviews.items()},
                                                   'provenance': provenance}, indent=2, allow_nan=False), encoding='utf-8')
    return directory
