"""Tray simgesi: kalkan logosu + hata rozeti (PIL ile cizilir).

- Sorun yok: yesil kalkan + onay isareti.
- Kritik sorun var: kalkanin ustunde KIRMIZI rozet, icinde kritik sorun sayisi (ornegin 1).
- Yalnizca kritik olmayan sorun var: TURUNCU rozet, icinde sorun sayisi.
- Durum okunamadi: gri kalkan.
Cizim 4x buyuk yapilip kucultulur (kenar yumusatma); tray 16/32 px'e ayrica olceklendirir.
"""

from __future__ import annotations

from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from auxy.gui import viewmodel as vm

SIZE = 64
_BIG = 256  # cizim tuvali (SIZE'a kucultulur)

GREEN = (38, 166, 91)
RED = (222, 53, 53)
ORANGE = (240, 140, 20)
GRAY = (128, 134, 144)
STEEL = (58, 74, 102)  # sorun varken kalkan: rozet rengi kalkanda kaybolmasin
LEVEL_COLORS = {vm.OK: GREEN, vm.WARN: ORANGE, vm.CRIT: RED}  # geriye uyum (belge/ico)
UNKNOWN_COLOR = GRAY
_FONTS = ("segoeuib.ttf", "arialbd.ttf", "seguisb.ttf", "verdanab.ttf")


def _shield_points(top: float, bottom: float, left: float, right: float) -> list[tuple[float, float]]:
    """Kalkan: ust ortada tepe, yanlar duz, alta dogru kavisle sivrilen govde."""
    cx = (left + right) / 2
    pts: list[tuple[float, float]] = [(cx, top), (right, top + 0.16 * (bottom - top))]
    mid_y = top + 0.52 * (bottom - top)
    pts.append((right, mid_y))

    def bezier(p0, p1, p2, steps=24):
        return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
                 (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1])
                for t in (i / steps for i in range(1, steps + 1))]

    pts += bezier((right, mid_y), (right, top + 0.86 * (bottom - top)), (cx, bottom))
    pts += bezier((cx, bottom), (left, top + 0.86 * (bottom - top)), (left, mid_y))
    pts.append((left, top + 0.16 * (bottom - top)))
    return pts


def _font(px: int) -> ImageFont.ImageFont:
    for name in _FONTS:
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default()


def _lighten(c: tuple[int, int, int], f: float) -> tuple[int, int, int]:
    return tuple(int(v + (255 - v) * f) for v in c)  # type: ignore[return-value]


def _draw_badge(d: ImageDraw.ImageDraw, color: tuple[int, int, int], count: int) -> None:
    r = 78  # buyuk rozet: 16 px'te bile okunsun
    cx, cy = _BIG - r - 11, r + 11  # beyaz halka tuval disina tasmasin
    d.ellipse((cx - r - 9, cy - r - 9, cx + r + 9, cy + r + 9), fill=(255, 255, 255, 255))  # beyaz halka
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color + (255,))
    text = str(count) if count < 10 else "9+"
    font = _font(118 if len(text) == 1 else 92)
    d.text((cx, cy + 4), text, font=font, fill=(255, 255, 255, 255), anchor="mm")


BLUE = (37, 99, 235)


