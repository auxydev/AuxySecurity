"""Gorunum: modern renk paleti, yuvarlak kartlar, Segoe UI yazi tipi ve kenar cubugu simgeleri.

customtkinter'in varsayilan temasi (Roboto, gri paneller, mavi dugmeler) eski gorunuyordu. `apply()` kutuphanenin
tema sozlugunu BIR KEZ, hicbir pencere olusturulmadan once gunceller; sayfa kodu degismeden yeni gorunumu alir.
Acik/koyu mod sistemi izler (her renk (acik, koyu) cifti).
"""

from __future__ import annotations

from functools import lru_cache

import customtkinter as ctk

# (acik, koyu)
BG = ("#f1f4f9", "#0d1220")
SURFACE = ("#ffffff", "#161d2d")
SURFACE_ALT = ("#f5f7fb", "#1d2639")      # kart icindeki ikinci duzey yuzey
BORDER = ("#e2e8f1", "#263048")
TEXT = ("#0f172a", "#e8edf6")
MUTED = ("#64748b", "#8c98ae")
ACCENT = ("#2563eb", "#3b82f6")
ACCENT_HOVER = ("#1d4ed8", "#2563eb")
TRACK = ("#cbd5e1", "#334155")           # kapali anahtar yolu
GOOD = ("#15803d", "#4ade80")      # metin renkleri (acik, koyu): her iki modda okunur
WARN = ("#b45309", "#fbbf24")
BAD = ("#c62828", "#f87171")
BTN_BAD = ("#dc3545", "#e5484d")    # kirmizi dugme dolgusu
BTN_BAD_HOVER = ("#b02a37", "#c93d42")
OK_BG, WARN_BG, BAD_BG = "#16a34a", "#d9822b", "#d64545"  # pano bandi

SIDEBAR = ("#ffffff", "#0b1220")          # acik modda acik kenar cubugu (icerikle uyumlu), koyuda koyu
SIDEBAR_TEXT = ("#475569", "#aab6cc")
SIDEBAR_HOVER = ("#eef2f9", "#17223a")
SIDEBAR_MUTED = ("#8a97ac", "#6b7a96")
SIDEBAR_ICON = ("#475569", "#aab6cc")    # simge cizim renkleri (acik, koyu)

FONT_FAMILY = "Segoe UI"
ICON_FONT = r"C:\Windows\Fonts\SegoeIcons.ttf"  # Windows 11 (Segoe Fluent Icons); yoksa simgesiz devam
GLYPHS = {"dashboard": "\ue80f", "security": "\uea18", "network": "\ue774", "scan": "\ue721", "quarantine": "\ue72e",
          "settings": "\ue713", "log": "\ue7c3"}

_applied = False


def apply() -> None:
    """Tema sozlugunu gunceller (idempotent). Pencere olusturulmadan once cagrilmali."""
    global _applied
    if _applied:
        return
    _applied = True
    t = ctk.ThemeManager.theme
    t["CTk"]["fg_color"] = list(BG)
    t["CTkFont"].update(family=FONT_FAMILY, size=13)
    t["CTkFrame"].update(corner_radius=14, border_width=0,  # kartlar kendi cizgisini ister (border_width=1)
                          fg_color=list(SURFACE), top_fg_color=list(SURFACE),
                         border_color=list(BORDER))
    t["CTkLabel"]["text_color"] = list(TEXT)
    t["CTkButton"].update(corner_radius=9, border_color=["#b6c2d6", "#3a4766"], fg_color=list(ACCENT), hover_color=list(ACCENT_HOVER),
                          text_color=["#ffffff", "#ffffff"], text_color_disabled=["#9aa7bd", "#5b6780"])
    t["CTkSwitch"].update(border_width=3, fg_color=list(TRACK), progress_color=list(ACCENT),
                          button_color=["#3b4a63", "#f1f5f9"], button_hover_color=["#26324a", "#ffffff"],
                          text_color=list(TEXT))
    t["CTkOptionMenu"].update(corner_radius=9, fg_color=list(SURFACE_ALT), button_color=list(ACCENT),
                              button_hover_color=list(ACCENT_HOVER), text_color=list(TEXT))
    t["CTkEntry"].update(corner_radius=9, border_width=1, fg_color=list(SURFACE_ALT), border_color=list(BORDER),
                         text_color=list(TEXT))
    t["CTkTextbox"].update(corner_radius=14, border_width=1, fg_color=list(SURFACE), border_color=list(BORDER),
                           text_color=list(TEXT))
    t["CTkScrollbar"].update(button_color=["#c3ccdb", "#394560"], button_hover_color=["#a3afc4", "#4b5a7a"])
    t["CTkProgressBar"].update(fg_color=list(TRACK), progress_color=list(ACCENT))
    t["CTkSegmentedButton"].update(corner_radius=9, fg_color=list(SURFACE_ALT), selected_color=list(ACCENT),
                                   selected_hover_color=list(ACCENT_HOVER), unselected_color=list(SURFACE_ALT),
                                   unselected_hover_color=list(BORDER), text_color=list(TEXT))
    t["CTkCheckBox"].update(fg_color=list(ACCENT), hover_color=list(ACCENT_HOVER), border_color=list(TRACK),
                            text_color=list(TEXT))
    t["DropdownMenu"].update(fg_color=list(SURFACE), hover_color=list(SURFACE_ALT), text_color=list(TEXT))


@lru_cache(maxsize=32)
def icon(key: str, size: int = 20, color: str = "#ffffff", dark: str | None = None) -> ctk.CTkImage | None:
    """Kenar cubugu simgesi (Segoe Fluent Icons yazi tipinden cizilir). Yazi tipi yoksa None."""
    glyph = GLYPHS.get(key)
    if not glyph:
        return None
    try:
        from PIL import Image, ImageDraw, ImageFont

        scale = 4
        font = ImageFont.truetype(ICON_FONT, size * scale)

        def draw(fill: str):
            img = Image.new("RGBA", (size * scale, size * scale), (0, 0, 0, 0))
            ImageDraw.Draw(img).text((size * scale / 2, size * scale / 2), glyph, font=font, fill=fill, anchor="mm")
            return img.resize((size, size), Image.LANCZOS)

        return ctk.CTkImage(light_image=draw(color), dark_image=draw(dark or color), size=(size, size))
    except Exception:  # noqa: BLE001 - simge kozmetik; yazi tipi/PIL sorunu uygulamayi bozmaz
        return None


def logo_image(size: int = 36) -> ctk.CTkImage | None:
    try:
        from auxy.agent.icon import make_logo

        img = make_logo(128)
        return ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
    except Exception:  # noqa: BLE001
        return None


def status_image(level: str | None, count: int = 0, size: int = 56) -> ctk.CTkImage | None:
    """Pano bandi: sagliga gore kalkan (tray ile ayni cizim)."""
    try:
        from auxy.agent.icon import make_banner_icon

        img = make_banner_icon(level, 128)
        return ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
    except Exception:  # noqa: BLE001
        return None
