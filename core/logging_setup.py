"""Rotating-file logging setup."""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

_CONFIGURED = False


def setup_logging(log_dir: Path, level: int = logging.INFO) -> Path:
    """Configure the root logger once; returns the log file path."""
    global _CONFIGURED
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "workbench.log"
    if _CONFIGURED:
        return log_file
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(level)
    fh = logging.handlers.RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    sh.setLevel(logging.WARNING)
    root.addHandler(sh)
    for noisy in ("matplotlib", "PIL", "urllib3", "h5py"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _CONFIGURED = True
    logging.getLogger(__name__).info("Logging started; file=%s", log_file)
    return log_file
