"""Sistem yardimcilari: yonetici yetkisi kontrolu ve yukseltme."""

import ctypes
import subprocess
import sys
from pathlib import Path


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def relaunch_as_admin(args: list[str], windowless: bool = False) -> bool:
    """`python -m auxy <args>` komutunu UAC ile yonetici olarak baslatir.

    windowless=True: konsol penceresi acmadan (pythonw) calistirir (GUI icin).
    Kullanici UAC'yi reddederse False doner.
    """
    exe = sys.executable
    if windowless:
        pyw = Path(exe).with_name("pythonw.exe")
        if pyw.exists():
            exe = str(pyw)
    params = subprocess.list2cmdline(["-m", "auxy", *args])
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    return rc > 32
