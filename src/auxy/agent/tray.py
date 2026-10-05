"""Boşta duran tray ajani: olay/zamanlayici tabanli, GUI'yi istek uzerine ayri surecte acar."""

from __future__ import annotations

import os
import subprocess
import threading

from auxy.agent.helpers import HelperManager
from auxy.core import actions, defender, system
from auxy.core import config as cfgmod
from auxy.core.log import get_logger
from auxy.core.settings import SETTINGS, TOGGLE_KEYS
from auxy.core.winsec import WINSEC_SETTINGS, WinSecService

FW_KEYS = ("fw_domain", "fw_private", "fw_public")
FW_LABELS = {"fw_domain": "Etki alanı ağı", "fw_private": "Özel ağ", "fw_public": "Genel ağ"}
from auxy.gui import viewmodel as vm

REFRESH_S = 60  # dakikada bir (~100 ms WMI); aradaki sure tamamen uykuda
VALUE_TR = {"on": "Açık", "off": "Kapalı", "audit": "Denetim", "basic": "Temel",
            "advanced": "Gelişmiş"}


def tooltip(health: vm.Health | None) -> str:
    if health is None:
        return "AuxySecurity – Durum okunamadı"
    kind = "kritik sorun" if health.crit_count else "uyarı"
    extra = f" ({health.badge} {kind})" if health.badge else ""
    return ("AuxySecurity – " + health.title + extra)[:120]


