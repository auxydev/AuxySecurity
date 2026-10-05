"""AuxySecurity ana penceresi (customtkinter). Mantik core/ ve viewmodel.py'dedir."""

from __future__ import annotations

import os

import customtkinter as ctk

from auxy.core import actions, defender, paths, system
from auxy.core.settings import SETTINGS
from auxy.core.settings import TOGGLE_KEYS as TOGGLES
from auxy.gui import viewmodel as vm
from auxy.gui.scan_page import ScanPage
from auxy.gui import theme
from auxy.gui.network_page import NetworkPage
from auxy.gui.security_page import SecurityPage
from auxy.gui.settings_page import SettingsPage
from auxy.gui.vault_page import VaultPage
from auxy.gui.widgets import Card, Tile
from auxy.gui.worker import Worker

theme.apply()  # pencere/widget olusturulmadan ONCE: modern tema (renk, yazi tipi, yuvarlak kartlar)

COLORS = {vm.OK: theme.OK_BG, vm.WARN: theme.WARN_BG, vm.CRIT: theme.BAD_BG}
AUTO_REFRESH_MS = 30_000

VALUE_TR = {"on": "Açık", "off": "Kapalı", "audit": "Denetim", "basic": "Temel",
            "advanced": "Gelişmiş"}

MAPS_TR = {"Kapalı": "off", "Temel": "basic", "Gelişmiş": "advanced"}

NAV = (
    ("dashboard", "Pano"),
    ("security", "Güvenlik"),
    ("network", "Ağ güvenliği"),
    ("scan", "Tarama"),
    ("quarantine", "Karantina"),
    ("settings", "Ayarlar"),
    ("log", "Günlük"),
)


TOGGLE_HINTS = {
    "realtime": "Dosyalar açılırken ve indirilirken sürekli taranır.",
    "pua": "Reklam yazılımı gibi istenmeyen programları engeller.",
    "cfa": "Fidye yazılımlarının belgelerini değiştirmesini engeller.",
    "netprot": "Zararlı sitelere ve sunuculara bağlantıyı keser.",
}
MAPS_HINT = "Şüpheli dosyaları bulutta hızlıca denetler."


