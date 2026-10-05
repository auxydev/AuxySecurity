"""Tarama sayfasi: hizli / tam / ozel tarama, iptal, imza guncelleme, tehditler ve gecmis."""

from __future__ import annotations

import time
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from auxy.core import actions, scan, threats
from auxy.gui import theme
from auxy.gui.widgets import page_header

MUTED = theme.MUTED


def format_detection(d: threats.Detection) -> str:
    when = d.time.strftime("%Y-%m-%d %H:%M") if d.time else "?"
    state = "işlem uygulandı" if d.handled else "beklemede"
    lines = [f"{when}   {d.severity:<11}  {d.name}   [{state}]"]
    lines += [f"      {p}" for p in d.paths]
    return "\n".join(lines)


def format_history_item(r: scan.ScanResult) -> str:
    when = r.started.replace("T", " ")[:16]
    target = f"  {r.path}" if r.path else ""
    return f"{when}   {r.summary()}  ({scan.format_duration(r.seconds)}){target}"


class ScanPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.manager = scan.ScanManager()
        self._started_at: float | None = None
        self._scan_title = ""
        self._cancel_all = False
        self.columnconfigure(0, weight=1)
        self.rowconfigure(5, weight=1)
        self.rowconfigure(7, weight=1)

        head0 = page_header(self, "Tarama", "Cihazını virüs ve zararlı yazılımlara karşı tara. "
                                            "Dosyaları pencereye sürükleyip bırakarak da tarayabilirsin.")
        self.sig_btn = ctk.CTkButton(head0.actions, text="İmzaları güncelle", width=150, fg_color="transparent",
                                     border_width=1, text_color=theme.TEXT, hover_color=theme.SURFACE_ALT,
                                     command=self.update_sigs)
        self.sig_btn.pack(side="right")

        # ---- tarama turleri: uc secenek kutusu
        tiles = ctk.CTkFrame(self, fg_color="transparent")
        tiles.grid(row=1, column=0, sticky="ew")
        self.start_buttons = []
        specs = (("Hızlı tarama", "Sık kullanılan konumlar. Genelde 1-2 dakika.",
                  [("Başlat", lambda: self.start(scan.QUICK))]),
                 ("Tam tarama", "Tüm sürücüler. Uzun sürebilir.", [("Başlat", lambda: self.start(scan.FULL))]),
                 ("Özel tarama", "Seçtiğin klasör ya da dosya.",
                  [("Klasör seç…", self.pick_folder), ("Dosya seç…", self.pick_file)]))
        for i, (title, desc, buttons) in enumerate(specs):
            tiles.columnconfigure(i, weight=1, uniform="scan")
            box = ctk.CTkFrame(tiles, corner_radius=14, border_width=1)
            box.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 5, 0 if i == 2 else 5))
            ctk.CTkLabel(box, text=title, font=ctk.CTkFont(size=16, weight="bold"), anchor="w").pack(
                anchor="w", padx=16, pady=(14, 0))
            ctk.CTkLabel(box, text=desc, anchor="w", justify="left", text_color=theme.MUTED, wraplength=190,
                         font=ctk.CTkFont(size=12)).pack(anchor="w", padx=16, pady=(2, 10))
            row = ctk.CTkFrame(box, fg_color="transparent")
            row.pack(anchor="w", padx=16, pady=(0, 14))
            for text, cmd in buttons:
                b = ctk.CTkButton(row, text=text, width=96 if len(buttons) > 1 else 110, height=34, command=cmd)
                b.pack(side="left", padx=(0, 6))
                self.start_buttons.append(b)

        # ---- ilerleme / durum
        prog = ctk.CTkFrame(self, fg_color="transparent")
        prog.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        prog.columnconfigure(0, weight=1)
        self.progress = ctk.CTkProgressBar(prog, mode="determinate")
        self.progress.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self.progress.set(0)
        self.progress.grid_remove()  # bosta gorunmesin (customtkinter sol uc noktasi kozmetigi)
        self.status = ctk.CTkLabel(prog, text="Hazır.", anchor="w", justify="left", wraplength=620,
                                   text_color=theme.MUTED)
        self.status.grid(row=1, column=0, sticky="w")
        self.cancel_btn = ctk.CTkButton(prog, text="Taramayı iptal et", width=140, height=30, fg_color=theme.BTN_BAD,
                                        hover_color=theme.BTN_BAD_HOVER, state="disabled", command=self.cancel)
        self.cancel_btn.grid(row=0, column=1, rowspan=2, padx=(8, 0))

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=4, column=0, sticky="ew", pady=(16, 6))
        ctk.CTkLabel(head, text="Bulunan tehditler", font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")
        ctk.CTkButton(head, text="Yenile", width=70, height=28, command=self.refresh_lists).pack(side="right")
        self.clean_btn = ctk.CTkButton(head, text="Etkin tehditleri temizle (Defender)", width=230, height=28,
                                       fg_color=theme.BTN_BAD, hover_color=theme.BTN_BAD_HOVER, command=self.clean_active)
        # yalnizca etkin tehdit varsa gorunur (_show_threats)
        self.threat_box = ctk.CTkScrollableFrame(self, height=120, corner_radius=14, border_width=1)
        self.threat_box.grid(row=5, column=0, sticky="nsew")
        self.threat_box.columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text="Tarama geçmişi", font=ctk.CTkFont(size=16, weight="bold"),
                     anchor="w").grid(row=6, column=0, sticky="w", pady=(16, 6))
        self.history_box = ctk.CTkTextbox(self, height=100, wrap="none")
        self.history_box.grid(row=7, column=0, sticky="nsew")
        self.refresh_lists()
    # ---- listeler ----
    def refresh_lists(self) -> None:
        self.app.worker.submit(threats.read_detections, self._show_threats)
        self._fill(self.history_box,
                   "\n".join(format_history_item(r) for r in reversed(scan.load_history()[-10:]))
                   or "(henüz tarama yok)")

    def _show_threats(self, items, exc) -> None:
        for w in self.threat_box.winfo_children():
            w.destroy()
        has_active = exc is None and any(d.active for d in items)
        if has_active and not self.clean_btn.winfo_manager():
            self.clean_btn.pack(side="right", padx=(0, 8))
        elif not has_active and self.clean_btn.winfo_manager():
            self.clean_btn.pack_forget()
        if exc is not None or not items:
            text = f"Tehditler okunamadı: {exc}" if exc is not None else "Kayıtlı tehdit yok."
            ctk.CTkLabel(self.threat_box, text=text, text_color=MUTED, anchor="w").grid(
                row=0, column=0, sticky="w", padx=8, pady=6)
            return
        r = 0
        for d in items[:30]:
            when = d.time.strftime("%Y-%m-%d %H:%M") if d.time else "?"
            state = "işlem uygulandı" if d.handled else "beklemede"
            ctk.CTkLabel(self.threat_box, anchor="w", font=ctk.CTkFont(weight="bold"),
                         text=f"{when}   {d.severity}   {d.name}   [{state}]").grid(
                row=r, column=0, columnspan=2, sticky="w", padx=8, pady=(6, 0))
            r += 1
            for p in d.paths:
                ctk.CTkLabel(self.threat_box, text=p, anchor="w", text_color=MUTED,
                             wraplength=520, justify="left").grid(row=r, column=0, sticky="w", padx=(22, 4))
                if Path(p).is_file():  # Defender dokunmadiysa / geri yuklenmisse kasaya alinabilir
                    ctk.CTkButton(self.threat_box, text="Kasaya al", width=80, height=24,
                                  command=lambda path=p, n=d.name: self.app.pages["quarantine"]
                                  .quarantine(path, f"Tehdit: {n}")).grid(row=r, column=1, padx=6)
                r += 1

    @staticmethod
    def _fill(box: ctk.CTkTextbox, text: str) -> None:
        box.configure(state="normal")
        box.delete("1.0", "end")
        box.insert("1.0", text)
        box.configure(state="disabled")

    # ---- tarama ----
    def pick_folder(self) -> None:
        path = filedialog.askdirectory(title="Taranacak klasör")
        if path:
            self.start(scan.CUSTOM, path)

    def pick_file(self) -> None:
        path = filedialog.askopenfilename(title="Taranacak dosya")
        if path:
            self.start(scan.CUSTOM, path)

    def start(self, scan_type: int, path: str | None = None) -> None:
        if self.manager.running:
            return
        self._scan_title = scan.TYPE_NAMES[scan_type]
        self._set_busy(True)
        self._started_at = time.monotonic()
        self._tick()
        self.app.worker.submit(lambda: self.manager.run(scan_type, path), self._on_done, long=True)

    def scan_paths(self, paths: list[str]) -> None:
        """Birakilan birden fazla yolu sirayla tarar (tek yol: normal ozel tarama)."""
        if self.manager.running or self._started_at is not None:
            self.status.configure(text="Zaten bir tarama sürüyor.", text_color=theme.BAD)
            return
        if len(paths) == 1:
            self.start(scan.CUSTOM, paths[0])
            return
        self._scan_title = f"{len(paths)} öğe taranıyor"
        self._cancel_all = False
        self._set_busy(True)
        self._started_at = time.monotonic()
        self._tick()

        def job():
            results = []
            for p in paths:
                if self._cancel_all:
                    break
                results.append(self.manager.run(scan.CUSTOM, p))
            return results

        self.app.worker.submit(job, self._on_done_many, long=True)

    def _on_done_many(self, results, exc) -> None:
        self._started_at = None
        self._set_busy(False)
        if exc is not None:
            self.status.configure(text=str(exc), text_color=theme.BAD)
        else:
            found = sorted({t for r in results for t in r.threats})
            text = f"{len(results)} öğe tarandı: " + (f"{len(found)} tehdit bulundu ({', '.join(found)})."
                                                      if found else "tehdit bulunamadı.")
            self.status.configure(text=text, text_color=theme.BAD if found else theme.GOOD)
        self.refresh_lists()
        self.app.refresh()

    def _tick(self) -> None:
        if self._started_at is None:
            return
        elapsed = scan.format_duration(time.monotonic() - self._started_at)
        self.status.configure(text=f"{self._scan_title} sürüyor… {elapsed}", text_color=theme.TEXT)
        self.after(1000, self._tick)  # yalnizca tarama sirasinda

    def _on_done(self, res, exc) -> None:
        self._started_at = None
        self._set_busy(False)
        if exc is not None:
            self.status.configure(text=str(exc), text_color=theme.BAD)
        else:
            bad = res.status == scan.FAILED or bool(res.threats)
            self.status.configure(
                text=f"{res.summary()}  ({scan.format_duration(res.seconds)})",
                text_color=theme.BAD if bad else theme.GOOD,
            )
        self.refresh_lists()
        self.app.refresh()

    def clean_active(self) -> None:
        if not messagebox.askyesno("Etkin tehditleri temizle",
                                   "Defender, bilgisayardaki ETKİN tehditleri temizleyecek (Remove-MpThreat).\n"
                                   "Devam edilsin mi?"):
            return
        self.status.configure(text="Etkin tehditler temizleniyor… (yönetici izni istenebilir)",
                              text_color=theme.TEXT)

        def done(res, exc):
            ok = exc is None and res.ok
            self.status.configure(text=str(exc) if exc else res.message, text_color=theme.GOOD if ok else theme.BAD)
            self.refresh_lists()
            self.app.refresh()

        self.app.worker.submit(lambda: actions.defender_quarantine_op("clean"), done)

    def cancel(self) -> None:
        self.cancel_btn.configure(state="disabled")
        self._cancel_all = True  # coklu taramada siradaki yollar atlanir
        self.manager.mark_cancel_requested()
        self.status.configure(text="İptal ediliyor… (yönetici izni gerekebilir)")
        self.app.worker.submit(actions.cancel_scan, self._on_cancel)

    def _on_cancel(self, res, exc) -> None:
        if exc is not None or not res.ok:
            msg = str(exc) if exc is not None else res.message
            self.manager._cancel_requested = False  # iptal olmadi; tarama sonucu normal islensin
            if self.manager.running:
                self.cancel_btn.configure(state="normal")
            self.status.configure(text=msg, text_color=theme.BAD)

    def update_sigs(self) -> None:
        self.sig_btn.configure(state="disabled")
        self.status.configure(text="İmzalar güncelleniyor… (~20 sn)", text_color=theme.TEXT)

        def done(res, exc):
            self.sig_btn.configure(state="normal")
            if exc is not None:
                self.status.configure(text=str(exc), text_color=theme.BAD)
            else:
                ok, msg = res
                self.status.configure(text=msg, text_color=theme.GOOD if ok else theme.BAD)
            self.app.refresh()

        self.app.worker.submit(scan.update_signatures, done, long=True)

    def _set_busy(self, busy: bool) -> None:
        for b in self.start_buttons:
            b.configure(state="disabled" if busy else "normal")
        self.cancel_btn.configure(state="normal" if busy else "disabled")
        if busy:
            self.progress.grid()
            self.progress.configure(mode="indeterminate")
            self.progress.start()
        else:
            self.progress.stop()
            self.progress.configure(mode="determinate")
            self.progress.set(0)
            self.progress.grid_remove()

