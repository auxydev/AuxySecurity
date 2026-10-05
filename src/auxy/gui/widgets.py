"""Ortak arayuz bilesenleri: sayfa basligi, kart (aciklamali satirlar), acilir "Gelismis" bolumu, ozet kutusu.

Amac: her sayfa ayni dili konussun (baslik + tek cumlelik aciklama, kartlar, satir basina acik Turkce aciklama),
teknik ayrintilar ise varsayilan olarak KAPALI "Gelismis" bolumlerinde dursun.
"""

from __future__ import annotations

import customtkinter as ctk

from auxy.gui import theme

WRAP = 520


def page_header(master, title: str, subtitle: str = "", row: int = 0) -> ctk.CTkFrame:
    """Sayfa basligi (buyuk baslik + altinda aciklama). `.actions` sagdaki dugme alani, `.message` durum metni."""
    head = ctk.CTkFrame(master, fg_color="transparent")
    head.grid(row=row, column=0, sticky="ew", pady=(0, 12))
    head.columnconfigure(0, weight=1)
    left = ctk.CTkFrame(head, fg_color="transparent")
    left.grid(row=0, column=0, sticky="w")
    ctk.CTkLabel(left, text=title, font=ctk.CTkFont(size=26, weight="bold"), anchor="w").pack(anchor="w")
    if subtitle:
        ctk.CTkLabel(left, text=subtitle, text_color=theme.MUTED, anchor="w", justify="left",
                     wraplength=560).pack(anchor="w", pady=(2, 0))
    head.actions = ctk.CTkFrame(head, fg_color="transparent")
    head.actions.grid(row=0, column=1, sticky="e")
    head.message = ctk.CTkLabel(head.actions, text="", anchor="e", justify="right", wraplength=330, text_color=theme.TEXT)
    return head


class Card(ctk.CTkFrame):
    """Yuvarlak kart: baslik, (istege bagli) aciklama ve satirlar. Satirlar 3 sutunlu izgarada: 0=metin, 2=denetim."""

    def __init__(self, master, title: str, row: int, subtitle: str = ""):
        super().__init__(master, corner_radius=14, border_width=1)
        self.grid(row=row, column=0, sticky="ew", pady=(0, 14), padx=(0, 6))
        self.columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text=title, font=ctk.CTkFont(size=16, weight="bold"), anchor="w").grid(
            row=0, column=0, columnspan=3, sticky="w", padx=18, pady=(14, 2 if subtitle else 8))
        self.next_row = 1
        if subtitle:
            ctk.CTkLabel(self, text=subtitle, anchor="w", justify="left", wraplength=WRAP + 120,
                         text_color=theme.MUTED).grid(row=1, column=0, columnspan=3, sticky="w", padx=18, pady=(0, 8))
            self.next_row = 2

    def line(self, text: str = "", color=None) -> ctk.CTkLabel:
        lbl = ctk.CTkLabel(self, text=text, anchor="w", justify="left", wraplength=WRAP + 120,
                           text_color=color or theme.TEXT)
        lbl.grid(row=self.next_row, column=0, columnspan=3, sticky="w", padx=18, pady=3)
        self.next_row += 1
        return lbl

    def label(self, text: str, hint: str = "", row: int | None = None) -> ctk.CTkLabel:
        """Sol sutun: baslik + altinda soluk aciklama. Aciklama etiketi `.hint_label` ile erisilir."""
        r = self.next_row if row is None else row
        box = ctk.CTkFrame(self, fg_color="transparent")
        box.grid(row=r, column=0, sticky="w", padx=18, pady=7)
        title = ctk.CTkLabel(box, text=text, anchor="w", font=ctk.CTkFont(size=14))
        title.pack(anchor="w")
        title.hint_label = None
        if hint:
            title.hint_label = ctk.CTkLabel(box, text=hint, anchor="w", justify="left", wraplength=WRAP,
                                            text_color=theme.MUTED, font=ctk.CTkFont(size=12))
            title.hint_label.pack(anchor="w")
        return title

    def switch_row(self, label: str, command, hint: str = "") -> ctk.CTkSwitch:
        self.label(label, hint)
        sw = ctk.CTkSwitch(self, text="", width=46, command=command)
        sw.grid(row=self.next_row, column=2, padx=(0, 18))
        self.next_row += 1
        return sw

    def menu_row(self, label: str, values: list[str], command, hint: str = "", width: int = 150) -> ctk.CTkOptionMenu:
        self.label(label, hint)
        menu = ctk.CTkOptionMenu(self, values=values, width=width, command=command)
        menu.grid(row=self.next_row, column=2, padx=(0, 18))
        self.next_row += 1
        return menu

    def button_bar(self, pady=(4, 12)) -> ctk.CTkFrame:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=self.next_row, column=0, columnspan=3, sticky="ew", padx=18, pady=pady)
        self.next_row += 1
        return bar

    def collapsible(self, title: str, open_: bool = False) -> "Collapsible":
        c = Collapsible(self, title, open_)
        c.grid(row=self.next_row, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 10))
        self.next_row += 1
        return c


class Collapsible(ctk.CTkFrame):
    """"Gelismis" bolumu: baslik tiklaninca acilir/kapanir. Icerik `.body`'ye konur; varsayilan KAPALI."""

    def __init__(self, master, title: str, open_: bool = False):
        super().__init__(master, fg_color="transparent")
        self.columnconfigure(0, weight=1)
        self.title = title
        self.btn = ctk.CTkButton(self, text="", anchor="w", height=30, fg_color="transparent",
                                 hover_color=theme.SURFACE_ALT, text_color=theme.MUTED, command=self.toggle)
        self.btn.grid(row=0, column=0, sticky="ew")
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.columnconfigure(0, weight=1)
        self.is_open = open_
        self._render()

    def toggle(self) -> None:
        self.is_open = not self.is_open
        self._render()

    def _render(self) -> None:
        self.btn.configure(text=("▾  " if self.is_open else "▸  ") + self.title)
        if self.is_open:
            self.body.grid(row=1, column=0, sticky="ew", padx=6)
        else:
            self.body.grid_remove()


class Tile(ctk.CTkFrame):
    """Ozet kutusu: kucuk baslik, buyuk deger (durum rengiyle) ve altta kisa not."""

    def __init__(self, master, caption: str):
        super().__init__(master, corner_radius=14, border_width=1)
        self.columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text=caption, anchor="w", text_color=theme.MUTED, font=ctk.CTkFont(size=12)).grid(
            row=0, column=0, sticky="w", padx=16, pady=(14, 0))
        self.value = ctk.CTkLabel(self, text="—", anchor="w", font=ctk.CTkFont(size=21, weight="bold"))
        self.value.grid(row=1, column=0, sticky="w", padx=16, pady=(0, 0))
        self.note = ctk.CTkLabel(self, text="", anchor="w", text_color=theme.MUTED, font=ctk.CTkFont(size=12),
                                 wraplength=150, justify="left")
        self.note.grid(row=2, column=0, sticky="w", padx=16, pady=(0, 14))

    def set(self, value: str, color=None, note: str = "") -> None:
        self.value.configure(text=value, text_color=color or theme.TEXT)
        self.note.configure(text=note)


def pill(master, text: str, color) -> ctk.CTkLabel:
    """Durum etiketi: renkli yazi + hafif zemin."""
    return ctk.CTkLabel(master, text=text, text_color=color, corner_radius=10, fg_color=theme.SURFACE_ALT,
                        font=ctk.CTkFont(size=13, weight="bold"), padx=10, pady=2)
