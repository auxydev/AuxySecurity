"""Paketlenmis AuxySecurity.exe penceresini acar, yalnizca O pencerenin goruntusunu (PrintWindow) alir, kapatir.

Kullanim: python scripts/frozen_gui_check.py <AuxySecurity.exe> <cikti.png> [bekleme_sn]
Baska pencereler goruntuye GIRMEZ; kenar cubugu kontrolu gecmezse dosya kaydedilmez.
"""

import ctypes
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psutil
import win32gui
import win32ui
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from _capture import looks_like_app  # noqa: E402

exe, out = sys.argv[1], Path(sys.argv[2])
wait = float(sys.argv[3]) if len(sys.argv) > 3 else 6
env = {**os.environ, "AUXY_HOME": tempfile.mkdtemp(prefix="auxy-frozen-gui-"), "AUXY_INSTANCE": "_frozengui"}
t0 = time.perf_counter()
proc = subprocess.Popen([exe], env=env)  # argumansiz penceresiz exe -> GUI acilmali

hwnd, deadline = 0, time.time() + 30
while time.time() < deadline and not hwnd:
    hwnd = win32gui.FindWindow(None, "AuxySecurity")
    time.sleep(0.1)
opened = time.perf_counter() - t0
print(f"pencere bulundu: {bool(hwnd)}  acilis suresi: {opened:.2f} sn")
time.sleep(wait)  # ilk veri okumasi

if hwnd:
    l, t, r, b = win32gui.GetClientRect(hwnd)
    w, h = r - l, b - t
    hdc = win32gui.GetWindowDC(hwnd)
    src = win32ui.CreateDCFromHandle(hdc)
    mem = src.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(src, w, h)
    mem.SelectObject(bmp)
    ctypes.windll.user32.PrintWindow(hwnd, mem.GetSafeHdc(), 3)
    info = bmp.GetInfo()
    img = Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]), bmp.GetBitmapBits(True), "raw", "BGRX", 0, 1)
    ok = looks_like_app(img)
    if ok:
        img.save(out, optimize=True)
    print(f"goruntu: {img.size}, uygulama penceresi gibi mi: {ok}, kaydedildi: {ok}")
    try:
        p = psutil.Process(proc.pid)
        print(f"surec: calisma kumesi {p.memory_info().rss / 1e6:.0f} MB, ozel {p.memory_full_info().private / 1e6:.0f} MB, "
              f"alt surec sayisi {len(p.children(recursive=True))}")
    except psutil.NoSuchProcess:
        print("surec bulunamadi")
    win32gui.PostMessage(hwnd, 0x0010, 0, 0)  # WM_CLOSE
    time.sleep(2)

try:
    proc.wait(timeout=5)
    print("kapandi, cikis kodu:", proc.returncode)
except subprocess.TimeoutExpired:
    proc.kill()
    print("zorla kapatildi")