class DashboardPage(ctk.CTkFrame):
    def __init__(self, master, app: App):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.columnconfigure(0, weight=1)
        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.body = body

        # ---- ust bant: durum + ana eylemler
        self.banner = ctk.CTkFrame(body, corner_radius=18, border_width=0)
        self.banner.grid(row=0, column=0, sticky="ew", pady=(0, 14), padx=(0, 6))
        self.banner.columnconfigure(1, weight=1)
        self.banner_icon = ctk.CTkLabel(self.banner, text="", image=theme.status_image(None, 0, 64), width=72)
        self.banner_icon.grid(row=0, column=0, rowspan=3, padx=(20, 4), pady=18)
        self.banner_title = ctk.CTkLabel(
            self.banner, text="Durum okunuyor…", font=ctk.CTkFont(size=26, weight="bold"),
            text_color="white", anchor="w",
        )
        self.banner_title.grid(row=0, column=1, sticky="w", padx=(8, 18), pady=(20, 0))
        self.banner_reasons = ctk.CTkLabel(
            self.banner, text="", justify="left", anchor="w", text_color="white", wraplength=560
        )
        self.banner_reasons.grid(row=1, column=1, sticky="w", padx=(8, 18), pady=(2, 0))
        actions_row = ctk.CTkFrame(self.banner, fg_color="transparent")
        actions_row.grid(row=2, column=1, sticky="w", padx=(8, 18), pady=(12, 18))
        white = dict(fg_color="white", hover_color="#e8edf6", text_color="#1e293b", height=34, corner_radius=10)
        ctk.CTkButton(actions_row, text="Hızlı tarama başlat", width=150, command=app.quick_scan, **white).pack(side="left")
        ctk.CTkButton(actions_row, text="İmzaları güncelle", width=140, command=app.update_signatures,
                      **white).pack(side="left", padx=8)

        self.admin_row = ctk.CTkFrame(body, fg_color="transparent")
        self.admin_row.grid(row=1, column=0, sticky="ew", pady=(0, 10), padx=(0, 6))
        self.admin_label = ctk.CTkLabel(
            self.admin_row, text="Ayar değiştirirken Windows yönetici izni (UAC) isteyecek.",
            text_color=theme.MUTED,
        )
        self.admin_label.pack(side="left")
        self.admin_btn = ctk.CTkButton(
            self.admin_row, text="Yönetici olarak aç", width=150, height=30,
            command=app.restart_as_admin,
        )
        self.admin_btn.pack(side="right")

        # ---- ozet kutulari
        tiles = ctk.CTkFrame(body, fg_color="transparent")
        tiles.grid(row=2, column=0, sticky="ew", pady=(0, 14), padx=(0, 6))
        self.tiles: dict[str, Tile] = {}
        self.info_values: dict[str, ctk.CTkLabel] = {}
        for i, (key, caption) in enumerate((("realtime", "Gerçek zamanlı koruma"), ("signature", "Virüs imzaları"),
                                            ("tamper", "Kurcalama koruması"), ("product", "Defender sürümü"))):
            tiles.columnconfigure(i, weight=1, uniform="tiles")
            tile = Tile(tiles, caption)
            tile.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 5, 0 if i == 3 else 5))
            self.tiles[key] = tile
            self.info_values[key] = tile.value

        # ---- hizli anahtarlar
        card = Card(body, "Hızlı anahtarlar", 3, "Windows Güvenlik'teki ana korumaları buradan aç ya da kapat.")
        self.switches: dict[str, ctk.CTkSwitch] = {}
        self.switch_notes: dict[str, ctk.CTkLabel] = {}
        for key in TOGGLES:
            s = SETTINGS[key]
            title = card.label(s.label, TOGGLE_HINTS.get(key, ""))
            note = ctk.CTkLabel(card, text="", text_color=theme.MUTED)
            note.grid(row=card.next_row, column=1, padx=8)
            switch = ctk.CTkSwitch(card, text="", width=46)
            switch.configure(command=lambda k=key, w=switch: app.toggle(k, w))
            switch.grid(row=card.next_row, column=2, padx=(0, 18))
            card.next_row += 1
            self.switches[key] = switch
            self.switch_notes[key] = note
            del title
        self.maps_menu = card.menu_row(SETTINGS["maps"].label, list(MAPS_TR), app.set_maps, MAPS_HINT, 130)

        self.message = ctk.CTkLabel(body, text="", anchor="w", wraplength=660, justify="left")
        self.message.grid(row=4, column=0, sticky="w", pady=(4, 0))

    def update_view(self, st: defender.DefenderStatus, admin: bool) -> None:
        health = vm.evaluate(st)
        self.banner.configure(fg_color=COLORS[health.level])
        self.banner_title.configure(text=health.title)
        self.banner_reasons.configure(text="\n".join(f"• {r}" for r in health.reasons))
        self.banner_icon.configure(image=theme.status_image(health.level, health.badge, 64))

        maps = SETTINGS["maps"].name_of(st.prefs["MAPSReporting"])
        self.maps_menu.set(VALUE_TR.get(maps, maps))
        rt = bool(st.status.get("RealTimeProtectionEnabled"))
        self.tiles["realtime"].set("Açık" if rt else "KAPALI", theme.GOOD if rt else theme.BAD,
                                   "Sürekli korunuyorsun" if rt else "Cihaz şu an korunmuyor")
        age = vm.signature_age_days(st)
        sig = st.status.get("AntivirusSignatureVersion") or "?"
        fresh = age is not None and age < vm.SIGNATURE_WARN_DAYS
        self.tiles["signature"].set("Güncel" if fresh else ("Eski" if age is not None else "?"),
                                    theme.GOOD if fresh else theme.WARN,
                                    f"{sig}" + ("" if age is None else f" • {age} gün önce"))
        tamper = bool(st.tamper_protected)
        self.tiles["tamper"].set("Açık" if tamper else "Kapalı", theme.GOOD if tamper else theme.WARN,
                                 "" if tamper else "Güvenlik'ten açılır")
        self.tiles["product"].set(str(st.status.get("AMProductVersion") or "?"), theme.TEXT, "Microsoft Defender")

        for key, switch in self.switches.items():
            name = SETTINGS[key].name_of(st.prefs[SETTINGS[key].pref_field])
            (switch.select if name == "on" else switch.deselect)()
            switch.configure(state="normal")
            self.switch_notes[key].configure(text="denetim modu" if name == "audit" else "")

        if admin:
            self.admin_row.grid_remove()
        else:
            self.admin_row.grid()

    def show_message(self, text: str, error: bool = False) -> None:
        self.message.configure(text=text, text_color=theme.BAD if error else theme.TEXT)

