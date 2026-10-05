"""Tray simgesi: saglik seviyesine gore renkli daire + sembol (PIL ile cizilir)."""

from __future__ import annotations

from functools import lru_cache

from PIL import Image, ImageDraw

from auxy.gui import viewmodel as vm

LEVEL_COLORS = {vm.OK: (46, 158, 91), vm.WARN: (217, 147, 43), vm.CRIT: (214, 69, 69)}
UNKNOWN_COLOR = (128, 128, 128)
SIZE = 64


@lru_cache(maxsize=8)
def make_icon(level: str | None) -> Image.Image:
    """Simge seviye basina BIR KEZ cizilir (her yenilemede yeniden cizim/bellek hareketi olmasin)."""
    color = LEVEL_COLORS.get(level, UNKNOWN_COLOR)
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((2, 2, SIZE - 2, SIZE - 2), fill=color + (255,))
    w = (255, 255, 255, 255)
    if level == vm.OK:  # onay isareti
        d.line([(18, 34), (28, 44), (47, 22)], fill=w, width=7, joint="curve")
    elif level == vm.WARN:  # unlem
        d.line([(32, 16), (32, 36)], fill=w, width=8)
        d.ellipse((28, 42, 36, 50), fill=w)
    elif level == vm.CRIT:  # carpi
        d.line([(20, 20), (44, 44)], fill=w, width=7)
        d.line([(44, 20), (20, 44)], fill=w, width=7)
    else:  # bilinmiyor
        d.ellipse((26, 26, 38, 38), fill=w)
    return img
