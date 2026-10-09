import argparse
import json

from .workflow import export_comparison, load_config, run_comparison


def main():
    parser = argparse.ArgumentParser(description='Initial longitudinal bed-volume calibration tool')
    parser.add_argument('--config', required=True)
    parser.add_argument('--hdf', required=True)
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--before-survey')
    parser.add_argument('--after-survey')
    parser.add_argument('--before-index', type=int, default=0)
    parser.add_argument('--after-index', type=int, default=1)
    parser.add_argument('--output', default='output/bathymetry')
    args = parser.parse_args()
    if args.headless:
        result, provenance = run_comparison(load_config(args.config), args.hdf, args.before_survey,
                                           args.after_survey, args.before_index, args.after_index)
        saved = export_comparison(result, provenance, args.output)
        print(json.dumps({'metrics': result.metrics, 'export': str(saved)}, indent=2))
    else:
        from PySide6.QtWidgets import QApplication
        from .gui import CalibrationWindow
        app = QApplication([])
        window = CalibrationWindow(args.config, args.hdf)
        window.show()
        return app.exec()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