class PlaceholderPage(ctk.CTkFrame):
    def __init__(self, master, title: str, note: str):
        super().__init__(master, fg_color="transparent")
        ctk.CTkLabel(self, text=title, font=ctk.CTkFont(size=22, weight="bold")).pack(
            anchor="w", pady=(0, 8))
        ctk.CTkLabel(self, text=note, justify="left", anchor="w").pack(anchor="w")


class LogPage(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master, fg_color="transparent")
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", pady=(0, 12))
        titles = ctk.CTkFrame(top, fg_color="transparent")
        titles.pack(side="left")
        ctk.CTkLabel(titles, text="Günlük", font=ctk.CTkFont(size=26, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(titles, text="Uygulamanın son kayıtları. Bir sorun olursa buraya bak.", text_color=theme.MUTED).pack(anchor="w")
        ctk.CTkButton(top, text="Yenile", width=80, command=self.reload).pack(side="right")
        self.box = ctk.CTkTextbox(self, wrap="none")
        self.box.pack(fill="both", expand=True)

    def reload(self) -> None:
        try:
            lines = (paths.log_dir() / "auxy.log").read_text(encoding="utf-8").splitlines()[-200:]
            text = "\n".join(lines) or "(günlük boş)"
        except FileNotFoundError:
            text = "(henüz kayıt yok)"
        self.box.configure(state="normal")
        self.box.delete("1.0", "end")
        self.box.insert("1.0", text)
        self.box.configure(state="disabled")
        self.box.see("end")


try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    _DnD = TkinterDnD.DnDWrapper
except ImportError:  # sürükle-bırak bağımlılığı yoksa uygulama yine çalışır
    DND_FILES, TkinterDnD, _DnD = None, None, object


class App(ctk.CTk, _DnD):
    def __init__(self):
        super().__init__()
        self.dnd_ready = self._setup_dnd()
        self.title("AuxySecurity")
        self.geometry("1000x680")
        self.minsize(900, 600)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        self.worker = Worker(self.after)
        self.admin = system.is_admin()
        self.last_status: defender.DefenderStatus | None = None

        sidebar = ctk.CTkFrame(self, width=224, corner_radius=0, fg_color=theme.SIDEBAR, border_width=0)
        sidebar.grid(row=0, column=0, sticky="nsew")
        ctk.CTkFrame(self, width=1, corner_radius=0, fg_color=theme.BORDER, border_width=0).grid(
            row=0, column=0, sticky="nse")  # kenar cubugu ayirici cizgi
        sidebar.grid_propagate(False)
        sidebar.rowconfigure(2, weight=1)
        brand = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=16, pady=(22, 20))
        ctk.CTkLabel(brand, text="", image=theme.logo_image(38)).pack(side="left")
        names = ctk.CTkFrame(brand, fg_color="transparent")
        names.pack(side="left", padx=(10, 0))
        ctk.CTkLabel(names, text="AuxySecurity", text_color=theme.TEXT, anchor="w",
                     font=ctk.CTkFont(size=17, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(names, text="Windows Güvenlik paneli", text_color=theme.SIDEBAR_MUTED, anchor="w",
                     font=ctk.CTkFont(size=11)).pack(anchor="w")
        nav = ctk.CTkFrame(sidebar, fg_color="transparent")
        nav.grid(row=1, column=0, sticky="ew", padx=12)
        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        for key, label in NAV:
            b = ctk.CTkButton(nav, text=f"  {label}", anchor="w", height=42, corner_radius=10,
                              fg_color="transparent", text_color=theme.SIDEBAR_TEXT,
                              hover_color=theme.SIDEBAR_HOVER, font=ctk.CTkFont(size=14),
                              image=theme.icon(key, 20, *theme.SIDEBAR_ICON), compound="left",
                              command=lambda k=key: self.show(k))
            b.pack(fill="x", pady=2)
            self.nav_buttons[key] = b
        foot = ctk.CTkFrame(sidebar, fg_color="transparent")
        foot.grid(row=3, column=0, sticky="ew", padx=18, pady=(8, 18))
        from auxy import __version__

        self.admin_pill = ctk.CTkLabel(
            foot, text="●  Yönetici" if self.admin else "●  Standart kullanıcı", anchor="w",
            text_color=("#16a34a", "#4ade80") if self.admin else theme.SIDEBAR_MUTED, font=ctk.CTkFont(size=12))
        self.admin_pill.pack(anchor="w")
        ctk.CTkLabel(foot, text=f"Sürüm {__version__}", text_color=theme.SIDEBAR_MUTED, anchor="w",
                     font=ctk.CTkFont(size=11)).pack(anchor="w", pady=(2, 0))
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.grid(row=0, column=1, sticky="nsew", padx=26, pady=22)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)

        self.dashboard = DashboardPage(content, self)
        self.log_page = LogPage(content)
        self.pages: dict[str, ctk.CTkFrame] = {
            "dashboard": self.dashboard,
            "security": SecurityPage(content, self),
            "network": NetworkPage(content, self),
            "scan": ScanPage(content, self),
            "quarantine": VaultPage(content, self),
            "settings": SettingsPage(content, self),
            "log": self.log_page,
        }
        for page in self.pages.values():
            page.grid(row=0, column=0, sticky="nsew")
        self.show("dashboard")

        self.refresh()
        self.after(AUTO_REFRESH_MS, self._auto_refresh)
        self.after(300, self._set_window_icon)  # customtkinter kendi simgesini ~200 ms sonra koyar: sonra ez
        if system.is_frozen():  # ilk calistirmada eski (Store Python) verisini tasima onerisi
            self.after(800, self._offer_migration)

    def _set_window_icon(self) -> None:
        """Pencere ve gorev cubugu simgesi: uygulama logosu (kalkan + A)."""
        try:
            from PIL import ImageTk

            from auxy.agent.icon import make_logo

            self._logo = ImageTk.PhotoImage(make_logo(64))  # referans tutulmazsa silinir
            self.iconphoto(True, self._logo)
        except Exception:  # noqa: BLE001 - simge kozmetik, pencere acilmaya devam etmeli
            pass

    def _offer_migration(self) -> None:
        from auxy.core import migrate

        try:
            plan = migrate.pending_plan()
        except Exception:  # noqa: BLE001 - oneri sessizce atlanabilir
            return
        if plan is None or not system.confirm_dialog(
                "Eski sürümden kalma veri bulundu (" + ", ".join(plan.to_copy) + ").\n\n"
                "Yeni kurulumun veri dizinine KOPYALANSIN mı? Eski veri silinmez.", "AuxySecurity"):
            return
        try:
            steps = migrate.migrate(plan)
        except Exception as exc:  # noqa: BLE001
            steps = [f"başarısız: {exc}"]
        self.dashboard.show_message("Veri taşındı: " + "; ".join(steps))

    def report_callback_exception(self, exc, val, tb) -> None:
        """Tk olay isleyicilerindeki istisnalar (varsayilan: stderr; pythonw'de kaybolur) gunluge yazilir."""
        from auxy.core.log import get_logger

        get_logger().error("GUI olay isleyicisi istisnasi", exc_info=(exc, val, tb))

    # ---- surukle-birak ----
    def _setup_dnd(self) -> bool:
        if TkinterDnD is None:
            return False
        try:
            self.TkdndVersion = TkinterDnD._require(self)
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", lambda e: self.on_drop(list(self.tk.splitlist(e.data))))
            return True
        except Exception:  # tkdnd yuklenemedi: sessizce kapali kal
            return False

    def on_drop(self, paths: list[str]) -> None:
        """Pencereye birakilan dosya/klasorleri tarar (var olmayan yollar atlanir)."""
        existing = [p for p in paths if os.path.exists(p)]
        if existing:
            self.show("scan")
            self.pages["scan"].scan_paths(existing)

    # ---- gezinme ----
    def show(self, key: str) -> None:
        self.pages[key].tkraise()
        for k, b in self.nav_buttons.items():
            active = k == key
            b.configure(fg_color=theme.ACCENT if active else "transparent",
                        hover_color=theme.ACCENT_HOVER if active else theme.SIDEBAR_HOVER,
                        text_color="white" if active else theme.SIDEBAR_TEXT,
                        image=theme.icon(k, 20, "#ffffff", "#ffffff") if active else theme.icon(k, 20, *theme.SIDEBAR_ICON))
        if key == "log":
            self.log_page.reload()
        elif key == "scan":
            self.pages["scan"].refresh_lists()
        elif key == "settings":
            self.pages["settings"].load_into_widgets()
        elif key == "security":
            self.pages["security"].refresh()
        elif key == "network":
            self.pages["network"].refresh()
        elif key == "quarantine":
            self.pages["quarantine"].refresh()

    # ---- veri ----
    def refresh(self) -> None:
        self.worker.submit(defender.read_status, self._on_status)

    def _auto_refresh(self) -> None:
        if self.state() != "iconic":  # kucultulmusken sorgu yok
            self.refresh()
        self.after(AUTO_REFRESH_MS, self._auto_refresh)

    def _on_status(self, st, exc) -> None:
        if exc is not None:
            self.dashboard.show_message(f"Durum okunamadı: {exc}", error=True)
            return
        self.last_status = st
        self.dashboard.update_view(st, self.admin)

    # ---- eylemler ----
    def toggle(self, key: str, switch: ctk.CTkSwitch) -> None:
        switch.configure(state="disabled")
        self._apply(key, "on" if switch.get() else "off")

    def set_maps(self, shown: str) -> None:
        self._apply("maps", MAPS_TR[shown])

    def _apply(self, key: str, value: str) -> None:
        label = SETTINGS[key].label
        self.dashboard.show_message(f"{label}: {VALUE_TR.get(value, value)} uygulanıyor…")
        self.worker.submit(lambda: actions.apply_setting(key, value),
                           lambda res, exc: self._on_set(label, res, exc))

    def _on_set(self, label: str, res, exc) -> None:
        if exc is not None:
            self.dashboard.show_message(str(exc), error=True)
        elif res.ok:
            self.dashboard.show_message(f"{label}: {res.message}")
        else:
            self.dashboard.show_message(res.message, error=True)
        self.refresh()  # gercek durumu geri oku (anahtarlari da dogrular)

    def quick_scan(self) -> None:
        """Pano'dan tek tikla hizli tarama: tarama sayfasina gecer ve baslatir."""
        from auxy.core import scan

        self.show("scan")
        self.pages["scan"].start(scan.QUICK)

    def update_signatures(self) -> None:
        self.show("scan")
        self.pages["scan"].update_sigs()

    def restart_as_admin(self) -> None:
        if system.relaunch_as_admin(["gui"], windowless=True):
            self.destroy()
        else:
            self.dashboard.show_message("Yönetici izni verilmedi.", error=True)


def run() -> None:
    if not system.acquire_single_instance("AuxySecurityGui"):
        system.focus_window("AuxySecurity")  # zaten acik: One getir
        return
    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("blue")
    App().mainloop()

