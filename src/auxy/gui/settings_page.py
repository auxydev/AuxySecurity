"""Ayarlar sayfasi: tema + gercek zamanli yardimcilar (config.json'a yazar, ajani aninda uyandirir)."""

from __future__ import annotations

from tkinter import filedialog, messagebox

import customtkinter as ctk

from auxy import __version__
from auxy.core import actions, autostart, contextmenu, hardening, system
from auxy.core import config as cfgmod
from auxy.gui import theme
from auxy.gui.widgets import Card, page_header

MUTED = theme.MUTED
HOURS = [f"{h:02d}:00" for h in range(24)]
KINDS = {"Hızlı tarama": "quick", "Tam tarama": "full"}


class SettingsPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.cfg = cfgmod.load()
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        head = page_header(self, "Ayarlar", "Uygulamanın davranışını ve otomatik korumaları buradan düzenle.")
        self.message = head.message
        self.message.pack(side="right", padx=(0, 12))  # butonlarin soluna

        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)

        # ---- gorunum ----
        card = Card(body, "Görünüm", 0)
        self.theme_menu = card.menu_row(
            "Tema", ["Sistem", "Açık", "Koyu"],
            lambda v: ctk.set_appearance_mode({"Sistem": "system", "Açık": "light", "Koyu": "dark"}[v]),
            "Windows'un açık/koyu ayarını izle ya da sabitle.", 130)

        # ---- otomatik koruma ----
        card = Card(body, "Otomatik koruma", 1, "Sen bir şey yapmasan da arka planda çalışan korumalar.")
        self.agent_lbl = card.line("", MUTED)
        self.watch_sw = card.switch_row("Yeni indirilen dosyaları tara", self._save,
                                        "İndirilenler klasörüne düşen dosyalar otomatik taranır.")
        fb = card.button_bar(pady=(0, 6))
        self.folders_lbl = ctk.CTkLabel(fb, text="", anchor="w", text_color=MUTED, wraplength=420, justify="left")
        self.folders_lbl.pack(side="left")
        ctk.CTkButton(fb, text="Sıfırla", width=70, height=28, fg_color="transparent", border_width=1,
                      text_color=theme.TEXT, command=self.reset_folders).pack(side="right")
        ctk.CTkButton(fb, text="Klasör ekle…", width=110, height=28, command=self.add_folder).pack(
            side="right", padx=(0, 6))
        self.recursive_sw = card.switch_row("Alt klasörleri de izle", self._save,
                                            "İzlenen klasörlerin içindeki klasörler de kapsanır.")
        self.events_sw = card.switch_row("Tehdit bulununca bildirim göster", self._save,
                                         "Defender bir tehdit yakaladığında sağ altta haber verir.")
        self.usb_sw = card.switch_row("Takılan USB sürücüyü tara", self._save,
                                      "Bir flash bellek taktığında içi otomatik taranır.")
        self.sched_sw = card.switch_row("Haftalık zamanlanmış tarama", self._save,
                                        "Bilgisayar 5 dk boştaysa ve prizdeyse çalışır; uygun an yoksa 6 saat sonra vazgeçer.")
        row = card.button_bar(pady=(0, 12))
        self.day_menu = ctk.CTkOptionMenu(row, values=cfgmod.WEEKDAYS, width=120, command=lambda _v: self._save())
        self.day_menu.pack(side="left")
        self.hour_menu = ctk.CTkOptionMenu(row, values=HOURS, width=90, command=lambda _v: self._save())
        self.hour_menu.pack(side="left", padx=6)
        self.kind_menu = ctk.CTkOptionMenu(row, values=list(KINDS), width=130, command=lambda _v: self._save())
        self.kind_menu.pack(side="left")

        # ---- sistem entegrasyonu ----
        card = Card(body, "Sistem entegrasyonu", 2)
        self.ctx_sw = card.switch_row("Sağ tık menüsüne 'Auxy ile tara' ekle", self._toggle_context,
                                      "Dosya veya klasöre sağ tıklayıp tara. Yalnızca bu kullanıcı için, yönetici izni gerekmez.")
        self.autostart_sw = card.switch_row("Windows açılışında başlat", self._toggle_autostart,
                                            "Tray ajanı oturum açılışından 30 sn sonra, UAC sorulmadan başlar. "
                                            "Kurmak ve kaldırmak yönetici izni ister.")

        ctk.CTkLabel(body, text=f"AuxySecurity {__version__}   |   Yönetici: "
                                f"{'evet' if system.is_admin() else 'hayır'}", text_color=MUTED).grid(
            row=3, column=0, sticky="w", pady=(4, 0))
        self.load_into_widgets()
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
            text_color=MUTED if running else theme.WARN)

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
        self.message.configure(text=text, text_color=theme.BAD if error else theme.TEXT)

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
