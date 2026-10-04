"""Boşta duran tray ajani: olay/zamanlayici tabanli, GUI'yi istek uzerine ayri surecte acar."""

from __future__ import annotations

import os
import subprocess
import threading

from auxy.core import actions, defender, system
from auxy.core.log import get_logger
from auxy.core.settings import READONLY_KEYS, SETTINGS, TOGGLE_KEYS
from auxy.gui import viewmodel as vm

REFRESH_S = 60  # dakikada bir (~100 ms WMI); aradaki sure tamamen uykuda
WINSEC_URI = "windowsdefender://threatsettings"
VALUE_TR = {"on": "Açık", "off": "Kapalı", "audit": "Denetim", "basic": "Temel",
            "advanced": "Gelişmiş"}


def tooltip(health: vm.Health | None) -> str:
    return "AuxySecurity – " + (health.title if health else "Durum okunamadı")[:100]


class Agent:
    def __init__(self):
        import pystray  # gec import

        self._pystray = pystray
        self._log = get_logger()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self.status: defender.DefenderStatus | None = None
        self.health: vm.Health | None = None
        from auxy.agent.icon import make_icon

        self._make_icon = make_icon
        self.icon = pystray.Icon(
            "AuxySecurity", make_icon(None), tooltip(None), menu=pystray.Menu(self._menu_items)
        )

    # ---- durum ----
    def refresh(self) -> None:
        try:
            self.status = defender.read_status()
            self.health = vm.evaluate(self.status)
        except Exception as exc:  # WMI gecici hatasi ajani dusurmesin
            self._log.warning("tray durum okunamadi: %s", exc)
            self.status = self.health = None
        self.icon.icon = self._make_icon(self.health.level if self.health else None)
        self.icon.title = tooltip(self.health)
        self.icon.update_menu()

    def _loop(self) -> None:
        self.refresh()
        while not self._stop.is_set():
            self._wake.wait(REFRESH_S)  # uykuda bekler, CPU kullanmaz
            self._wake.clear()
            if self._stop.is_set():
                break
            self.refresh()

    # ---- menu ----
    def _value_name(self, key: str) -> str | None:
        if self.status is None:
            return None
        s = SETTINGS[key]
        return s.name_of(self.status.prefs[s.pref_field])

    def _menu_items(self):
        item, sep = self._pystray.MenuItem, self._pystray.Menu.SEPARATOR
        yield item(self.health.title if self.health else "Durum okunamadı", None, enabled=False)
        yield sep
        yield item("Paneli aç", self.open_gui, default=True)
        yield sep
        for key in TOGGLE_KEYS:
            yield item(
                SETTINGS[key].label,
                self._toggle_action(key),
                checked=self._checked(key),
                enabled=self.status is not None,
            )
        yield sep
        for key in READONLY_KEYS:
            name = self._value_name(key)
            text = f"{SETTINGS[key].label}: {VALUE_TR.get(name, name) if name else '?'}"
            yield item(text, None, enabled=False)
        yield sep
        yield item("Windows Security'yi aç", lambda *_: os.startfile(WINSEC_URI))
        yield item("Yenile", lambda *_: self._wake.set())
        yield item("Çıkış", self.quit)

    # pystray, eylem/checked fonksiyonlarinin tam parametre sayisini denetler
    # (varsayilan degerli lambda kabul etmez); bu yuzden fabrika kullaniyoruz.
    def _toggle_action(self, key: str):
        def action(icon, item):
            self._start(self._toggle, key)

        return action

    def _checked(self, key: str):
        def checked(item):
            return self._value_name(key) in ("on", "audit")

        return checked

    # ---- eylemler ----
    @staticmethod
    def _start(fn, *args) -> None:
        threading.Thread(target=fn, args=args, daemon=True).start()

    def _toggle(self, key: str) -> None:
        value = "off" if self._value_name(key) in ("on", "audit") else "on"
        res = actions.apply_setting(key, value)
        label = SETTINGS[key].label
        self.icon.notify(res.message if not res.ok else f"{label}: {res.message}", "AuxySecurity")
        self.refresh()

    def open_gui(self, *_args) -> None:
        flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
        subprocess.Popen(
            [system.python_exe(windowless=True), "-m", "auxy", "gui"],
            creationflags=flags, close_fds=True,
        )

    def quit(self, *_args) -> None:
        self._stop.set()
        self._wake.set()
        self.icon.stop()

    def run(self) -> int:
        threading.Thread(target=self._loop, daemon=True).start()
        self.icon.run()  # ana is parcacigini bloke eder (mesaj dongusu)
        return 0


def run() -> int:
    if not system.acquire_single_instance("AuxySecurityAgent"):
        return 0
    get_logger().info("Ajan basladi (pid=%s, yonetici=%s)", os.getpid(), system.is_admin())
    return Agent().run()
