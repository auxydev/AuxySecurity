"""Guvenlik sayfasi: guvenlik duvari, SmartScreen, cihaz guvenligi, exploit protection, dislamalar."""

from __future__ import annotations

from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from auxy.core import actions, winsec

MUTED = ("gray40", "gray60")
GOOD, BAD = "#2e9e5b", "#d64545"
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


class Card(ctk.CTkFrame):
    def __init__(self, master, title: str, row: int):
        super().__init__(master, corner_radius=12)
        self.grid(row=row, column=0, sticky="ew", pady=(0, 12), padx=(0, 6))
        self.columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text=title, font=ctk.CTkFont(size=15, weight="bold"), anchor="w").grid(
            row=0, column=0, columnspan=3, sticky="w", padx=16, pady=(10, 4))
        self.next_row = 1

    def line(self, text: str = "", color=None) -> ctk.CTkLabel:
        lbl = ctk.CTkLabel(self, text=text, anchor="w", justify="left", wraplength=560,
                           text_color=color or ("gray20", "gray85"))
        lbl.grid(row=self.next_row, column=0, columnspan=3, sticky="w", padx=16, pady=2)
        self.next_row += 1
        return lbl

    def switch_row(self, label: str, command) -> ctk.CTkSwitch:
        ctk.CTkLabel(self, text=label, anchor="w").grid(
            row=self.next_row, column=0, sticky="w", padx=16, pady=5)
        sw = ctk.CTkSwitch(self, text="", width=46, command=command)
        sw.grid(row=self.next_row, column=2, padx=(0, 16))
        self.next_row += 1
        return sw


class SecurityPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ctk.CTkLabel(head, text="Güvenlik", font=ctk.CTkFont(size=22, weight="bold")).pack(side="left")
        ctk.CTkButton(head, text="Yenile", width=70, command=self.refresh).pack(side="right")
        self.message = ctk.CTkLabel(head, text="", anchor="e", wraplength=420, justify="right")
        self.message.pack(side="right", padx=12)

        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)

        # Genel durum
        c = Card(body, "Genel durum (Windows Güvenlik Merkezi)", 0)
        self.products_lbl = c.line("Okunuyor…")

        # Guvenlik duvari
        c = Card(body, "Güvenlik duvarı", 1)
        self.sw: dict[str, ctk.CTkSwitch] = {}
        for key in ("fw_domain", "fw_private", "fw_public"):
            self.sw[key] = c.switch_row(winsec.WINSEC_SETTINGS[key].label.split(": ")[1],
                                        lambda k=key: self._toggle(k))
        c.line("Gelen bağlantılar Windows varsayılanına göre engellenir.", MUTED)

        # SmartScreen
        c = Card(body, "Uygulama ve tarayıcı denetimi (SmartScreen)", 2)
        ctk.CTkLabel(c, text="Uygulamalar ve dosyalar", anchor="w").grid(
            row=c.next_row, column=0, sticky="w", padx=16, pady=5)
        self.ss_menu = ctk.CTkOptionMenu(c, values=list(SMARTSCREEN_TR), width=110,
                                         command=self._set_smartscreen)
        self.ss_menu.grid(row=c.next_row, column=2, padx=(0, 16))
        c.next_row += 1
        self.sw["smartscreen_store"] = c.switch_row("Microsoft Store uygulamaları",
                                                    lambda: self._toggle("smartscreen_store"))

        # Cihaz guvenligi
        c = Card(body, "Cihaz güvenliği", 3)
        self.device_lbl = c.line("Okunuyor…")
        self.sw["hvci"] = c.switch_row("Çekirdek yalıtımı: Bellek bütünlüğü",
                                       lambda: self._toggle("hvci"))
        self.hvci_note = c.line(winsec.WINSEC_SETTINGS["hvci"].hint, MUTED)
        row = ctk.CTkFrame(c, fg_color="transparent")
        row.grid(row=c.next_row, column=0, columnspan=3, sticky="ew", padx=16, pady=(2, 10))
        c.next_row += 1
        ctk.CTkButton(row, text="TPM bilgisini oku (yönetici)", width=200, height=28,
                      command=self.read_tpm).pack(side="left")
        self.tpm_lbl = ctk.CTkLabel(row, text="", anchor="w", justify="left", wraplength=360)
        self.tpm_lbl.pack(side="left", padx=10)

        # Exploit protection (salt-okunur)
        c = Card(body, "Exploit protection (sistem, salt-okunur)", 4)
        self.exploit_lbl = c.line("Okunuyor…")
        c.line("Windows tek tek 'varsayılana dön' sunmadığı için bu bölümde değişiklik yapılmaz.", MUTED)

        # Dislamalar
        c = Card(body, "Defender dışlamaları", 5)
        c.line("Dışlanan konumlar taranmaz. Okumak ve değiştirmek yönetici izni (UAC) ister.", MUTED)
        bar = ctk.CTkFrame(c, fg_color="transparent")
        bar.grid(row=c.next_row, column=0, columnspan=3, sticky="ew", padx=16, pady=4)
        c.next_row += 1
        ctk.CTkButton(bar, text="Listele", width=70, command=self.load_exclusions).pack(side="left")
        ctk.CTkButton(bar, text="Klasör ekle…", width=100, command=self.add_folder).pack(side="left", padx=6)
        ctk.CTkButton(bar, text="Uzantı ekle…", width=100, command=lambda: self.add_text("extension")).pack(side="left")
        ctk.CTkButton(bar, text="İşlem ekle…", width=100, command=lambda: self.add_text("process")).pack(
            side="left", padx=6)
        self.excl_frame = ctk.CTkFrame(c, fg_color="transparent")
        self.excl_frame.grid(row=c.next_row, column=0, columnspan=3, sticky="ew", padx=16, pady=(0, 10))
        self.excl_frame.columnconfigure(0, weight=1)
        self.excl_note = ctk.CTkLabel(self.excl_frame, text="(Listelemek için 'Listele'ye bas.)",
                                      text_color=MUTED, anchor="w")
        self.excl_note.grid(row=0, column=0, sticky="w")

    # ---- mesaj ----
    def say(self, text: str, error: bool = False) -> None:
        self.message.configure(text=text, text_color=BAD if error else ("gray20", "gray85"))

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
                                     text_color="#d9932b")
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
                text_color=("gray20", "gray85"))

        self.app.worker.submit(actions.read_tpm, done)

    # ---- dislamalar ----
    def load_exclusions(self) -> None:
        self.excl_note.configure(text="Okunuyor… (yönetici izni istenebilir)")
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
                              hover_color="#b53a3a",
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
