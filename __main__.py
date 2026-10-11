"""Desktop, pair, time-series, and standalone survey QA/QC entry points."""
import argparse
import json

from .core import CalibrationError
from .sources import model_times
from .workflow import (export_comparison, export_survey_qaqc, export_time_series, load_config,
                       match_survey_times, run_comparison, run_survey_qaqc, run_time_series,
                       export_sensitivity)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Compare HEC-RAS bed change with bathymetric surveys')
    parser.add_argument('--config', required=True)
    parser.add_argument('--hdf', help='Overrides model.path in configuration')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--headless', action='store_true', help='Compare a survey pair without the desktop GUI')
    mode.add_argument('--series', action='store_true', help='Compare consecutive surveys on fixed support')
    mode.add_argument('--qaqc-only', action='store_true', help='Review surveys without requiring model data')
    parser.add_argument('--surveys', nargs='+', help='Survey names for series or QA/QC; defaults to all')
    parser.add_argument('--before-survey')
    parser.add_argument('--after-survey')
    parser.add_argument('--before-index', type=int)
    parser.add_argument('--after-index', type=int)
    parser.add_argument('--output', default='output/bathymetry')
    parser.add_argument('--sensitivity', help='JSON with scenarios and optional uncertainty; requires --headless')
    args = parser.parse_args(argv)
    if args.sensitivity and not args.headless:
        parser.error('--sensitivity requires --headless')
    try:
        settings = load_config(args.config)
        hdf = args.hdf or settings.get('model', {}).get('path')
        if args.qaqc_only:
            reviews, provenance = run_survey_qaqc(settings, args.surveys)
            saved = export_survey_qaqc(reviews, provenance, args.output)
            payload = {'surveys': {name: review.summary for name, review in reviews.items()}, 'export': str(saved)}
        elif args.series:
            if not hdf:
                parser.error('--hdf or model.path is required for time-series comparison')
            series = run_time_series(settings, hdf, args.surveys)
            saved = export_time_series(series, args.output)
            payload = {'intervals': json.loads(series.summary.to_json(orient='records')), 'export': str(saved)}
        elif args.headless:
            if not hdf:
                parser.error('--hdf or model.path is required for model comparison')
            names = [args.before_survey, args.after_survey]
            if any(name is None for name in names):
                parser.error('--before-survey and --after-survey are required in --headless mode')
            indices = [args.before_index, args.after_index]
            if any(index is None for index in indices):
                matched = match_survey_times(settings, model_times(hdf, settings['model']), names)
                indices = [matched[i] if value is None else value for i, value in enumerate(indices)]
            result, provenance = run_comparison(settings, hdf, *names, *indices)
            if args.sensitivity:
                from pathlib import Path
                from .calculation_audit import run_sensitivity
                specifications = json.loads(Path(args.sensitivity).read_text(encoding='utf-8'))
                if not isinstance(specifications, dict):
                    raise CalibrationError('Sensitivity specifications must be a JSON object.')
                error = provenance['volume_uncertainty']
                defaults = {key: error[key] for key in
                    ('before_sigma_m', 'after_sigma_m', 'temporal_correlation', 'spatial_correlation')}
                defaults.update(specifications.get('uncertainty', {}))
                exploration = run_sensitivity(result, specifications['scenarios'], uncertainty=defaults)
                saved = export_sensitivity(exploration, provenance, args.output)
            else:
                saved = export_comparison(result, provenance, args.output)
            payload = {'metrics': result.metrics, 'warnings': provenance['warnings'], 'export': str(saved)}
            if args.sensitivity:
                payload['sensitivity_scenarios'] = json.loads(exploration.summary.to_json(orient='records'))
        else:
            from PySide6.QtWidgets import QApplication
            from .gui import CalibrationWindow
            app = QApplication([])
            window = CalibrationWindow(
                args.config, hdf or '',
                before_survey=args.before_survey,
                after_survey=args.after_survey,
                before_index=args.before_index,
                after_index=args.after_index,
            )
            window.show()
            return app.exec()
        print(json.dumps(payload, indent=2, allow_nan=False))
        return 0
    except (CalibrationError, OSError, KeyError, ValueError, TypeError) as exc:
        parser.exit(1, f'Bathymetry comparison failed: {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
