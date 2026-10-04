"""Yapilandirmaya gore yardimci bilesenleri baslatir/durdurur (yalnizca degisenleri)."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from auxy.agent import watchers
from auxy.core import config as cfgmod
from auxy.core import scan
from auxy.core.log import get_logger


@dataclass
class LastThreat:
    name: str
    path: str
    when: datetime
    handled: bool = False

    def quarantinable(self) -> bool:
        return bool(self.path) and not self.handled and Path(self.path).is_file()


class HelperManager:
    def __init__(self, manager: scan.ScanManager, notify: Callable[[str], None],
                 factories: dict | None = None):
        self._manager = manager
        self._notify = notify
        self._running: dict[str, tuple[tuple, object]] = {}
        self._lock = threading.Lock()
        self._cfg = cfgmod.Config()
        self.last_threat: LastThreat | None = None
        self._log = get_logger()
        # testlerde degistirilebilir
        self._factories = factories or {
            "watch": lambda c: watchers.FolderWatcher(c.effective_watch_folders(), self._manager,
                                                      self._notify, self._remember_threat_from_scan,
                                                      c.watch_recursive),
            "events": lambda c: watchers.DefenderEventListener(self._on_event),
            "usb": lambda c: watchers.UsbWatcher(self._manager, self._notify),
            "schedule": lambda c: watchers.ScheduledScanner(c.scheduled, self._manager, self._notify),
        }

    @staticmethod
    def signatures(cfg: cfgmod.Config) -> dict[str, tuple | None]:
        """Bilesen -> imza (None: kapali). Imza degisince bilesen yeniden baslatilir."""
        s = cfg.scheduled
        return {
            "watch": (tuple(cfg.effective_watch_folders()), cfg.watch_recursive) if cfg.watch_enabled else None,
            "events": () if cfg.event_notifications else None,
            "usb": () if cfg.usb_scan else None,
            "schedule": (s.weekday, s.hour, s.kind) if s.enabled else None,
        }

    def apply(self, cfg: cfgmod.Config) -> None:
        with self._lock:
            self._cfg = cfg
            for name, sig in self.signatures(cfg).items():
                current = self._running.get(name)
                if current is not None and current[0] == sig:
                    continue
                if current is not None:
                    self._stop_component(name, current[1])
                    del self._running[name]
                if sig is None:
                    continue
                try:
                    comp = self._factories[name](cfg)
                    comp.start()
                    self._running[name] = (sig, comp)
                except Exception as exc:  # bir bilesen hatasi digerlerini durdurmasin
                    self._log.error("yardimci %s baslatilamadi: %s", name, exc)
                    self._notify(f"'{name}' yardımcısı başlatılamadı: {exc}")

    def stop_all(self) -> None:
        with self._lock:
            for name, (_sig, comp) in list(self._running.items()):
                self._stop_component(name, comp)
            self._running.clear()

    def _stop_component(self, name: str, comp) -> None:
        try:
            comp.stop()
        except Exception as exc:
            self._log.warning("yardimci %s durdurulamadi: %s", name, exc)

    @property
    def running(self) -> list[str]:
        return sorted(self._running)

    # ---- olaylar ----
    def _on_event(self, ev: watchers.DefenderEvent) -> None:
        if ev.event_id == 1116:
            self.last_threat = LastThreat(ev.threat, ev.path, datetime.now())
            if self._cfg.event_notifications:
                where = f"\n{Path(ev.path).name}" if ev.path else ""
                self._notify(f"Tehdit bulundu: {ev.threat} ({ev.severity}){where}")
        elif ev.event_id == 1117 and self.last_threat and self.last_threat.name == ev.threat:
            self.last_threat.handled = True  # Defender kendisi islem uyguladi

    def _remember_threat_from_scan(self, name: str, paths: list[str]) -> None:
        self.last_threat = LastThreat(name, paths[0] if paths else "", datetime.now())
