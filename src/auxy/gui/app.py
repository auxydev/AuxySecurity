"""AuxySecurity ana penceresi (customtkinter). Mantik core/ ve viewmodel.py'dedir."""

from __future__ import annotations

import os

import customtkinter as ctk

from auxy import __version__
from auxy.core import defender, paths, system
from auxy.core.service import DefenderService
from auxy.core.settings import SETTINGS
from auxy.gui import viewmodel as vm
from auxy.gui.worker import Worker

COLORS = {vm.OK: "#2e9e5b", vm.WARN: "#d9932b", vm.CRIT: "#d64545"}
AUTO_REFRESH_MS = 30_000
WINSEC_URI = "windowsdefender://threatsettings"

VALUE_TR = {"on": "Açık", "off": "Kapalı", "audit": "Denetim", "basic": "Temel",
            "advanced": "Gelişmiş"}

# Yazilabilen ayarlar (anahtar) ve Windows'un disaridan degistirmeye izin vermedikleri
TOGGLES = ("pua", "cfa", "netprot")
READONLY = ("realtime", "maps")

NAV = (
    ("dashboard", "Pano"),
    ("scan", "Tarama"),
    ("quarantine", "Karantina"),
    ("settings", "Ayarlar"),
    ("log", "Günlük"),
)


def _open_windows_security() -> None:
    try:
        os.startfile(WINSEC_URI)  # noqa: S606
    except OSError:
        pass


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
            self.admin_row, text="Ayarları değiştirmek için yönetici yetkisi gerekir.",
            text_color=("gray30", "gray70"),
        )
        self.admin_label.pack(side="left")
        self.admin_btn = ctk.CTkButton(
            self.admin_row, text="Yönetici olarak yeniden başlat", width=210,
            command=app.restart_as_admin,
        )
        self.admin_btn.pack(side="right")

        # Salt-okunur durum satirlari
        info = ctk.CTkFrame(self, corner_radius=12)
        info.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        info.columnconfigure(1, weight=1)
        self.info_values: dict[str, ctk.CTkLabel] = {}
        rows = (
            ("realtime", "Gerçek zamanlı koruma"),
            ("maps", "Bulut korumalı koruma"),
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
            if key in READONLY:
                ctk.CTkButton(
                    info, text="Windows Security'de aç", width=170, height=26,
                    fg_color="transparent", border_width=1,
                    text_color=("gray20", "gray85"), command=_open_windows_security,
                ).grid(row=i, column=2, padx=(0, 14), pady=5)

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

        self.message = ctk.CTkLabel(self, text="", anchor="w", wraplength=640, justify="left")
        self.message.grid(row=5, column=0, sticky="w", pady=(12, 0))

    def update_view(self, st: defender.DefenderStatus, admin: bool) -> None:
        health = vm.evaluate(st)
        self.banner.configure(fg_color=COLORS[health.level])
        self.banner_title.configure(text=health.title)
        self.banner_reasons.configure(text="\n".join(f"• {r}" for r in health.reasons))

        iv = self.info_values
        iv["realtime"].configure(text="Açık" if st.realtime_on else "Kapalı")
        maps = SETTINGS["maps"].name_of(st.prefs["MAPSReporting"])
        iv["maps"].configure(text=VALUE_TR.get(maps, maps))
        iv["tamper"].configure(text="Açık" if st.tamper_protected else "Kapalı")
        age = vm.signature_age_days(st)
        sig = st.status.get("AntivirusSignatureVersion") or "?"
        iv["signature"].configure(text=sig if age is None else f"{sig}  ({age} gün önce)")
        iv["product"].configure(text=str(st.status.get("AMProductVersion") or "?"))

        for key, switch in self.switches.items():
            name = SETTINGS[key].name_of(st.prefs[SETTINGS[key].pref_field])
            (switch.select if name == "on" else switch.deselect)()
            switch.configure(state="normal" if admin else "disabled")
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


class SettingsPage(ctk.CTkFrame):
    def __init__(self, master, app: App):
        super().__init__(master, fg_color="transparent")
        ctk.CTkLabel(self, text="Ayarlar", font=ctk.CTkFont(size=22, weight="bold")).pack(
            anchor="w", pady=(0, 12))
        ctk.CTkLabel(self, text="Tema").pack(anchor="w")
        menu = ctk.CTkOptionMenu(
            self, values=["Sistem", "Açık", "Koyu"], width=140,
            command=lambda v: ctk.set_appearance_mode({"Sistem": "system", "Açık": "light",
                                                        "Koyu": "dark"}[v]),
        )
        menu.pack(anchor="w", pady=(2, 16))
        admin = "evet" if system.is_admin() else "hayır"
        ctk.CTkLabel(self, text=f"AuxySecurity {__version__}   |   Yönetici: {admin}",
                     text_color=("gray40", "gray60")).pack(anchor="w")
        ctk.CTkLabel(self, text="Başlangıçta çalıştırma ve tray: M3'te eklenecek.",
                     text_color=("gray40", "gray60")).pack(anchor="w", pady=(4, 0))


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


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
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
            "scan": PlaceholderPage(content, "Tarama", "Hızlı / tam / özel tarama: M4'te eklenecek."),
            "quarantine": PlaceholderPage(content, "Karantina", "Karantina kasası: M5'te eklenecek."),
            "settings": SettingsPage(content, self),
            "log": self.log_page,
        }
        for page in self.pages.values():
            page.grid(row=0, column=0, sticky="nsew")
        self.show("dashboard")

        self.refresh()
        self.after(AUTO_REFRESH_MS, self._auto_refresh)

    # ---- gezinme ----
    def show(self, key: str) -> None:
        self.pages[key].tkraise()
        for k, b in self.nav_buttons.items():
            b.configure(fg_color=("gray78", "gray28") if k == key else "transparent")
        if key == "log":
            self.log_page.reload()

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
        value = "on" if switch.get() else "off"
        label = SETTINGS[key].label
        self.dashboard.show_message(f"{label}: {value} uygulanıyor…")
        switch.configure(state="disabled")
        self.worker.submit(lambda: DefenderService().set(key, value),
                           lambda res, exc: self._on_set(label, res, exc))

    def _on_set(self, label: str, res, exc) -> None:
        if exc is not None:
            self.dashboard.show_message(str(exc), error=True)
        elif res.changed:
            self.dashboard.show_message(f"{label}: {res.old} → {res.new}")
        else:
            self.dashboard.show_message(f"{label}: zaten {res.new}.")
        self.refresh()  # gercek durumu geri oku (anahtarlari da dogrular)

    def restart_as_admin(self) -> None:
        if system.relaunch_as_admin(["gui"], windowless=True):
            self.destroy()
        else:
            self.dashboard.show_message("Yönetici izni verilmedi.", error=True)


def run() -> None:
    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("blue")
    App().mainloop()
