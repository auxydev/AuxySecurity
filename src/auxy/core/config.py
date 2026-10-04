"""Kullanici ayarlari (config.json). GUI yazar; tray ajani degisikligi aninda uygular.

Varsayilanlar bilerek temkinli: pahali/uyari cikaran ozellikler kapali, yalnizca tehdit bildirimi acik.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from auxy.core import paths

WEEKDAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]  # 0 = Pazartesi
SCAN_KINDS = ("quick", "full")


def downloads_folder() -> str:
    try:
        from win32com.shell import shell, shellcon

        return str(shell.SHGetKnownFolderPath(shellcon.FOLDERID_Downloads, 0, None))
    except Exception:
        return str(Path.home() / "Downloads")


@dataclass
class ScheduledScan:
    enabled: bool = False
    weekday: int = 6  # Pazar
    hour: int = 3
    kind: str = "quick"


@dataclass
class Config:
    watch_enabled: bool = False
    watch_folders: list[str] = field(default_factory=list)  # bos = Indirilenler
    event_notifications: bool = True
    usb_scan: bool = False
    scheduled: ScheduledScan = field(default_factory=ScheduledScan)

    def effective_watch_folders(self) -> list[str]:
        return [f for f in (self.watch_folders or [downloads_folder()]) if f]

    # ---- dogrulama ----
    def sanitized(self) -> Config:
        s = self.scheduled
        sched = ScheduledScan(
            enabled=bool(s.enabled),
            weekday=s.weekday if isinstance(s.weekday, int) and 0 <= s.weekday <= 6 else 6,
            hour=s.hour if isinstance(s.hour, int) and 0 <= s.hour <= 23 else 3,
            kind=s.kind if s.kind in SCAN_KINDS else "quick",
        )
        folders = [str(f) for f in self.watch_folders if isinstance(f, str) and f][:20]
        return Config(bool(self.watch_enabled), folders, bool(self.event_notifications),
                      bool(self.usb_scan), sched)


def _from_dict(raw: dict) -> Config:
    base = Config()
    sched_raw = raw.get("scheduled", {}) if isinstance(raw.get("scheduled"), dict) else {}
    sched = ScheduledScan(**{f.name: sched_raw.get(f.name, getattr(base.scheduled, f.name))
                             for f in fields(ScheduledScan)})
    kwargs = {f.name: raw.get(f.name, getattr(base, f.name)) for f in fields(Config) if f.name != "scheduled"}
    return Config(**kwargs, scheduled=sched).sanitized()


def config_file() -> Path:
    return paths.home() / "config.json"


def load() -> Config:
    try:
        raw = json.loads(config_file().read_text(encoding="utf-8"))
        return _from_dict(raw if isinstance(raw, dict) else {})
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        return Config()


def save(cfg: Config) -> None:
    target = config_file()
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(cfg.sanitized()), indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, target)
