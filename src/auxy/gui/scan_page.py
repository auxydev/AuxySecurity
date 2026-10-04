"""Tarama sayfasi: hizli / tam / ozel tarama, iptal, imza guncelleme, tehditler ve gecmis."""

from __future__ import annotations

import time
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from auxy.core import actions, scan, threats

MUTED = ("gray40", "gray60")


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
        self.columnconfigure(0, weight=1)
        self.rowconfigure(5, weight=1)
        self.rowconfigure(7, weight=1)

        ctk.CTkLabel(self, text="Tarama", font=ctk.CTkFont(size=22, weight="bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 10))

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew")
        self.start_buttons = [
            ctk.CTkButton(bar, text="Hızlı tarama", width=120,
                          command=lambda: self.start(scan.QUICK)),
            ctk.CTkButton(bar, text="Tam tarama", width=120, command=lambda: self.start(scan.FULL)),
            ctk.CTkButton(bar, text="Klasör tara…", width=120, command=self.pick_folder),
            ctk.CTkButton(bar, text="Dosya tara…", width=120, command=self.pick_file),
        ]
        for b in self.start_buttons:
            b.pack(side="left", padx=(0, 8))
        self.cancel_btn = ctk.CTkButton(bar, text="İptal", width=80, fg_color="#d64545",
                                        hover_color="#b53a3a", state="disabled", command=self.cancel)
        self.cancel_btn.pack(side="left", padx=(8, 0))
        self.sig_btn = ctk.CTkButton(bar, text="İmzaları güncelle", width=140,
                                     fg_color="transparent", border_width=1,
                                     text_color=("gray20", "gray85"), command=self.update_sigs)
        self.sig_btn.pack(side="right")

        self.progress = ctk.CTkProgressBar(self, mode="determinate")
        self.progress.grid(row=2, column=0, sticky="ew", pady=(12, 4))
        self.progress.set(0)
        self.status = ctk.CTkLabel(self, text="Hazır.", anchor="w", justify="left", wraplength=640)
        self.status.grid(row=3, column=0, sticky="w")

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=4, column=0, sticky="ew", pady=(14, 4))
        ctk.CTkLabel(head, text="Tehditler", font=ctk.CTkFont(size=15, weight="bold")).pack(
            side="left")
        ctk.CTkButton(head, text="Yenile", width=70, height=24, command=self.refresh_lists).pack(
            side="right")
        self.threat_box = ctk.CTkScrollableFrame(self, height=140, corner_radius=8)
        self.threat_box.grid(row=5, column=0, sticky="nsew")
        self.threat_box.columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text="Tarama geçmişi", font=ctk.CTkFont(size=15, weight="bold"),
                     anchor="w").grid(row=6, column=0, sticky="w", pady=(14, 4))
        self.history_box = ctk.CTkTextbox(self, height=110, wrap="none")
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

    def _tick(self) -> None:
        if self._started_at is None:
            return
        elapsed = scan.format_duration(time.monotonic() - self._started_at)
        self.status.configure(text=f"{self._scan_title} sürüyor… {elapsed}", text_color=("gray20", "gray85"))
        self.after(1000, self._tick)  # yalnizca tarama sirasinda

    def _on_done(self, res, exc) -> None:
        self._started_at = None
        self._set_busy(False)
        if exc is not None:
            self.status.configure(text=str(exc), text_color="#d64545")
        else:
            bad = res.status == scan.FAILED or bool(res.threats)
            self.status.configure(
                text=f"{res.summary()}  ({scan.format_duration(res.seconds)})",
                text_color="#d64545" if bad else "#2e9e5b",
            )
        self.refresh_lists()
        self.app.refresh()

    def cancel(self) -> None:
        self.cancel_btn.configure(state="disabled")
        self.manager.mark_cancel_requested()
        self.status.configure(text="İptal ediliyor… (yönetici izni gerekebilir)")
        self.app.worker.submit(actions.cancel_scan, self._on_cancel)

    def _on_cancel(self, res, exc) -> None:
        if exc is not None or not res.ok:
            msg = str(exc) if exc is not None else res.message
            self.manager._cancel_requested = False  # iptal olmadi; tarama sonucu normal islensin
            if self.manager.running:
                self.cancel_btn.configure(state="normal")
            self.status.configure(text=msg, text_color="#d64545")

    def update_sigs(self) -> None:
        self.sig_btn.configure(state="disabled")
        self.status.configure(text="İmzalar güncelleniyor… (~20 sn)", text_color=("gray20", "gray85"))

        def done(res, exc):
            self.sig_btn.configure(state="normal")
            if exc is not None:
                self.status.configure(text=str(exc), text_color="#d64545")
            else:
                ok, msg = res
                self.status.configure(text=msg, text_color="#2e9e5b" if ok else "#d64545")
            self.app.refresh()

        self.app.worker.submit(scan.update_signatures, done, long=True)

    def _set_busy(self, busy: bool) -> None:
        for b in self.start_buttons:
            b.configure(state="disabled" if busy else "normal")
        self.cancel_btn.configure(state="normal" if busy else "disabled")
        if busy:
            self.progress.configure(mode="indeterminate")
            self.progress.start()
        else:
            self.progress.stop()
            self.progress.configure(mode="determinate")
            self.progress.set(0)

