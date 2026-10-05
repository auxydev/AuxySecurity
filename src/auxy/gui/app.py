"""AuxySecurity ana penceresi (customtkinter). Mantik core/ ve viewmodel.py'dedir."""

from __future__ import annotations

import os

import customtkinter as ctk

from auxy.core import actions, defender, paths, system
from auxy.core.settings import SETTINGS
from auxy.core.settings import TOGGLE_KEYS as TOGGLES
from auxy.gui import viewmodel as vm
from auxy.gui.scan_page import ScanPage
from auxy.gui.network_page import NetworkPage
from auxy.gui.security_page import SecurityPage
from auxy.gui.settings_page import SettingsPage
from auxy.gui.vault_page import VaultPage
from auxy.gui.worker import Worker

COLORS = {vm.OK: "#2e9e5b", vm.WARN: "#d9932b", vm.CRIT: "#d64545"}
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


class DashboardPage(ctk.CTkFrame):
    def __init__(self, master, app: App):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.columnconfigure(0, weight=1)

        self.banner = ctk.CTkFrame(self, corner_radius=12)
        self.banner.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self.banner_title = ctk.CTkLabel(
            self.banner, text="Durum okunuyor…", font=ctk.CTkFont(size=22, weight="bold"),
            text_color="white",
        )
        self.banner_title.pack(anchor="w", padx=18, pady=(14, 2))
        self.banner_reasons = ctk.CTkLabel(
            self.banner, text="", justify="left", anchor="w", text_color="white", wraplength=620
        )
        self.banner_reasons.pack(anchor="w", padx=18, pady=(0, 14))

        self.admin_row = ctk.CTkFrame(self, fg_color="transparent")
        self.admin_row.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self.admin_label = ctk.CTkLabel(
            self.admin_row, text="Ayar değiştirirken yönetici izni (UAC) istenecek.",
            text_color=("gray30", "gray70"),
        )
        self.admin_label.pack(side="left")
        self.admin_btn = ctk.CTkButton(
            self.admin_row, text="Yönetici olarak yeniden aç", width=190,
            command=app.restart_as_admin,
        )
        self.admin_btn.pack(side="right")

        # Salt-okunur durum satirlari
        info = ctk.CTkFrame(self, corner_radius=12)
        info.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        info.columnconfigure(1, weight=1)
        self.info_values: dict[str, ctk.CTkLabel] = {}
        rows = (
            ("tamper", "Tamper Protection"),
            ("signature", "Virüs imzaları"),
            ("product", "Defender sürümü"),
        )
        for i, (key, label) in enumerate(rows):
            ctk.CTkLabel(info, text=label, anchor="w").grid(
                row=i, column=0, sticky="w", padx=18, pady=5)
            val = ctk.CTkLabel(info, text="—", anchor="e")
            val.grid(row=i, column=1, sticky="e", padx=(8, 8), pady=5)
            self.info_values[key] = val

        # Hizli anahtarlar
        ctk.CTkLabel(self, text="Hızlı anahtarlar", font=ctk.CTkFont(size=15, weight="bold"),
                     anchor="w").grid(row=3, column=0, sticky="w", pady=(0, 4))
        sw = ctk.CTkFrame(self, corner_radius=12)
        sw.grid(row=4, column=0, sticky="ew")
        sw.columnconfigure(0, weight=1)
        self.switches: dict[str, ctk.CTkSwitch] = {}
        self.switch_notes: dict[str, ctk.CTkLabel] = {}
        for i, key in enumerate(TOGGLES):
            s = SETTINGS[key]
            ctk.CTkLabel(sw, text=s.label, anchor="w").grid(
                row=i, column=0, sticky="w", padx=18, pady=8)
            note = ctk.CTkLabel(sw, text="", text_color=("gray40", "gray60"))
            note.grid(row=i, column=1, padx=8)
            switch = ctk.CTkSwitch(sw, text="", width=46)
            switch.configure(command=lambda k=key, w=switch: app.toggle(k, w))
            switch.grid(row=i, column=2, padx=(0, 18))
            self.switches[key] = switch
            self.switch_notes[key] = note

        # Bulut koruma: uc seviyeli (Kapali / Temel / Gelismis)
        row = len(TOGGLES)
        ctk.CTkLabel(sw, text=SETTINGS["maps"].label, anchor="w").grid(
            row=row, column=0, sticky="w", padx=18, pady=8)
        self.maps_menu = ctk.CTkOptionMenu(
            sw, values=list(MAPS_TR), width=130, command=app.set_maps)
        self.maps_menu.grid(row=row, column=2, padx=(0, 18), pady=6)

        self.message = ctk.CTkLabel(self, text="", anchor="w", wraplength=640, justify="left")
        self.message.grid(row=5, column=0, sticky="w", pady=(12, 0))

    def update_view(self, st: defender.DefenderStatus, admin: bool) -> None:
        health = vm.evaluate(st)
        self.banner.configure(fg_color=COLORS[health.level])
        self.banner_title.configure(text=health.title)
        self.banner_reasons.configure(text="\n".join(f"• {r}" for r in health.reasons))

        iv = self.info_values
        maps = SETTINGS["maps"].name_of(st.prefs["MAPSReporting"])
        self.maps_menu.set(VALUE_TR.get(maps, maps))
        iv["tamper"].configure(text="Açık" if st.tamper_protected else "Kapalı")
        age = vm.signature_age_days(st)
        sig = st.status.get("AntivirusSignatureVersion") or "?"
        iv["signature"].configure(text=sig if age is None else f"{sig}  ({age} gün önce)")
        iv["product"].configure(text=str(st.status.get("AMProductVersion") or "?"))

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
        self.message.configure(text=text, text_color="#d64545" if error else ("gray20", "gray85"))


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
        top.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(top, text="Günlük", font=ctk.CTkFont(size=22, weight="bold")).pack(side="left")
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
        self.geometry("920x620")
        self.minsize(820, 560)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        self.worker = Worker(self.after)
        self.admin = system.is_admin()
        self.last_status: defender.DefenderStatus | None = None

        sidebar = ctk.CTkFrame(self, width=170, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsew")
        ctk.CTkLabel(sidebar, text="AuxySecurity", font=ctk.CTkFont(size=18, weight="bold")).pack(
            padx=16, pady=(18, 18))
        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        for key, label in NAV:
            b = ctk.CTkButton(sidebar, text=label, anchor="w", fg_color="transparent",
                              text_color=("gray10", "gray90"),
                              hover_color=("gray75", "gray30"),
                              command=lambda k=key: self.show(k))
            b.pack(fill="x", padx=10, pady=2)
            self.nav_buttons[key] = b

        content = ctk.CTkFrame(self, fg_color="transparent")
        content.grid(row=0, column=1, sticky="nsew", padx=20, pady=18)
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
            b.configure(fg_color=("gray78", "gray28") if k == key else "transparent")
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

