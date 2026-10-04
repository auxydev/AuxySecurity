"""Donen dosya gunlugu (denetim kaydi dahil)."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from auxy.core import paths

_configured = False


def get_logger() -> logging.Logger:
    global _configured
    logger = logging.getLogger("auxy")
    if not _configured:
        logger.setLevel(logging.INFO)
        handler = RotatingFileHandler(
            paths.log_dir() / "auxy.log", maxBytes=512_000, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        _configured = True
    return logger
