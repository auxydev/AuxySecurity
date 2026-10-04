"""Defender dislamalari (yol / uzanti / islem): listele, ekle, kaldir. Hepsi yonetici gerektirir.

Degerler PowerShell koduna GOMULMEZ: ortam degiskeniyle (AUXY_ARG) aktarilir, komut metni sabittir.
Ekleme icin siki dogrulama vardir (tum surucu, Windows dizini, calistirilabilir uzantilar reddedilir).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from auxy.core import pshell
from auxy.core.actions import ActionResult
from auxy.core.log import get_logger
from auxy.core.service import AuxyError

KINDS = {"path": "ExclusionPath", "extension": "ExclusionExtension", "process": "ExclusionProcess"}
OPS = ("list", "add", "remove")
BLOCKED_EXTENSIONS = {
    "exe", "dll", "com", "scr", "bat", "cmd", "ps1", "vbs", "vbe", "js", "jse", "wsf", "hta",
    "msi", "jar", "lnk", "sys", "cpl", "reg", "pif", "py",
}
_CONTROL = re.compile(r"[\x00-\x1f]")


class ExclusionError(AuxyError):
    pass


def validate_path(value: str) -> str:
    if not value or _CONTROL.search(value):
        raise ExclusionError("Geçersiz yol.")
    if any(c in value for c in "*?"):
        raise ExclusionError("Joker karakterli (*, ?) yollar dışlama olarak eklenemez.")
    p = Path(value)
    if value.startswith("\\\\") or not p.is_absolute() or not p.drive:
        raise ExclusionError("Yalnızca yerel sürücüdeki tam yollar (C:\\klasor) eklenebilir.")
    if len(p.parts) <= 1:
        raise ExclusionError("Tüm sürücü dışlanamaz.")
    low = os.path.normcase(str(p))
    system_root = os.path.normcase(os.environ.get("SystemRoot", r"C:\Windows"))
    profile = os.path.normcase(os.environ.get("USERPROFILE", ""))
    users = os.path.normcase(str(Path(p.drive + "\\Users")))
    if low == system_root or low.startswith(system_root + "\\"):
        raise ExclusionError("Windows sistem dizini dışlanamaz.")
    if low in (profile, users) or low == os.path.normcase(os.environ.get("ProgramFiles", "")):
        raise ExclusionError("Bu kadar geniş bir konum dışlanamaz.")
    return str(p)


def validate_extension(value: str) -> str:
    ext = value.strip().lstrip(".").lower()
    if not re.fullmatch(r"[a-z0-9_]{1,10}", ext):
        raise ExclusionError("Geçersiz uzantı (1–10 harf/rakam).")
    if ext in BLOCKED_EXTENSIONS:
        raise ExclusionError(f".{ext} çalıştırılabilir/komut dosyası türü; dışlama olarak eklenemez.")
    return ext


def validate_process(value: str) -> str:
    v = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9_.\- ]{1,64}\.exe", v, re.IGNORECASE):
        raise ExclusionError("İşlem adı biçimi: ornek.exe")
    return v


_VALIDATORS = {"path": validate_path, "extension": validate_extension, "process": validate_process}


def validate_op(op: str, kind: str, value: str = "") -> str:
    """Girdiyi dogrular, temizlenmis degeri dondurur. Gecersizse ExclusionError."""
    if op not in OPS:
        raise ExclusionError(f"Geçersiz işlem: {op!r}")
    if kind not in KINDS:
        raise ExclusionError(f"Geçersiz dışlama türü: {kind!r}")
    if op == "list":
        return ""
    if op == "add":
        return _VALIDATORS[kind](value)
    # remove: listede zaten olan (baska yazilimin ekledigi) degerler de silinebilsin
    if not value or _CONTROL.search(value):
        raise ExclusionError("Geçersiz değer.")
    return value


def _powershell(command: str, arg: str = "") -> tuple[int, str, str]:
    return pshell.run(command, {"AUXY_ARG": arg})


def _as_list(value) -> list[str]:
    if value is None:
        return []
    return [value] if isinstance(value, str) else [str(v) for v in value]


def list_all(run=_powershell) -> dict[str, list[str]]:
    rc, out, err = run(
        "Get-MpPreference | Select-Object ExclusionPath,ExclusionExtension,ExclusionProcess "
        "| ConvertTo-Json -Compress"
    )
    if rc != 0:
        raise ExclusionError(f"Dışlamalar okunamadı: {err.strip() or rc}")
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        raise ExclusionError("Dışlama listesi ayrıştırılamadı.") from None
    result = {k: _as_list(data.get(p)) for k, p in KINDS.items()}
    if any(v.startswith("N/A") for lst in result.values() for v in lst):
        raise ExclusionError("Dışlamaları görmek için yönetici yetkisi gerekir.")
    return result


def run_op(op: str, kind: str, value: str = "", run=_powershell) -> ActionResult:
    clean = validate_op(op, kind, value)
    log = get_logger()
    if op == "list":
        data = list_all(run)
        return ActionResult(True, f"{sum(len(v) for v in data.values())} dışlama.", data=data)
    param = KINDS[kind]
    cmdlet = "Add-MpPreference" if op == "add" else "Remove-MpPreference"
    current = list_all(run)[kind]
    present = any(os.path.normcase(c) == os.path.normcase(clean) for c in current)
    if op == "add" and present:
        return ActionResult(True, "Zaten dışlamalarda.", False)
    if op == "remove" and not present:
        return ActionResult(True, "Dışlamalarda yok.", False)
    rc, _out, err = run(f"{cmdlet} -{param} $env:AUXY_ARG", clean)
    if rc != 0:
        log.error("dislama %s %s basarisiz: %s", op, kind, err.strip())
        raise ExclusionError(f"{cmdlet} başarısız: {err.strip() or rc}")
    after = list_all(run)[kind]
    now_present = any(os.path.normcase(c) == os.path.normcase(clean) for c in after)
    if now_present != (op == "add"):
        raise ExclusionError("Dışlama değişikliği uygulanmadı (Windows engelledi olabilir).")
    log.info("DISLAMA %s %s: %s", op, kind, clean)
    return ActionResult(True, "Eklendi." if op == "add" else "Kaldırıldı.", True)
