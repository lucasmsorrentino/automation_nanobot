"""Structured logging setup for UFPR Automation.

Provides a pre-configured logger that writes structured JSON to a log file
and human-readable output to the console. All modules should import ``logger``
from this module instead of using ``print()`` for operational messages.

Usage:
    from ufpr_automation.utils.logging import logger

    logger.info("Pipeline started", extra={"emails": 5})
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from pythonjsonlogger import json as jsonlogger

# Log directory lives next to the ufpr_automation package
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
_LOG_DIR = _PACKAGE_ROOT / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_LOG_FILE = _LOG_DIR / "ufpr_automation.jsonl"

# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

_JSON_FORMAT = "%(asctime)s %(name)s %(levelname)s %(message)s"
_CONSOLE_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
_CONSOLE_DATE_FORMAT = "%H:%M:%S"


def _build_logger() -> logging.Logger:
    log = logging.getLogger("ufpr_automation")
    if log.handlers:
        return log  # already configured

    log.setLevel(logging.DEBUG)

    # --- JSON file handler (structured, for machine consumption) ---
    file_handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    json_formatter = jsonlogger.JsonFormatter(
        _JSON_FORMAT,
        rename_fields={"asctime": "timestamp", "levelname": "level"},
    )
    file_handler.setFormatter(json_formatter)
    log.addHandler(file_handler)

    # --- Console handler (human-readable) ---
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(_CONSOLE_FORMAT, datefmt=_CONSOLE_DATE_FORMAT)
    console_handler.setFormatter(console_formatter)
    log.addHandler(console_handler)

    return log


logger = _build_logger()
