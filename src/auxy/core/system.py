"""Sistem yardimcilari: yonetici yetkisi kontrolu ve yukseltme."""

import ctypes
import subprocess
import sys


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def relaunch_as_admin(args: list[str]) -> bool:
    """`python -m auxy <args>` komutunu UAC ile yeni yonetici konsolunda baslatir.

    Kullanici UAC'yi reddederse False doner.
    """
    params = subprocess.list2cmdline(["-m", "auxy", *args])
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
    return rc > 32
