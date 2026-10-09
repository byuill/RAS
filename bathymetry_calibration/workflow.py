"""Comparison orchestration, provenance, and exports; input datasets remain read-only."""
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .cache import ProfileCache, cache_key, fingerprint
from .core import CalibrationError, compare_profiles, validate_transects
from .sources import model_times, native_volume_audit, read_model_profiles, read_survey


def load_config(path):
    path = Path(path).resolve()
    settings = json.loads(path.read_text(encoding='utf-8'))
    # Relative paths are relative to the configuration file, never the GUI's cwd.
    for field in ('transects', 'cache_dir'):
        value = Path(settings[field])
        settings[field] = str(value if value.is_absolute() else path.parent / value)
    for source in settings['surveys'].values():
        value = Path(source['path'])
        source['path'] = str(value if value.is_absolute() else path.parent / value)
    return settings


def run_comparison(settings, hdf_path, before_name, after_name, before_index, after_index):
    if before_name == after_name:
        raise CalibrationError('Select distinct baseline and target surveys.')
    if settings.get('spatial_mapping_verified') is not True or settings.get('temporal_alignment_verified') is not True:
        raise CalibrationError('Local XS geometry/reach-length mapping and survey/model time alignment must be verified in the configuration.')
    sources = [settings['surveys'][name] for name in (before_name, after_name)]
    for source in sources + [settings['model']]:
        if source.get('vertical_datum') != settings['vertical_datum'] or source.get('vertical_alignment_verified') is not True:
            raise CalibrationError('All sources require verified bed-elevation units and alignment to the same vertical datum.')
    dates = [pd.Timestamp(source['date']) if source.get('date') else None for source in sources]
    if any(date is None or date.tz is not None or pd.isna(date) for date in dates) or dates[1] <= dates[0]:
        raise CalibrationError('Enter actual, ordered survey dates on the common local clock; survey years alone are insufficient.')
    times = model_times(hdf_path, settings['model'])
    if not 0 <= before_index < after_index < len(times):
        raise CalibrationError('Select ordered model baseline and target outputs.')
    tolerance = float(settings.get('survey_alignment_tolerance_days', 0))
    if not np.isfinite(tolerance) or tolerance < 0:
        raise CalibrationError('Date alignment tolerance must be finite and nonnegative.')
    for survey_date, model_date in zip(dates, times[[before_index, after_index]]):
        if abs((survey_date-model_date).total_seconds()) > tolerance * 86400:
            import sys
            sys.stderr.write(f'WARNING: Selected model output {model_date} is outside the approved survey-date alignment tolerance {tolerance} for {survey_date}.\n')
    transects, _ = validate_transects(pd.read_csv(settings['transects'], dtype={'xs_id': str}))
    cache_path = Path(settings['cache_dir']).resolve()
    for source in sources:
        path = Path(source['path']).resolve()
        if path.is_dir() and (cache_path == path or path in cache_path.parents):
            raise CalibrationError('The cache must be outside the source geodatabase.')
    cache = ProfileCache(cache_path)
    observations, cache_status = [], []
    cache_settings = {'analysis_crs': settings['analysis_crs'], 'vertical_datum': settings['vertical_datum'],
                      'adapter_version': 2,
                      'sample_spacing_m': settings.get('integration', {}).get('sample_spacing_m', 10.0)}
    for name, source in zip((before_name, after_name), sources):
        key = cache_key(source, settings['transects'], cache_settings)
        profile = cache.get(key)
        hit = profile is not None
        if not hit:
            profile = read_survey(source, transects, settings)
            if cache_key(source, settings['transects'], cache_settings) != key:
                raise CalibrationError('Survey or geometry changed while processing; no cache result was committed.')
            cache.put(key, profile)
        observations.append(profile)
        cache_status.append({'survey': name, 'key': key, 'hit': hit})
    model_fingerprint = fingerprint(hdf_path)
    model_before, model_after = read_model_profiles(hdf_path, settings['model'], transects, before_index, after_index)
    result = compare_profiles(transects, model_before, model_after, *observations,
                              **settings.get('integration', {}))
    native = settings.get('native_volume')
    if native:
        if result.sections.coverage.min() < 1 - 1e-10:
            import sys
            sys.stderr.write("WARNING: Native full-bed volume audits require full common lateral support. Skipping native audit.\n")
        else:
            local = native_volume_audit(hdf_path, native, result.sections, before_index, after_index)
            result.sections['native_local_m3'] = local
            result.sections['native_cumulative_m3'] = np.cumsum(local)
            result.sections['native_minus_reconstructed_local_m3'] = local-result.sections.model_local_control_volume_m3
            result.metrics['native_minus_reconstructed_total_m3'] = float(local.sum()-result.metrics['model_total_m3'])
    if fingerprint(hdf_path) != model_fingerprint:
        raise CalibrationError('Model results changed during processing.')
    provenance = {'algorithm': 'common-section-lumped-average-end-area-v1', 'sign': 'deposition positive; erosion negative',
                  'settings': settings, 'model_fingerprint': model_fingerprint,
                  'model_before_time': str(times[before_index]), 'model_after_time': str(times[after_index]),
                  'survey_before': before_name, 'survey_after': after_name, 'cache': cache_status,
                  'warning': 'Native output is an audit until its control volumes and bed footprint match the common-profile reconstruction.'}
    return result, provenance


def export_comparison(result, provenance, directory):
    directory = Path(directory) / datetime.now(timezone.utc).strftime('comparison-%Y%m%dT%H%M%S%fZ')
    directory.mkdir(parents=True, exist_ok=False)
    result.sections.to_csv(directory/'sections.csv', index=False)
    result.intervals.to_csv(directory/'intervals.csv', index=False)
    if result.excluded is not None and len(result.excluded):
        result.excluded.to_csv(directory/'excluded_sections.csv', index=False)
    (directory/'report.json').write_text(json.dumps({'metrics': result.metrics, 'provenance': provenance},
                                                  indent=2, allow_nan=False), encoding='utf-8')
    return directory