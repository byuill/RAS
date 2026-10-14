"""Exercise the user's direct-file launch from a copied create_BC folder."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.parametrize('launch', ['file', 'module'])
def test_standalone_gui_launch_calculates_without_repository_gui(tmp_path, launch):
    source = Path(__file__).parents[1]/'create_BC'
    copied = tmp_path/'Flow Boundary Conditions'/'create_BC'
    shutil.copytree(source, copied, ignore=shutil.ignore_patterns('output', 'legacy', '__pycache__'))
    # Replace only the blocking event loop: run the real launcher, create/show
    # the real window, and wait for the real bundled calibration to calculate.
    script = '''
import runpy
import sys
import time
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QThread

def no_dialog(*args):
    raise AssertionError(str(args[-1]))
QMessageBox.warning = no_dialog

def checked_event_loop(app):
    from create_BC.gui import BoundaryWindow
    windows = [w for w in app.topLevelWidgets() if isinstance(w, BoundaryWindow)]
    assert len(windows) == 1
    window = windows[0]
    deadline = time.monotonic()+30
    while time.monotonic() < deadline:
        app.processEvents()
        if window.result is not None and window.workers.idle():
            assert QThread.currentThread() == app.thread()
            assert len(window.result.flows) == 9497
            assert window.export_button.isEnabled()
            assert window.network.figure.axes
            assert 'gui' not in sys.modules
            window.close()
            print('STANDALONE_GUI_OK')
            return 0
        time.sleep(.01)
    raise AssertionError('Standalone GUI calculation did not finish')

QApplication.exec = checked_event_loop
'''
    if launch == 'file':
        script += "sys.argv = ['Generate_Discharge_BC_Ver3.py']\nrunpy.run_path(sys.argv[0], run_name='__main__')\n"
        cwd = copied
    else:
        script += "sys.argv = ['create_BC']\nrunpy.run_module('create_BC', run_name='__main__')\n"
        cwd = copied.parent
    environ = dict(os.environ, QT_QPA_PLATFORM='offscreen')
    environ.pop('PYTHONPATH', None)
    completed = subprocess.run([sys.executable, '-c', script], cwd=cwd, env=environ,
                               capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stdout+completed.stderr
    assert 'STANDALONE_GUI_OK' in completed.stdout
