"""Guvenlik sayfasi: SmartScreen, cihaz guvenligi, exploit protection, dislamalar. (Guvenlik duvari: ag guvenligi sayfasi)"""

from __future__ import annotations

from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from auxy.core import actions, winsec
from auxy.gui import theme
from auxy.gui.widgets import Card, page_header

MUTED = theme.MUTED
GOOD, BAD = theme.GOOD, theme.BAD
SMARTSCREEN_TR = {"Kapalı": "off", "Uyar": "warn", "Engelle": "block"}
SMARTSCREEN_BACK = {v: k for k, v in SMARTSCREEN_TR.items()}

# Zayiflatici (kapatici) degisiklikler icin onay metinleri
CONFIRM_OFF = {
    "fw_domain": "Etki alanı ağında güvenlik duvarını kapatmak bilgisayarını ağdan gelen saldırılara açar.",
    "fw_private": "Özel ağda güvenlik duvarını kapatmak bilgisayarını ağdan gelen saldırılara açar.",
    "fw_public": "Genel ağda (kafe, otel vb.) güvenlik duvarını kapatmak çok risklidir.",
    "smartscreen_store": "Microsoft Store uygulamalarının web içeriği denetimi kapatılacak.",
}


def yn(value: bool | None, yes: str = "Evet", no: str = "Hayır") -> str:
    return "Bilinmiyor" if value is None else (yes if value else no)


def format_product(p: winsec.SecurityProduct) -> str:
    state = "etkin" if p.enabled else "KAPALI"
    fresh = "güncel" if p.up_to_date else "güncel DEĞİL"
    return f"{p.category}: {p.name}  ({state}, {fresh})"


class SecurityPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        head = page_header(self, "Güvenlik", "Windows'un yerleşik koruma özelliklerini tek yerden yönet.")
        ctk.CTkButton(head.actions, text="Yenile", width=80, command=self.refresh).pack(side="right")
        self.message = head.message
        self.message.pack(side="right", padx=(0, 12))  # butonlarin soluna

        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)

        # Genel durum
        c = Card(body, "Genel durum", 0, "Windows Güvenlik Merkezi'ne kayıtlı koruma ürünleri.")
        self.products_lbl = c.line("Okunuyor…")

        self.sw: dict[str, ctk.CTkSwitch] = {}

        # SmartScreen
        c = Card(body, "Uygulama ve web koruması", 1, "SmartScreen, tanınmayan ve zararlı olabilecek indirmeleri uyarır.")
        self.ss_menu = c.menu_row("Uygulamalar ve dosyalar", list(SMARTSCREEN_TR), self._set_smartscreen,
                                  "İnternetten indirilen programlar çalıştırılmadan önce denetlenir.", 130)
        self.sw["smartscreen_store"] = c.switch_row("Microsoft Store uygulamaları",
                                                    lambda: self._toggle("smartscreen_store"),
                                                    "Store uygulamalarının açtığı web içeriğini denetler.")

        # Cihaz guvenligi
        c = Card(body, "Cihaz güvenliği", 2, "Donanım tabanlı korumalar.")
        self.device_lbl = c.line("Okunuyor…")
        self.sw["hvci"] = c.switch_row("Bellek bütünlüğü", lambda: self._toggle("hvci"),
                                       "Çekirdeği zararlı kodlardan korur. Değişiklik yeniden başlatınca etkinleşir.")
        self.hvci_note = c.line(winsec.WINSEC_SETTINGS["hvci"].hint, MUTED)
        row = c.button_bar()
        ctk.CTkButton(row, text="TPM bilgisini oku (yönetici)", width=210, height=30,
                      command=self.read_tpm).pack(side="left")
        self.tpm_lbl = ctk.CTkLabel(row, text="", anchor="w", justify="left", wraplength=360)
        self.tpm_lbl.pack(side="left", padx=10)

        # Gelismis (varsayilan kapali)
        c = Card(body, "Gelişmiş", 3, "Teknik ayrıntılar. Çoğu kullanıcının buraya bakması gerekmez.")
        ex = c.collapsible("Exploit protection (sistem, salt-okunur)")
        self.exploit_lbl = ctk.CTkLabel(ex.body, text="Okunuyor…", anchor="w", justify="left")
        self.exploit_lbl.grid(row=0, column=0, sticky="w", padx=12, pady=(2, 2))
        ctk.CTkLabel(ex.body, text="Windows tek tek 'varsayılana dön' sunmadığı için bu bölümde değişiklik yapılmaz.",
                     anchor="w", text_color=MUTED, wraplength=560, justify="left").grid(
            row=1, column=0, sticky="w", padx=12, pady=(0, 8))
        excl = c.collapsible("Defender dışlamaları")
        ctk.CTkLabel(excl.body, text="Dışlanan konumlar taranmaz. Okumak ve değiştirmek yönetici izni (UAC) ister.",
                     anchor="w", text_color=MUTED, wraplength=560, justify="left").grid(
            row=0, column=0, sticky="w", padx=12, pady=(2, 4))
        bar = ctk.CTkFrame(excl.body, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", padx=12, pady=4)
        ctk.CTkButton(bar, text="Listele", width=70, command=self.load_exclusions).pack(side="left")
        ctk.CTkButton(bar, text="Klasör ekle…", width=100, command=self.add_folder).pack(side="left", padx=6)
        ctk.CTkButton(bar, text="Uzantı ekle…", width=100, command=lambda: self.add_text("extension")).pack(side="left")
        ctk.CTkButton(bar, text="İşlem ekle…", width=100, command=lambda: self.add_text("process")).pack(
            side="left", padx=6)
        self.excl_frame = ctk.CTkFrame(excl.body, fg_color="transparent")
        self.excl_frame.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 10))
        self.excl_frame.columnconfigure(0, weight=1)
        self._set_excl_note("(Listelemek için 'Listele'ye bas.)")
    def _set_excl_note(self, text: str) -> None:
        """Dislama alanini temizleyip tek satirlik not gosterir. Etiketi HER SEFERINDE yeniden olusturur:
        liste yenilenirken eski etiket yok ediliyordu ve ikinci 'Listele' TclError veriyordu."""
        for w in self.excl_frame.winfo_children():
            w.destroy()
        ctk.CTkLabel(self.excl_frame, text=text, text_color=MUTED, anchor="w").grid(row=0, column=0, sticky="w")

    # ---- mesaj ----
    def say(self, text: str, error: bool = False) -> None:
        self.message.configure(text=text, text_color=BAD if error else theme.TEXT)

    # ---- veri ----
    def refresh(self) -> None:
        def read():
            svc = winsec.WinSecService()
            return svc.get_all(), winsec.read_security_center(), winsec.read_device_security()

        self.app.worker.submit(read, self._show_main)
        self.app.worker.submit(winsec.read_exploit_protection, self._show_exploit)

    def _show_main(self, res, exc) -> None:
        if exc is not None:
            self.say(f"Okunamadı: {exc}", error=True)
            return
        values, products, device = res
        self.products_lbl.configure(
            text="\n".join(format_product(p) for p in products) or "Güvenlik ürünü bulunamadı.")
        for key, sw in self.sw.items():
            (sw.select if values[key] == "on" else sw.deselect)()
        self.ss_menu.set(SMARTSCREEN_BACK.get(values["smartscreen_apps"], "Uyar"))
        self.device_lbl.configure(
            text=f"Secure Boot: {yn(device.secure_boot, 'Açık', 'Kapalı')}   •   "
                 f"Sanallaştırma tabanlı güvenlik: {yn(device.vbs_running, 'Çalışıyor', 'Kapalı')}   •   "
                 f"Bellek bütünlüğü: {yn(device.hvci_running, 'Çalışıyor', 'Çalışmıyor')}")
        configured = values["hvci"] == "on"
        if device.hvci_running is not None and configured != device.hvci_running:
            self.hvci_note.configure(text="Ayar değişti, etkinleşmesi için bilgisayarı yeniden başlat.",
                                     text_color=theme.WARN)
        else:
            self.hvci_note.configure(text=winsec.WINSEC_SETTINGS["hvci"].hint, text_color=MUTED)

    def _show_exploit(self, res, exc) -> None:
        if exc is not None:
            self.exploit_lbl.configure(text=f"Okunamadı: {exc}")
            return
        names = {n: label for n, _g, _p, label in winsec.EXPLOIT_ITEMS}
        self.exploit_lbl.configure(text="\n".join(
            f"{names.get(k, k)}: {winsec.EXPLOIT_STATES.get(v, v)}" for k, v in res.items()))

    # ---- ayar degistirme ----
    def _toggle(self, key: str) -> None:
        sw = self.sw[key]
        value = "on" if sw.get() else "off"
        if value == "off" and key in CONFIRM_OFF and not messagebox.askyesno(
                "Emin misin?", CONFIRM_OFF[key] + "\nDevam edilsin mi?", icon="warning"):
            sw.select()
            return
        if key == "hvci" and not messagebox.askyesno(
                "Bellek bütünlüğü",
                "Bu ayar yalnızca bilgisayar yeniden başlatılınca etkinleşir.\n"
                + winsec.WINSEC_SETTINGS["hvci"].hint + "\nDevam edilsin mi?"):
            (sw.deselect if value == "on" else sw.select)()
            return
        self._apply(key, value)

    def _set_smartscreen(self, shown: str) -> None:
        value = SMARTSCREEN_TR[shown]
        if value == "off" and not messagebox.askyesno(
                "Emin misin?", "SmartScreen'i kapatmak zararlı indirmelere karşı korumayı azaltır.\n"
                               "Devam edilsin mi?", icon="warning"):
            self.refresh()
            return
        self._apply("smartscreen_apps", value)

    def _apply(self, key: str, value: str) -> None:
        label = winsec.WINSEC_SETTINGS[key].label
        self.say(f"{label}: uygulanıyor…")
        self.app.worker.submit(lambda: actions.apply_winsec(key, value),
                               lambda res, exc: self._done(label, res, exc))

    def _done(self, label: str, res, exc) -> None:
        if exc is not None:
            self.say(str(exc), error=True)
        else:
            self.say(f"{label}: {res.message}" if res.ok else res.message, error=not res.ok)
        self.refresh()

    # ---- TPM ----
    def read_tpm(self) -> None:
        self.tpm_lbl.configure(text="Okunuyor… (yönetici izni istenebilir)")

        def done(res, exc):
            if exc is not None or not res.ok:
                self.tpm_lbl.configure(text=str(exc) if exc else res.message, text_color=BAD)
                return
            d = res.data or {}
            self.tpm_lbl.configure(
                text=f"Var: {yn(d.get('TpmPresent'))} • Hazır: {yn(d.get('TpmReady'))} • "
                     f"Etkin: {yn(d.get('TpmEnabled'))} • Sürüm: {d.get('ManufacturerVersion') or '?'}",
                text_color=theme.TEXT)

        self.app.worker.submit(actions.read_tpm, done)

    # ---- dislamalar ----
    def load_exclusions(self) -> None:
        self._set_excl_note("Okunuyor… (yönetici izni istenebilir)")
        self.app.worker.submit(lambda: actions.exclusion_op("list", "path"), self._show_exclusions)

    def _show_exclusions(self, res, exc) -> None:
        for w in self.excl_frame.winfo_children():
            w.destroy()
        if exc is not None or not res.ok:
            ctk.CTkLabel(self.excl_frame, text=str(exc) if exc else res.message, text_color=BAD,
                         anchor="w").grid(row=0, column=0, sticky="w")
            return
        kinds = {"path": "Yol", "extension": "Uzantı", "process": "İşlem"}
        r = 0
        for kind, items in (res.data or {}).items():
            for it in items:
                ctk.CTkLabel(self.excl_frame, text=f"[{kinds[kind]}]  {it}", anchor="w",
                             wraplength=470, justify="left").grid(row=r, column=0, sticky="w", pady=2)
                ctk.CTkButton(self.excl_frame, text="Kaldır", width=70, height=24, fg_color=BAD,
                              hover_color=theme.BTN_BAD_HOVER,
                              command=lambda k=kind, v=it: self.remove_exclusion(k, v)).grid(
                    row=r, column=1, padx=(8, 0))
                r += 1
        if r == 0:
            ctk.CTkLabel(self.excl_frame, text="Dışlama yok.", text_color=MUTED, anchor="w").grid(
                row=0, column=0, sticky="w")

    def add_folder(self) -> None:
        path = filedialog.askdirectory(title="Dışlanacak klasör")
        if path:
            self.add_exclusion("path", str(Path(path)))

    def add_text(self, kind: str) -> None:
        title = {"extension": "Dışlanacak uzantı (örn. log)", "process": "Dışlanacak işlem (örn. derleyici.exe)"}[kind]
        dialog = ctk.CTkInputDialog(text=title, title="Dışlama ekle")
        value = dialog.get_input()
        if value:
            self.add_exclusion(kind, value)

    def add_exclusion(self, kind: str, value: str) -> None:
        if not messagebox.askyesno(
                "Dışlama ekle", f"'{value}' Defender taramasından dışlanacak. Dışlanan konumdaki zararlılar "
                                "bulunmaz.\nDevam edilsin mi?", icon="warning"):
            return
        self._exclusion("add", kind, value)

    def remove_exclusion(self, kind: str, value: str) -> None:
        self._exclusion("remove", kind, value)

    def _exclusion(self, op: str, kind: str, value: str) -> None:
        self.say("Dışlama güncelleniyor… (yönetici izni istenebilir)")

        def run():
            return actions.exclusion_op(op, kind, value)

        def done(res, exc):
            self.say(str(exc) if exc else res.message, error=exc is not None or not res.ok)
            self.load_exclusions()

        self.app.worker.submit(run, done)
