"""Ayarlar sayfasi: tema + gercek zamanli yardimcilar (config.json'a yazar, ajani aninda uyandirir)."""

from __future__ import annotations

from tkinter import filedialog, messagebox

import customtkinter as ctk

from auxy import __version__
from auxy.core import actions, autostart, contextmenu, hardening, system
from auxy.core import config as cfgmod

MUTED = ("gray40", "gray60")
HOURS = [f"{h:02d}:00" for h in range(24)]
KINDS = {"Hızlı tarama": "quick", "Tam tarama": "full"}


class SettingsPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.cfg = cfgmod.load()
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ctk.CTkLabel(head, text="Ayarlar", font=ctk.CTkFont(size=22, weight="bold")).pack(side="left")
        self.message = ctk.CTkLabel(head, text="", anchor="e", wraplength=420, justify="right")
        self.message.pack(side="right")

        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)

        # ---- gorunum ----
        card = self._card(body, "Görünüm", 0)
        ctk.CTkLabel(card, text="Tema", anchor="w").grid(row=1, column=0, sticky="w", padx=16, pady=6)
        ctk.CTkOptionMenu(
            card, values=["Sistem", "Açık", "Koyu"], width=120,
            command=lambda v: ctk.set_appearance_mode({"Sistem": "system", "Açık": "light", "Koyu": "dark"}[v]),
        ).grid(row=1, column=2, padx=16, pady=6)

        # ---- yardimcilar ----
        card = self._card(body, "Gerçek zamanlı yardımcılar", 1)
        self.agent_lbl = ctk.CTkLabel(card, text="", anchor="w", text_color=MUTED, wraplength=520, justify="left")
        self.agent_lbl.grid(row=1, column=0, columnspan=3, sticky="w", padx=16)

        self.watch_sw = self._switch(card, 2, "Yeni indirilen dosyaları otomatik tara", self._save)
        self.folders_lbl = ctk.CTkLabel(card, text="", anchor="w", text_color=MUTED, wraplength=430, justify="left")
        self.folders_lbl.grid(row=3, column=0, sticky="w", padx=32)
        fb = ctk.CTkFrame(card, fg_color="transparent")
        fb.grid(row=3, column=2, padx=16)
        ctk.CTkButton(fb, text="Klasör ekle…", width=100, height=24, command=self.add_folder).pack(side="left")
        ctk.CTkButton(fb, text="Sıfırla", width=60, height=24, fg_color="transparent", border_width=1,
                      text_color=("gray20", "gray85"), command=self.reset_folders).pack(side="left", padx=(6, 0))

        self.recursive_sw = self._switch(card, 4, "İzlenen klasörlerin alt klasörlerini de izle", self._save)
        self.events_sw = self._switch(card, 5, "Tehdit bulununca bildirim göster", self._save)
        self.usb_sw = self._switch(card, 6, "Takılan USB sürücüyü tara", self._save)

        self.sched_sw = self._switch(card, 7, "Haftalık zamanlanmış tarama (bilgisayar boştayken)", self._save)
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.grid(row=8, column=0, columnspan=3, sticky="w", padx=32, pady=(0, 8))
        self.day_menu = ctk.CTkOptionMenu(row, values=cfgmod.WEEKDAYS, width=120, command=lambda _v: self._save())
        self.day_menu.pack(side="left")
        self.hour_menu = ctk.CTkOptionMenu(row, values=HOURS, width=90, command=lambda _v: self._save())
        self.hour_menu.pack(side="left", padx=6)
        self.kind_menu = ctk.CTkOptionMenu(row, values=list(KINDS), width=130, command=lambda _v: self._save())
        self.kind_menu.pack(side="left")
        ctk.CTkLabel(card, text="Bilgisayar 5 dk boştaysa ve prizdeyse çalışır; uygun an yoksa 6 saat sonra vazgeçer.",
                     anchor="w", text_color=MUTED, wraplength=520, justify="left").grid(
            row=9, column=0, columnspan=3, sticky="w", padx=32, pady=(0, 10))

        # ---- sag tik ----
        card = self._card(body, "Explorer", 2)
        self.ctx_sw = self._switch(card, 1, "Sağ tık menüsüne 'Auxy ile tara' ekle", self._toggle_context)
        ctk.CTkLabel(card, text="Yalnızca bu kullanıcı için kaydedilir (yönetici gerekmez), kapatınca silinir.",
                     anchor="w", text_color=MUTED, wraplength=520, justify="left").grid(
            row=2, column=0, columnspan=3, sticky="w", padx=16, pady=(0, 10))

        # ---- baslangic ----
        card = self._card(body, "Başlangıç", 3)
        self.autostart_sw = self._switch(card, 1, "Windows açılışında tray ajanını başlat", self._toggle_autostart)
        ctk.CTkLabel(card, text="Görev Zamanlayıcı ile oturum açılışından 30 sn sonra, yüksek yetkiyle (her açılışta "
                                "UAC sorulmadan) başlar. Kurmak ve kaldırmak yönetici izni (UAC) ister.",
                     anchor="w", text_color=MUTED, wraplength=520, justify="left").grid(
            row=2, column=0, columnspan=3, sticky="w", padx=16, pady=(0, 10))

        ctk.CTkLabel(body, text=f"AuxySecurity {__version__}   |   Yönetici: "
                                f"{'evet' if system.is_admin() else 'hayır'}", text_color=MUTED).grid(
            row=4, column=0, sticky="w", pady=(4, 0))
        self.load_into_widgets()

    # ---- yapi ----
    @staticmethod
    def _card(master, title: str, row: int) -> ctk.CTkFrame:
        c = ctk.CTkFrame(master, corner_radius=12)
        c.grid(row=row, column=0, sticky="ew", pady=(0, 12), padx=(0, 6))
        c.columnconfigure(0, weight=1)
        ctk.CTkLabel(c, text=title, font=ctk.CTkFont(size=15, weight="bold"), anchor="w").grid(
            row=0, column=0, columnspan=3, sticky="w", padx=16, pady=(10, 4))
        return c

    @staticmethod
    def _switch(card, row: int, label: str, command) -> ctk.CTkSwitch:
        ctk.CTkLabel(card, text=label, anchor="w").grid(row=row, column=0, sticky="w", padx=16, pady=6)
        sw = ctk.CTkSwitch(card, text="", width=46, command=command)
        sw.grid(row=row, column=2, padx=16)
        return sw

    # ---- yukle / kaydet ----
    def load_into_widgets(self) -> None:
        c = self.cfg = cfgmod.load()
        for sw, val in ((self.watch_sw, c.watch_enabled), (self.recursive_sw, c.watch_recursive),
                        (self.events_sw, c.event_notifications),
                        (self.usb_sw, c.usb_scan), (self.sched_sw, c.scheduled.enabled),
                        (self.ctx_sw, contextmenu.is_installed())):
            (sw.select if val else sw.deselect)()
        (self.autostart_sw.select if autostart.is_installed() else self.autostart_sw.deselect)()
        self.day_menu.set(cfgmod.WEEKDAYS[c.scheduled.weekday])
        self.hour_menu.set(f"{c.scheduled.hour:02d}:00")
        self.kind_menu.set(next(k for k, v in KINDS.items() if v == c.scheduled.kind))
        shown = c.watch_folders or ["İndirilenler klasörü (varsayılan)"]
        self.folders_lbl.configure(text="İzlenen: " + "; ".join(shown))
        running = system.is_agent_running()
        self.agent_lbl.configure(
            text="Tray ajanı çalışıyor: değişiklikler hemen uygulanır." if running else
                 "Tray ajanı çalışmıyor: ayarlar kaydedilir ama ajan açılınca (ya da başlangıçta) uygulanır.",
            text_color=MUTED if running else "#d9932b")

    def collect(self) -> cfgmod.Config:
        return cfgmod.Config(
            watch_enabled=bool(self.watch_sw.get()),
            watch_folders=list(self.cfg.watch_folders),
            watch_recursive=bool(self.recursive_sw.get()),
            event_notifications=bool(self.events_sw.get()),
            usb_scan=bool(self.usb_sw.get()),
            scheduled=cfgmod.ScheduledScan(
                enabled=bool(self.sched_sw.get()),
                weekday=cfgmod.WEEKDAYS.index(self.day_menu.get()),
                hour=int(self.hour_menu.get()[:2]),
                kind=KINDS[self.kind_menu.get()],
            ),
        ).sanitized()

    def _save(self) -> None:
        self.cfg = self.collect()
        cfgmod.save(self.cfg)
        system.signal_config_changed()
        self.say("Kaydedildi.")

    def say(self, text: str, error: bool = False) -> None:
        self.message.configure(text=text, text_color="#d64545" if error else ("gray20", "gray85"))

    # ---- klasorler ----
    def add_folder(self) -> None:
        path = filedialog.askdirectory(title="İzlenecek klasör")
        if path and path not in self.cfg.watch_folders:
            self.cfg.watch_folders.append(path)
            cfgmod.save(self.cfg)
            system.signal_config_changed()
            self.load_into_widgets()
            self.say("Klasör eklendi.")

    def reset_folders(self) -> None:
        self.cfg.watch_folders = []
        cfgmod.save(self.cfg)
        system.signal_config_changed()
        self.load_into_widgets()
        self.say("İndirilenler klasörüne sıfırlandı.")

    # ---- baslangic gorevi ----
    def _toggle_autostart(self) -> None:
        op = "install" if self.autostart_sw.get() else "remove"
        if op == "install":
            risk = hardening.install_location_risk()
            if risk.risky and not messagebox.askyesno(
                    "Güvenlik uyarısı",
                    "Başlangıç görevi YÜKSEK YETKİYLE (yönetici) çalışır, ama uygulama dosyaları kullanıcının "
                    "yazabildiği bir dizinde duruyor:\n\n" + "\n".join(risk.paths) +
                    "\n\nBu hesapta çalışan zararlı bir program bu dosyaları değiştirip yönetici yetkisi kazanabilir. "
                    "Yalnızca kendi kullandığın bir bilgisayarda kabul edilebilir.\n\nYine de kurulsun mu?",
                    icon="warning"):
                self.load_into_widgets()  # onaylanmadi: anahtar gercek duruma doner
                return
        self.say("Başlangıç görevi güncelleniyor… (yönetici izni istenebilir)")
        self.app.worker.submit(lambda: actions.autostart_op(op), self._autostart_done)

    def _autostart_done(self, res, exc) -> None:
        if exc is not None:
            self.say(str(exc), error=True)
        else:
            self.say(res.message, error=not res.ok)
        self.load_into_widgets()  # gercek durumu geri oku (UAC reddedildiyse anahtar eski haline doner)

    # ---- sag tik ----
    def _toggle_context(self) -> None:
        try:
            contextmenu.install() if self.ctx_sw.get() else contextmenu.remove()
            self.say("Sağ tık menüsü güncellendi.")
        except OSError as exc:
            self.say(f"Kayıt defteri güncellenemedi: {exc}", error=True)
            self.load_into_widgets()
