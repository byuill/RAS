"""Run the desktop workbench or reproducible command-line exports."""
import argparse
from pathlib import Path

from .engine import calculate_budget
from .export import export_result
from .parameters import Parameters


def main(argv=None):
    base = Path(__file__).parent
    parser = argparse.ArgumentParser(description='Lower Mississippi discharge boundary condition workbench')
    parser.add_argument('--input', default=str(base/'new_data_RF.csv'), help='Continuous daily input CSV, cfs')
    parser.add_argument('--splits', help='Month-column MMR/Ohio CSV (defaults to selected water/calendar year file)')
    parser.add_argument('--parameters', help='Scenario JSON; unknown parameters are rejected')
    parser.add_argument('--headless', action='store_true', help='Calculate and export without a desktop')
    parser.add_argument('--output', default=str(base/'output'))
    parser.add_argument('--dss', action='store_true', help='Also export and verify HEC-DSS')
    parser.add_argument('--stage', help='Optional daily date,stage_ft CSV in verified model datum')
    parser.add_argument('--scenario', default='Cal', help='DSS F-part scenario label')
    args = parser.parse_args(argv)
    try:
        p = Parameters.load(args.parameters) if args.parameters else Parameters()
        if args.headless:
            result = calculate_budget(args.input, args.splits, p)
            path = export_result(result, args.output, scenario=args.scenario, include_dss=args.dss, stage=args.stage)
            print(f'{result.summary["days"]:,} days processed. Export: {path}')
            print('Maximum residuals (cfs):', result.summary['max_abs_residual_cfs'])
            return 0
        from PySide6.QtWidgets import QApplication
        from .gui import BoundaryWindow
        app = QApplication([])
        window = BoundaryWindow(args.input, p)
        if args.splits:
            window.split_edit.setText(args.splits)
        if args.stage:
            window.stage_edit.setText(args.stage)
        window.scenario_edit.setText(args.scenario)
        window.show()
        return app.exec()
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(1, f'Boundary calculation failed: {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
