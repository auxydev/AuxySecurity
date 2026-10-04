"""GUI ve tray'in ortak eylem katmani: yetki yoksa UAC ister, sonucu geri dondurur."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from auxy.core import system
from auxy.core.service import AuxyError, DefenderService

RESULT_PREFIX = "auxy-result-"


@dataclass(frozen=True)
class ActionResult:
    ok: bool
    message: str
    changed: bool = False


def result_path_allowed(path: str) -> bool:
    """Yukseltilmis surecin yazacagi sonuc dosyasi yalnizca gecici dizinde, bilinen on ekle olabilir."""
    p = Path(path).resolve()
    return p.parent == Path(tempfile.gettempdir()).resolve() and p.name.startswith(RESULT_PREFIX)


def write_result(path: str, ok: bool, message: str, changed: bool = False) -> None:
    if not result_path_allowed(path):
        raise ValueError("Gecersiz sonuc dosyasi yolu")
    Path(path).write_text(
        json.dumps({"ok": ok, "message": message, "changed": changed}), encoding="utf-8"
    )


def _describe(res) -> ActionResult:
    if res.changed:
        return ActionResult(True, f"{res.old} → {res.new}", True)
    return ActionResult(True, f"zaten {res.new}", False)


def apply_setting(key: str, value: str) -> ActionResult:
    """Ayari uygular. Yonetici degilsek UAC penceresi acar (gizli yardimci surec)."""
    if system.is_admin():
        try:
            return _describe(DefenderService().set(key, value))
        except AuxyError as exc:
            return ActionResult(False, str(exc))

    fd, tmp = tempfile.mkstemp(prefix=RESULT_PREFIX, suffix=".json")
    os.close(fd)
    try:
        code = system.run_elevated_and_wait(["set", key, value, "--result", tmp])
        if code is None:
            return ActionResult(False, "Yönetici izni verilmedi.")
        try:
            data = json.loads(Path(tmp).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ActionResult(False, f"İşlem sonucu okunamadı (çıkış kodu {code}).")
        return ActionResult(bool(data["ok"]), str(data["message"]), bool(data.get("changed")))
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