class Agent:
    def __init__(self):
        import pystray  # gec import

        self._pystray = pystray
        self._log = get_logger()
        from auxy.core.scan import ScanManager

        self._scans = ScanManager()
        self._helpers = HelperManager(self._scans, self._notify)
        self._config_waiter = system.ConfigWaiter()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self.status: defender.DefenderStatus | None = None
        self.health: vm.Health | None = None
        self.fw: dict[str, str] = {}
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
        try:
            self.fw = WinSecService().get_many(FW_KEYS)  # yalnizca kayit defteri, hafif
        except Exception as exc:
            self._log.info("guvenlik duvari durumu okunamadi: %s", exc)
            self.fw = {}
        self.icon.icon = self._make_icon(self.health.level if self.health else None,
                                         self.health.badge if self.health else 0)
        self.icon.title = tooltip(self.health)
        self.icon.update_menu()
        system.trim_working_set()  # bekleme oncesi: calisma kumesini kucult (bkz. system.trim_working_set)

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
        yield item("Hızlı tara", self._quick_scan_action, enabled=self._scan_enabled)
        lt = self._helpers.last_threat
        if lt is not None and lt.quarantinable():
            yield item(f"Tehdidi kasaya al: {lt.name}"[:90], self._quarantine_last_action)
        yield sep
        for key in TOGGLE_KEYS:
            yield item(
                SETTINGS[key].label,
                self._toggle_action(key),
                checked=self._checked(key),
                enabled=self.status is not None,
            )
        yield item(
            "Güvenlik duvarı",
            self._pystray.Menu(*(
                item(FW_LABELS[k], self._fw_action(k), checked=self._fw_checked(k)) for k in FW_KEYS)),
            enabled=bool(self.fw),
        )
        yield item(
            SETTINGS["maps"].label,
            self._pystray.Menu(*(
                item(shown, self._maps_action(value), checked=self._maps_checked(value), radio=True)
                for shown, value in (("Kapalı", "off"), ("Temel", "basic"), ("Gelişmiş", "advanced"))
            )),
            enabled=self.status is not None,
        )
        yield sep
        yield item("Yenile", lambda *_: self._wake.set())
        yield item("Çıkış", self.quit)

    # pystray, eylem/checked fonksiyonlarinin tam parametre sayisini denetler
    # (varsayilan degerli lambda kabul etmez); bu yuzden fabrika kullaniyoruz.
    def _toggle_action(self, key: str):
        def action(icon, item):
            self._start(self._toggle, key)

        return action

    def _fw_checked(self, key: str):
        def checked(item):
            return self.fw.get(key) == "on"

        return checked

    def _fw_action(self, key: str):
        def action(icon, item):
            self._start(self._toggle_fw, key)

        return action

    def _toggle_fw(self, key: str) -> None:
        turning_off = self.fw.get(key) == "on"
        if turning_off and not system.confirm_dialog(
                f"{WINSEC_SETTINGS[key].label} KAPATILACAK.\nBilgisayarın ağdan gelen saldırılara açık kalır.\n\nDevam edilsin mi?"):
            return
        res = actions.apply_winsec(key, "off" if turning_off else "on")
        self._notify(f"{WINSEC_SETTINGS[key].label}: {res.message}")
        self.refresh()

    def _maps_action(self, value: str):
        def action(icon, item):
            self._start(self._apply, "maps", value)

        return action

    def _maps_checked(self, value: str):
        def checked(item):
            return self._value_name("maps") == value

        return checked

    def _checked(self, key: str):
        def checked(item):
            return self._value_name(key) in ("on", "audit")

        return checked

    def _notify(self, message: str) -> None:
        try:
            self.icon.notify(message, "AuxySecurity")
        except Exception as exc:  # simge henuz hazir degilse
            self._log.info("bildirim gosterilemedi (%s): %s", exc, message)

    def _quarantine_last_action(self, icon, item):
        self._start(self._quarantine_last)

    def _quarantine_last(self) -> None:
        from auxy.core.service import AuxyError
        from auxy.core.vault import Vault

        lt = self._helpers.last_threat
        if lt is None or not lt.quarantinable():
            return
        try:
            vitem = Vault.default().add(lt.path, f"Tehdit: {lt.name}")
            lt.handled = True
            self._notify(f"Kasaya alındı: {vitem.name}")
        except AuxyError as exc:
            self._notify(str(exc))

    def _config_loop(self) -> None:
        while not self._stop.is_set():
            self._config_waiter.wait()  # GUI ayar kaydedince uyanir; baska zaman uykuda
            if self._stop.is_set():
                break
            self._helpers.apply(cfgmod.load())
            self._wake.set()

    def _setup(self, icon) -> None:
        icon.visible = True
        self._helpers.apply(cfgmod.load())
        threading.Thread(target=self._config_loop, daemon=True, name="auxy-config").start()
        system.trim_working_set()

    def _quick_scan_action(self, icon, item):
        self._start(self._quick_scan)

    def _scan_enabled(self, item) -> bool:
        return not self._scans.running

    # ---- eylemler ----
    def _quick_scan(self) -> None:
        from auxy.core import scan

        self._notify("Hızlı tarama başladı.")
        try:
            res = self._scans.run(scan.QUICK)
            self._notify(res.summary())
        except Exception as exc:  # ScanBusyError dahil
            self._notify(str(exc))
        self.refresh()

    @staticmethod
    def _start(fn, *args) -> None:
        threading.Thread(target=fn, args=args, daemon=True).start()

    def _toggle(self, key: str) -> None:
        self._apply(key, "off" if self._value_name(key) in ("on", "audit") else "on")

    def _apply(self, key: str, value: str) -> None:
        res = actions.apply_setting(key, value)
        label = SETTINGS[key].label
        self._notify(res.message if not res.ok else f"{label}: {res.message}")
        self.refresh()

    def open_gui(self, *_args) -> None:
        flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
        subprocess.Popen(
            [system.app_exe(windowless=True), *system.app_args(["gui"])],
            creationflags=flags, close_fds=True,
        )

    def quit(self, *_args) -> None:
        self._stop.set()
        self._wake.set()
        self._config_waiter.wake()
        self._helpers.stop_all()
        self.icon.stop()

    def run(self) -> int:
        threading.Thread(target=self._loop, daemon=True).start()
        try:
            self.icon.run(setup=self._setup)  # ana is parcacigini bloke eder (mesaj dongusu)
        finally:  # normal cikista da, istisnada da: arka plan bilesenlerini durdur (yeniden baslatmada sizinti olmasin)
            self._stop.set()
            self._wake.set()
            self._config_waiter.wake()
            self._helpers.stop_all()
            try:
                self.icon.stop()
            except Exception:  # noqa: BLE001 - zaten durmus olabilir
                pass
        return 0


def run() -> int:
    from auxy.agent import supervisor

    if not system.acquire_single_instance(system.agent_mutex_name()):
        return 0
    get_logger().info("Ajan basladi (pid=%s, yonetici=%s)", os.getpid(), system.is_admin())
    return supervisor.supervise(lambda: Agent().run())  # istisnada surec ici yeniden baslatma
