"""
Logging setup. Call configure_logging() once at startup.
Logs go to both console and a rotating file in ~/.past_paper_extractor/logs/
"""

import logging
import logging.handlers
import os
from pathlib import Path


def configure_logging(level=logging.INFO):
    log_dir = Path.home() / ".past_paper_extractor" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "app.log"

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # File handler with rotation (5 files × 2MB)
    fh = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=2 * 1024 ** 2, backupCount=5, encoding="utf-8"
    )
    fh.setFormatter(fmt)

    # Console handler
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(fh)
    root.addHandler(ch)

    logging.info("Logging configured. Log file: %s", log_file)