@lru_cache(maxsize=4)
def make_logo(size: int = 256) -> Image.Image:
    """Uygulama logosu (exe/gorev cubugu/pencere): durumdan bagimsiz mavi kalkan + beyaz 'A' harfi. Onay isareti YOK."""
    img = Image.new("RGBA", (_BIG, _BIG), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    box = (30, 10, 226, 246)
    d.polygon(_shield_points(box[1], box[3], box[0], box[2]), fill=_lighten(BLUE, 0.0) + (255,))
    d.polygon(_shield_points(box[1] + 14, box[3] - 18, box[0] + 16, box[2] - 16), fill=_lighten(BLUE, 0.22) + (255,))
    w = (255, 255, 255, 255)
    # 'A': iki egik cubuk + yatay kiris
    d.line([(128, 62), (84, 190)], fill=w, width=26, joint="curve")
    d.line([(128, 62), (172, 190)], fill=w, width=26, joint="curve")
    d.line([(100, 150), (156, 150)], fill=w, width=22)
    return img.resize((size, size), Image.LANCZOS)


@lru_cache(maxsize=8)
def make_banner_icon(level: str | None, size: int = 128) -> Image.Image:
    """Pano bandi (renkli zemin) icin BEYAZ kalkan + durum renginde isaret: tik / unlem / carpi."""
    img = Image.new("RGBA", (_BIG, _BIG), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.polygon(_shield_points(10, 246, 30, 226), fill=(255, 255, 255, 255))
    color = LEVEL_COLORS.get(level, GRAY) + (255,)
    if level == vm.OK:
        d.line([(76, 130), (112, 166), (180, 88)], fill=color, width=26, joint="curve")
    elif level == vm.WARN:
        d.line([(128, 72), (128, 150)], fill=color, width=26)
        d.ellipse((113, 168, 143, 198), fill=color)
    elif level == vm.CRIT:
        d.line([(88, 86), (168, 166)], fill=color, width=26)
        d.line([(168, 86), (88, 166)], fill=color, width=26)
    else:
        d.ellipse((112, 112, 144, 144), fill=color)
    return img.resize((size, size), Image.LANCZOS)


@lru_cache(maxsize=32)
def make_icon(level: str | None, count: int = 0) -> Image.Image:
    """Simge (seviye, sayi) basina BIR KEZ cizilir (her yenilemede yeniden cizim/bellek hareketi olmasin).

    `count`: seviyedeki sorun sayisi (kritik varsa kritik sayisi, yoksa kritik olmayan sayisi). 0 -> rozet yok.
    """
    img = Image.new("RGBA", (_BIG, _BIG), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    has_issue = level in (vm.WARN, vm.CRIT) and count > 0
    base = GRAY if level not in LEVEL_COLORS else (STEEL if has_issue else GREEN)

    box = (22, 12, 216, 244) if has_issue else (30, 10, 226, 246)
    outer = _shield_points(box[1], box[3], box[0], box[2])
    d.polygon(outer, fill=_lighten(base, 0.0) + (255,))
    # ic yuzey: ustte hafif aydinlik, sag yarida hafif golge (kalkana hacim)
    inset = _shield_points(box[1] + 14, box[3] - 18, box[0] + 16, box[2] - 16)
    d.polygon(inset, fill=_lighten(base, 0.18) + (255,))
    mask = Image.new("L", (_BIG, _BIG), 0)
    ImageDraw.Draw(mask).polygon(inset, fill=255)
    shade = Image.new("RGBA", (_BIG, _BIG), (0, 0, 0, 0))
    ImageDraw.Draw(shade).polygon(
        [(_BIG / 2 + 4, 0), (_BIG, 0), (_BIG, _BIG), (_BIG / 2 + 4, _BIG)], fill=(0, 0, 0, 42))
    img.paste(shade, (0, 0), Image.composite(shade.getchannel("A"), Image.new("L", (_BIG, _BIG), 0), mask))

    w = (255, 255, 255, 255)
    cx = (box[0] + box[2]) / 2
    if level == vm.OK or (level in LEVEL_COLORS and not has_issue):  # onay isareti
        d.line([(cx - 52, 128), (cx - 14, 166), (cx + 56, 84)], fill=w, width=26, joint="curve")
    elif level is None or level not in LEVEL_COLORS:  # bilinmiyor: soru benzeri nokta
        d.ellipse((cx - 16, 112, cx + 16, 144), fill=w)

    if has_issue:
        _draw_badge(d, RED if level == vm.CRIT else ORANGE, count)
    return img.resize((SIZE, SIZE), Image.LANCZOS)
