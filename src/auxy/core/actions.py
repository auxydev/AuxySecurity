"""GUI ve tray'in ortak eylem katmani: yetki yoksa UAC ister, sonucu geri dondurur.

Yukseltilmis islemler `python -m auxy <komut> ... --result <dosya>` olarak gizli pencerede,
UAC ile calisir; sonuc (JSON) yalnizca %TEMP%'te `auxy-result-` onekli dosyaya yazilir.
"""

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
    data: object = None


def result_path_allowed(path: str) -> bool:
    """Yukseltilmis surecin yazacagi sonuc dosyasi yalnizca gecici dizinde, bilinen on ekle olabilir."""
    p = Path(path).resolve()
    return p.parent == Path(tempfile.gettempdir()).resolve() and p.name.startswith(RESULT_PREFIX)


def write_result(path: str, ok: bool, message: str, changed: bool = False, data=None) -> None:
    if not result_path_allowed(path):
        raise ValueError("Gecersiz sonuc dosyasi yolu")
    Path(path).write_text(
        json.dumps({"ok": ok, "message": message, "changed": changed, "data": data}),
        encoding="utf-8",
    )


def run_elevated(args: list[str], denied_message: str = "Yönetici izni verilmedi.",
                 timeout_s: float = 120) -> ActionResult:
    """`auxy <args> --result <tmp>` komutunu UAC ile calistirip sonucunu okur."""
    fd, tmp = tempfile.mkstemp(prefix=RESULT_PREFIX, suffix=".json")
    os.close(fd)
    try:
        code = system.run_elevated_and_wait([*args, "--result", tmp], timeout_s)
        if code is None:
            return ActionResult(False, denied_message)
        try:
            data = json.loads(Path(tmp).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ActionResult(False, f"İşlem sonucu okunamadı (çıkış kodu {code}).")
        return ActionResult(bool(data["ok"]), str(data["message"]), bool(data.get("changed")),
                            data.get("data"))
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _describe(res) -> ActionResult:
    if res.changed:
        return ActionResult(True, f"{res.old} → {res.new}", True)
    return ActionResult(True, f"zaten {res.new}", False)


def cancel_scan() -> ActionResult:
    """Calisan taramayi iptal eder (yonetici gerekir; degilsek UAC ister)."""
    from auxy.core import scan

    if system.is_admin():
        code, out = scan.cancel_scan_command()
        ok = code == 0
        return ActionResult(ok, "Tarama iptal edildi." if ok else f"İptal edilemedi: {out.strip()[-200:]}")
    return run_elevated(["scan-cancel"], "Yönetici izni verilmedi; tarama iptal edilemedi.")


def apply_setting(key: str, value: str) -> ActionResult:
    """Defender ayarini uygular. Yonetici degilsek UAC penceresi acar (gizli yardimci surec)."""
    if system.is_admin():
        try:
            return _describe(DefenderService().set(key, value))
        except AuxyError as exc:
            return ActionResult(False, str(exc))
    return run_elevated(["set", key, value])


def apply_winsec(key: str, value: str) -> ActionResult:
    """Windows guvenlik ayari (guvenlik duvari, SmartScreen, Memory Integrity). Gerekirse UAC."""
    from auxy.core import winsec

    setting = winsec.WINSEC_SETTINGS.get(key)
    if setting is not None and not setting.needs_admin or system.is_admin():
        try:
            res = winsec.WinSecService().set(key, value)
        except AuxyError as exc:
            return ActionResult(False, str(exc))
        msg = f"{res.old} → {res.new}" if res.changed else f"zaten {res.new}"
        if res.changed and setting is not None and setting.reboot:
            msg += " (yeniden başlatma gerekir)"
        return ActionResult(True, msg, res.changed)
    return run_elevated(["winsec-set", key, value])


def autostart_op(op: str) -> ActionResult:
    """Oturum acilisinda baslatma gorevi: install / remove. Yonetici gerekir (degilsek UAC)."""
    from auxy.core import autostart

    if op not in ("install", "remove"):
        return ActionResult(False, f"Geçersiz işlem: {op!r}")
    if system.is_admin():
        try:
            autostart.install() if op == "install" else autostart.remove()
        except AuxyError as exc:
            return ActionResult(False, str(exc))
        return ActionResult(True, "Başlangıç görevi kuruldu." if op == "install" else "Başlangıç görevi kaldırıldı.", True)
    return run_elevated(["autostart", op])


def defender_quarantine_op(op: str, path: str = "", to_dir: str = "") -> ActionResult:
    """Defender karantinasi / tehdit temizleme / cevrimdisi tarama. Hepsi yonetici gerektirir (degilsek UAC).

    op: list | restore | clean | offline-scan.  offline-scan bilgisayari YENIDEN BASLATIR: cagiran onay almalidir.
    """
    from auxy.core import defender_quarantine as dq

    if op not in ("list", "restore", "clean", "offline-scan"):
        return ActionResult(False, f"Geçersiz işlem: {op!r}")
    try:
        if op == "restore":
            dq.validate_restore_path(path)  # gecersiz girdi UAC'ye hic gitmesin
        if system.is_admin():
            return dq.run_op(op, path, to_dir)
    except AuxyError as exc:
        return ActionResult(False, str(exc))
    args = ["defender-quarantine", op]
    if op == "restore":
        args.append(path)
        if to_dir:
            args += ["--to", to_dir]
    return run_elevated(args, timeout_s=300 if op == "offline-scan" else 120)


def exclusion_op(op: str, kind: str, value: str = "") -> ActionResult:
    """Defender dislamalari (list/add/remove). Hepsi yonetici gerektirir (okuma dahil)."""
    from auxy.core import exclusions

    if system.is_admin():
        try:
            return exclusions.run_op(op, kind, value)
        except AuxyError as exc:
            return ActionResult(False, str(exc))
    exclusions.validate_op(op, kind, value)  # gecersiz girdi UAC'ye hic gitmesin
    return run_elevated(["exclusion", op, kind, value])


def read_tpm() -> ActionResult:
    from auxy.core import winsec

    if system.is_admin():
        try:
            return ActionResult(True, "TPM okundu.", data=winsec.read_tpm())
        except AuxyError as exc:
            return ActionResult(False, str(exc))
    return run_elevated(["tpm-info"])
