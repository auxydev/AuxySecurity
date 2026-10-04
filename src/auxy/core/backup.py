"""Degistirilen ayarlarin ORIJINAL degerlerini saklar (revert icin).

Bir anahtar icin ilk degisiklikte orijinal kaydedilir; sonraki degisiklikler
ustune yazmaz, boylece revert her zaman kullanicinin baslangic durumuna doner.
"""

from __future__ import annotations

import json
import os

from auxy.core import paths


def load() -> dict:
    try:
        return json.loads(paths.backup_file().read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write(data: dict) -> None:
    target = paths.backup_file()
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, target)


def remember_original(key: str, raw) -> bool:
    """Orijinali yalnizca daha once kaydedilmediyse yazar. Yazildiysa True."""
    data = load()
    if key in data:
        return False
    data[key] = raw
    _write(data)
    return True


def get_value(key: str, default=None):
    return load().get(key, default)


def set_value(key: str, value) -> None:
    """Orijinal-koruma kurali OLMADAN dogrudan yaz (liste gibi durum verileri icin)."""
    data = load()
    data[key] = value
    _write(data)


def forget(key: str) -> None:
    data = load()
    if key in data:
        del data[key]
        _write(data)
