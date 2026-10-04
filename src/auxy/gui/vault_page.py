"""Karantina sayfasi: kasadaki dosyalari listeler, geri yukler, kalici siler, dosya ekler."""

from __future__ import annotations

from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from auxy.core.vault import Vault, VaultItem

MUTED = ("gray40", "gray60")
_vault: Vault | None = None


def get_vault() -> Vault:
    """Kasayi (DPAPI anahtariyla) ilk kullanimda acar; yalnizca is parcaciklarindan cagrilir."""
    global _vault
    if _vault is None:
        _vault = Vault.default()
    return _vault


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"


def format_meta(item: VaultItem) -> str:
    when = item.quarantined_at.replace("T", " ")[:16]
    return f"{when}  •  {human_size(item.size)}  •  {item.reason}"


class VaultPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ctk.CTkLabel(head, text="Karantina", font=ctk.CTkFont(size=22, weight="bold")).pack(side="left")
        ctk.CTkButton(head, text="Yenile", width=70, command=self.refresh).pack(side="right")
        ctk.CTkButton(head, text="Dosya ekle…", width=110, command=self.add_file).pack(
            side="right", padx=(0, 8))

        ctk.CTkLabel(
            self, anchor="w", justify="left", wraplength=640, text_color=MUTED,
            text="Kasadaki dosyalar AES-256 ile şifrelenir ve çalıştırılamaz. "
                 "Orijinal dosya, kasadaki kopya doğrulandıktan sonra silinir.",
        ).grid(row=1, column=0, sticky="w")
        self.status = ctk.CTkLabel(self, text="", anchor="w", justify="left", wraplength=640)
        self.status.grid(row=2, column=0, sticky="w", pady=(6, 6))
        self.list = ctk.CTkScrollableFrame(self, corner_radius=12)
        self.list.grid(row=3, column=0, sticky="nsew")
        self.list.columnconfigure(0, weight=1)

    # ---- liste ----
    def refresh(self) -> None:
        self.app.worker.submit(lambda: get_vault().list(), self._show)

    def _show(self, items, exc) -> None:
        for w in self.list.winfo_children():
            w.destroy()
        if exc is not None:
            self.say(f"Kasa açılamadı: {exc}", error=True)
            return
        if not items:
            ctk.CTkLabel(self.list, text="Kasa boş.", text_color=MUTED).grid(
                row=0, column=0, padx=14, pady=14, sticky="w")
            return
        for i, item in enumerate(items):
            row = ctk.CTkFrame(self.list, corner_radius=8)
            row.grid(row=i, column=0, sticky="ew", padx=4, pady=4)
            row.columnconfigure(0, weight=1)
            ctk.CTkLabel(row, text=item.name, anchor="w", font=ctk.CTkFont(weight="bold")).grid(
                row=0, column=0, sticky="w", padx=12, pady=(8, 0))
            ctk.CTkLabel(row, text=item.original_path, anchor="w", text_color=MUTED,
                         wraplength=430, justify="left").grid(row=1, column=0, sticky="w", padx=12)
            ctk.CTkLabel(row, text=format_meta(item), anchor="w", text_color=MUTED).grid(
                row=2, column=0, sticky="w", padx=12, pady=(0, 8))
            ctk.CTkButton(row, text="Geri yükle", width=90,
                          command=lambda it=item: self.restore(it)).grid(
                row=0, column=1, rowspan=3, padx=(0, 6))
            ctk.CTkButton(row, text="Sil", width=60, fg_color="#d64545", hover_color="#b53a3a",
                          command=lambda it=item: self.delete(it)).grid(
                row=0, column=2, rowspan=3, padx=(0, 12))

    def say(self, text: str, error: bool = False) -> None:
        self.status.configure(text=text, text_color="#d64545" if error else ("gray20", "gray85"))

    # ---- eylemler ----
    def add_file(self) -> None:
        path = filedialog.askopenfilename(title="Kasaya alınacak dosya")
        if path:
            self.quarantine(path, "Elle eklendi")

    def quarantine(self, path: str, reason: str) -> None:
        """Baska sayfalardan da cagrilir (tehdit listesi)."""
        self.say(f"Kasaya alınıyor: {Path(path).name}…")
        self.app.worker.submit(lambda: get_vault().add(path, reason), self._on_added)

    def _on_added(self, item, exc) -> None:
        if exc is not None:
            self.say(str(exc), error=True)
        else:
            self.say(f"Kasaya alındı: {item.name}")
        self.refresh()
        self.app.pages["scan"].refresh_lists()

    def restore(self, item: VaultItem) -> None:
        if not messagebox.askyesno(
            "Geri yükle",
            f"'{item.name}' şüpheli olarak kasaya alınmıştı.\nGeri yüklemek bilgisayarını riske atabilir. "
            "Devam edilsin mi?",
        ):
            return
        dest = None
        if Path(item.original_path).exists():
            dest = filedialog.asksaveasfilename(
                title="Hedef dosya zaten var; başka bir yol seç", initialfile=item.name)
            if not dest:
                return
        self.say(f"Geri yükleniyor: {item.name}…")
        self.app.worker.submit(lambda: get_vault().restore(item.id, dest), self._on_restored)

    def _on_restored(self, out, exc) -> None:
        self.say(str(exc) if exc is not None else f"Geri yüklendi: {out}", error=exc is not None)
        self.refresh()

    def delete(self, item: VaultItem) -> None:
        if not messagebox.askyesno(
            "Kalıcı sil", f"'{item.name}' kasadan KALICI olarak silinecek. Bu işlem geri alınamaz.\nDevam edilsin mi?",
            icon="warning",
        ):
            return
        self.app.worker.submit(lambda: get_vault().delete(item.id),
                               lambda _r, exc: (self.say(str(exc) if exc else f"Silindi: {item.name}",
                                                         error=exc is not None), self.refresh()))
