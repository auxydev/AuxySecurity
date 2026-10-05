"""Eski (Microsoft Store Python'un SANALLASTIRILMIS) veri dizininden gercek dizine tasima.

Gelistirme surumu Store Python ile calisirken `%LOCALAPPDATA%\\AuxySecurity` yazimlari Python paketinin ozel
`LocalCache` alanina yonlendirilir (kasa, anahtar yedegi kaydi, ayarlar orada durur). Paketlenmis surum
sanallastirilmaz ve GERCEK `%LOCALAPPDATA%\\AuxySecurity` dizinini kullanir; bu modul eski veriyi oraya KOPYALAR.

Guvenlik: eski veri SILINMEZ (kopya); hedefte var olan dosyanin uzerine YAZILMAZ; kasa anahtari DPAPI ile ayni
Windows kullanicisinda cozulebilir oldugundan (vault.key) oldugu gibi kopyalanir.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from auxy.core.log import get_logger

ITEMS = ("vault", "backup.json", "config.json", "scan_history.json")  # gunluk (logs) tasinmaz
MARKER = "migrated-from.txt"


@dataclass(frozen=True)
class Plan:
    source: Path
    target: Path
    to_copy: tuple[str, ...]
    blocked: tuple[str, ...]  # hedefte zaten var: dokunulmaz

    @property
    def needed(self) -> bool:
        return bool(self.to_copy)


def target_dir() -> Path:
    return Path(os.environ["LOCALAPPDATA"]) / "AuxySecurity"


def find_legacy_dirs() -> list[Path]:
    """Store Python sanallastirma alanlari (Packages\\PythonSoftwareFoundation.Python.*\\LocalCache\\Local\\AuxySecurity)."""
    base = Path(os.environ["LOCALAPPDATA"]) / "Packages"
    if not base.is_dir():
        return []
    found = []
    for pkg in base.glob("PythonSoftwareFoundation.Python.*"):
        d = pkg / "LocalCache" / "Local" / "AuxySecurity"
        if d.is_dir() and any(d.iterdir()):
            found.append(d)
    return found


def _non_empty(p: Path) -> bool:
    return p.exists() and (p.is_file() or any(p.iterdir()))


def make_plan(source: Path, target: Path | None = None) -> Plan:
    target = target or target_dir()
    to_copy, blocked = [], []
    for name in ITEMS:
        if not _non_empty(source / name):
            continue
        (blocked if _non_empty(target / name) else to_copy).append(name)
    return Plan(source, target, tuple(to_copy), tuple(blocked))


def pending_plan() -> Plan | None:
    """Tasinacak eski veri var mi? (Sanallastirilmamis surecten cagrilmali: gelistirme surumunde eski=yeni gorunur)."""
    target = target_dir().resolve()
    for src in find_legacy_dirs():
        if src.resolve() == target:
            continue
        plan = make_plan(src, target)
        if plan.needed:
            return plan
    return None


def migrate(plan: Plan) -> list[str]:
    """Plani uygular (KOPYA). Yapilan adimlarin aciklamalarini dondurur; hata olursa o ogeyi atlar ve bildirir."""
    log = get_logger()
    plan.target.mkdir(parents=True, exist_ok=True)
    done: list[str] = []
    for name in plan.to_copy:
        src, dst = plan.source / name, plan.target / name
        try:
            if _non_empty(dst):
                done.append(f"{name}: atlandı (hedefte zaten var)")
                continue
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)
            done.append(f"{name}: kopyalandı")
            log.info("VERI TASIMA %s: %s -> %s", name, src, dst)
        except OSError as exc:
            done.append(f"{name}: HATA ({exc})")
            log.error("veri tasima hatasi (%s): %s", name, exc)
    (plan.target / MARKER).write_text(f"{plan.source}\n", encoding="utf-8")
    return done
