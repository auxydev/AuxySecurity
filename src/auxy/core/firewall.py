"""Guvenlik duvari KURALLARI: listele, pasiflestir / yeniden etkinlestir, program engelle / engeli kaldir.

Guvenlik ilkeleri:
- Degerler PowerShell komut metnine GOMULMEZ: ortam degiskeniyle (AUXY_ARG, AUXY_NAME, AUXY_DISP) aktarilir.
- Yalnizca GERI ALINABILIR islemler: bir kurali yalnizca ETKINKEN pasiflestirebilir, yalnizca BIZIM
  pasiflestirdigimiz kurali yeniden etkinlestirebiliriz; silme yok. Engel kurallari yalnizca `AuxySecurity-` onekli.
- Listeleme yonetici gerektirmez; degistirme gerektirir (UAC akisi actions.firewall_op).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from auxy.core import backup, pshell
from auxy.core.actions import ActionResult
from auxy.core.log import get_logger
from auxy.core.service import AuxyError

OPS = ("list", "list-blocks", "disable", "enable", "block", "unblock")
DISABLED_KEY = "fwrules"  # backup.json: bizim pasiflestirdigimiz kural adlari
BLOCK_PREFIX = "AuxySecurity-"
_BLOCK_NAME = re.compile(r"^AuxySecurity-(in|out)-[0-9a-f]{12}$")
_CONTROL = re.compile(r"[\x00-\x1f]")


class FirewallError(AuxyError):
    pass


@dataclass(frozen=True)
class FirewallRule:
    name: str
    display_name: str
    profile: str
    program: str
    group: str

    def to_dict(self) -> dict:
        return asdict(self)


_LIST_SCRIPT = (
    "$all = Get-NetFirewallApplicationFilter -All; $map = @{}; foreach($a in $all){ $map[$a.InstanceID] = $a.Program }; "
    "$rules = @@RULES@@; "
    "$out = foreach($r in $rules){ [pscustomobject]@{ Name=$r.Name; DisplayName=$r.DisplayName; "
    "Profile=[string]$r.Profile; Program=$map[$r.Name]; Group=$r.DisplayGroup } }; "
    "if($out){ ConvertTo-Json -InputObject @($out) -Compress } else { '[]' }"
)
_ENABLED_INBOUND_ALLOW = "Get-NetFirewallRule -Enabled True -Direction Inbound -Action Allow"
_OUR_BLOCKS = "Get-NetFirewallRule -Name 'AuxySecurity-*' -ErrorAction SilentlyContinue"


def _ps(command: str, env: dict[str, str] | None = None) -> tuple[int, str, str]:
    return pshell.run(command, env, timeout=120)


def _parse(out: str) -> list[FirewallRule]:
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        raise FirewallError("Kural listesi ayrıştırılamadı.") from None
    if isinstance(data, dict):
        data = [data]
    return [FirewallRule(str(d.get("Name") or ""), str(d.get("DisplayName") or d.get("Name") or ""),
                         str(d.get("Profile") or ""), str(d.get("Program") or ""), str(d.get("Group") or ""))
            for d in data if d.get("Name")]


def list_rules(run: Callable = _ps) -> list[FirewallRule]:
    """Etkin, gelen, izin veren kurallar (kapatilabilecek olanlar). Yonetici gerekmez."""
    rc, out, err = run(_LIST_SCRIPT.replace("@@RULES@@", _ENABLED_INBOUND_ALLOW))
    if rc != 0:
        raise FirewallError(f"Kurallar okunamadı: {err.strip() or rc}")
    return _parse(out)


def list_blocks(run: Callable = _ps) -> list[FirewallRule]:
    """Bizim olusturdugumuz engel kurallari (AuxySecurity-*)."""
    rc, out, err = run(_LIST_SCRIPT.replace("@@RULES@@", _OUR_BLOCKS))
    if rc != 0:
        raise FirewallError(f"Engel kuralları okunamadı: {err.strip() or rc}")
    return _parse(out)


def disabled_by_us() -> list[str]:
    value = backup.get_value(DISABLED_KEY, [])
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _remember_disabled(name: str, add: bool) -> None:
    current = [n for n in disabled_by_us() if n != name]
    if add:
        current.append(name)
    backup.set_value(DISABLED_KEY, current) if current else backup.forget(DISABLED_KEY)


def _clean_name(name: str) -> str:
    if not name or _CONTROL.search(name) or len(name) > 256:
        raise FirewallError("Geçersiz kural adı.")
    return name


def disable_rule(name: str, run: Callable = _ps) -> ActionResult:
    name = _clean_name(name)
    if name.startswith(BLOCK_PREFIX):
        raise FirewallError("AuxySecurity engel kuralları buradan pasifleştirilemez (engeli kaldır).")
    if name not in {r.name for r in list_rules(run)}:
        raise FirewallError("Bu kural etkin, gelen, izin veren kurallar arasında değil.")
    _remember_disabled(name, True)  # ONCE kaydet: yarida kesilse bile geri alinabilsin
    rc, _o, err = run("Set-NetFirewallRule -Name $env:AUXY_ARG -Enabled False", {"AUXY_ARG": name})
    if rc != 0:
        _remember_disabled(name, False)
        raise FirewallError(f"Set-NetFirewallRule başarısız: {err.strip() or rc}")
    if name in {r.name for r in list_rules(run)}:  # hala etkin: uygulanmadi
        _remember_disabled(name, False)
        raise FirewallError("Kural pasifleştirilemedi (değişiklik uygulanmadı).")
    get_logger().info("GUVENLIK DUVARI kural pasiflestirildi: %s", name)
    return ActionResult(True, "Kural pasifleştirildi (geri alınabilir).", True)


def enable_rule(name: str, run: Callable = _ps) -> ActionResult:
    name = _clean_name(name)
    if name not in disabled_by_us():
        raise FirewallError("Bu kuralı biz pasifleştirmedik; yalnızca kendi pasifleştirdiklerimiz geri açılır.")
    rc, _o, err = run("Set-NetFirewallRule -Name $env:AUXY_ARG -Enabled True", {"AUXY_ARG": name})
    if rc != 0:
        raise FirewallError(f"Set-NetFirewallRule başarısız: {err.strip() or rc}")
    if name not in {r.name for r in list_rules(run)}:
        raise FirewallError("Kural yeniden etkinleştirilemedi (değişiklik uygulanmadı).")
    _remember_disabled(name, False)
    get_logger().info("GUVENLIK DUVARI kural yeniden etkinlestirildi: %s", name)
    return ActionResult(True, "Kural yeniden etkinleştirildi.", True)


# ---------------- program engelleme ----------------
def validate_program(path: str) -> str:
    if not path or _CONTROL.search(path):
        raise FirewallError("Geçersiz yol.")
    p = Path(path)
    if not p.is_absolute() or not p.drive or path.startswith("\\\\") or any(c in path for c in "*?"):
        raise FirewallError("Yalnızca yerel sürücüdeki tam dosya yolları engellenebilir.")
    if not p.is_file():
        raise FirewallError("Dosya bulunamadı.")
    system_root = os.path.normcase(os.environ.get("SystemRoot", r"C:\Windows"))
    low = os.path.normcase(str(p))
    if low.startswith(system_root + "\\"):
        raise FirewallError("Windows sistem dosyaları engellenemez (sistemi bozabilir).")
    return str(p)


def rule_names_for(path: str) -> tuple[str, str]:
    h = hashlib.sha1(os.path.normcase(path).encode("utf-8")).hexdigest()[:12]
    return f"{BLOCK_PREFIX}in-{h}", f"{BLOCK_PREFIX}out-{h}"


def block_program(path: str, run: Callable = _ps) -> ActionResult:
    clean = validate_program(path)
    in_name, out_name = rule_names_for(clean)
    existing = {r.name for r in list_blocks(run)}
    if {in_name, out_name} <= existing:
        return ActionResult(True, "Bu program zaten engelli.", False)
    disp = f"AuxySecurity: Engelle – {Path(clean).name}"
    for name, direction in ((in_name, "Inbound"), (out_name, "Outbound")):
        if name in existing:
            continue
        rc, _o, err = run(
            f"New-NetFirewallRule -Name $env:AUXY_NAME -DisplayName $env:AUXY_DISP -Direction {direction} "
            "-Action Block -Program $env:AUXY_ARG -Profile Any -Enabled True",
            {"AUXY_NAME": name, "AUXY_DISP": disp, "AUXY_ARG": clean},
        )
        if rc != 0:
            raise FirewallError(f"New-NetFirewallRule başarısız: {err.strip() or rc}")
    after = {r.name for r in list_blocks(run)}
    if not {in_name, out_name} <= after:
        raise FirewallError("Engel kuralları oluşturulamadı (değişiklik uygulanmadı).")
    get_logger().info("GUVENLIK DUVARI program engellendi: %s", clean)
    return ActionResult(True, "Program gelen ve giden bağlantılar için engellendi.", True)


def unblock_program(path_or_rule: str, run: Callable = _ps) -> ActionResult:
    """Yol (engellenen program) ya da kural adi (AuxySecurity-in-/out-<hash>) verilebilir."""
    value = _clean_name(path_or_rule)
    if _BLOCK_NAME.match(value):
        suffix = value.rsplit("-", 1)[1]
        names = (f"{BLOCK_PREFIX}in-{suffix}", f"{BLOCK_PREFIX}out-{suffix}")
    else:
        names = rule_names_for(validate_path_for_unblock(value))
    present = {r.name for r in list_blocks(run)}
    todo = [n for n in names if n in present]
    if not todo:
        return ActionResult(True, "Bu program için engel kuralı yok.", False)
    for name in todo:
        if not _BLOCK_NAME.match(name):  # savunma: yalnizca bizim adlar silinir
            raise FirewallError("Geçersiz engel kuralı adı.")
        rc, _o, err = run("Remove-NetFirewallRule -Name $env:AUXY_ARG", {"AUXY_ARG": name})
        if rc != 0:
            raise FirewallError(f"Remove-NetFirewallRule başarısız: {err.strip() or rc}")
    if {r.name for r in list_blocks(run)} & set(todo):
        raise FirewallError("Engel kaldırılamadı (değişiklik uygulanmadı).")
    get_logger().info("GUVENLIK DUVARI engel kaldirildi: %s", value)
    return ActionResult(True, "Engel kaldırıldı.", True)


def unblock_name_or_path_check(value: str) -> str:
    """UAC acilmadan once: kural adi ya da mutlak yol olmali."""
    value = _clean_name(value)
    if _BLOCK_NAME.match(value):
        return value
    return validate_path_for_unblock(value)


def validate_path_for_unblock(path: str) -> str:
    """Engel kaldirirken dosyanin hala var olmasi gerekmez (silinmis programin engeli de kalkabilsin)."""
    if not path or _CONTROL.search(path) or not Path(path).is_absolute():
        raise FirewallError("Geçersiz yol ya da kural adı.")
    return str(Path(path))


def run_op(op: str, value: str = "") -> ActionResult:
    if op == "list":
        rules = list_rules()
        return ActionResult(True, f"{len(rules)} kural.", data=[r.to_dict() for r in rules])
    if op == "list-blocks":
        rules = list_blocks()
        return ActionResult(True, f"{len(rules)} engel kuralı.", data=[r.to_dict() for r in rules])
    if op == "disable":
        return disable_rule(value)
    if op == "enable":
        return enable_rule(value)
    if op == "block":
        return block_program(value)
    if op == "unblock":
        return unblock_program(value)
    raise FirewallError(f"Geçersiz işlem: {op!r}")
