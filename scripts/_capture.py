"""Pencere goruntusu: ekrani KOPYALAMAZ, yalnizca pencerenin kendi icerigini alir (PrintWindow).

Neden: ImageGrab ekranin o bolgesini oldugu gibi kopyalar; baska bir pencere (tarayici vb.) uygulamanin
ustunu kapatiyorsa KISISEL ICERIK yakalanir. PrintWindow, pencere ortulu olsa bile yalnizca o pencereyi cizer.
Kaydetmeden once kenar cubugu (duz renk) kontrolu yapilir; supheliyse dosya yazilmaz.
"""

from __future__ import annotations

import ctypes
from pathlib import Path

import win32con
import win32gui
import win32ui
from PIL import Image

PW_CLIENTONLY, PW_RENDERFULLCONTENT = 1, 2


def top_hwnd(tk_window) -> int:
    hwnd = tk_window.winfo_id()
    parent = ctypes.windll.user32.GetParent(hwnd)
    return parent or hwnd


def grab_window(tk_window) -> Image.Image:
    hwnd = top_hwnd(tk_window)
    l, t, r, b = win32gui.GetClientRect(hwnd)
    w, h = r - l, b - t
    hdc = win32gui.GetWindowDC(hwnd)
    src = win32ui.CreateDCFromHandle(hdc)
    mem = src.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(src, w, h)
    mem.SelectObject(bmp)
    try:
        ctypes.windll.user32.PrintWindow(hwnd, mem.GetSafeHdc(), PW_CLIENTONLY | PW_RENDERFULLCONTENT)
        info = bmp.GetInfo()
        bits = bmp.GetBitmapBits(True)
        return Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]), bits, "raw", "BGRX", 0, 1)
    finally:
        win32gui.DeleteObject(bmp.GetHandle())
        mem.DeleteDC()
        src.DeleteDC()
        win32gui.ReleaseDC(hwnd, hdc)


def looks_like_app(img: Image.Image) -> bool:
    """Sol kenar cubugunun alt kismi duz renk mi? (baska pencere/ekran icerigi degil, uygulama)"""
    w, h = img.size
    side = img.crop((0, int(h * 0.68), min(150, w), int(h * 0.86)))  # navigasyonun altindaki bos duz alan
    colors = side.getcolors(maxcolors=100000)
    return bool(colors) and max(colors)[0] / (side.size[0] * side.size[1]) > 0.9


def save_window(tk_window, path: Path) -> bool:
    """Pencereyi kaydeder. Kenar cubugu kontrolu basarisizsa KAYDETMEZ ve False doner."""
    img = grab_window(tk_window)
    if not looks_like_app(img):
        print(f"UYARI: {path.name} uygulama penceresi gibi gorunmuyor; KAYDEDILMEDI")
        return False
    img.save(path, optimize=True)
    return True
