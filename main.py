import sys
from pathlib import Path

# Insert project root to sys.path to allow imports like 'config', 'core'
project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from PySide6.QtWidgets import QApplication

from core.logging_setup import setup_logging
from config.settings import AppSettings, LOG_DIR
from gui.main_window import MainWindow

def main():
    setup_logging(LOG_DIR)
    
    settings = AppSettings.load()
    
    app = QApplication(sys.argv)
    app.setApplicationName("RAS Sediment Calibration Workbench")
    
    window = MainWindow(settings)
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
