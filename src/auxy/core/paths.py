"""Uygulama veri dizini. Testlerde AUXY_HOME ile degistirilebilir."""

from __future__ import annotations

import os
from pathlib import Path


def home() -> Path:
    override = os.environ.get("AUXY_HOME")
    base = Path(override) if override else Path(os.environ["LOCALAPPDATA"]) / "AuxySecurity"
    base.mkdir(parents=True, exist_ok=True)
    return base


def backup_file() -> Path:
    return home() / "backup.json"


def log_dir() -> Path:
    d = home() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d
