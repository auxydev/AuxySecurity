""""Auxy ile tara" Explorer sag-tik menusu. Yalnizca HKCU (yonetici gerekmez), tamamen geri alinabilir.

Windows 11'de klasik girdiler "Daha fazla secenek goster" altinda gorunur.
"""

from __future__ import annotations

import subprocess
import winreg

from auxy.core import system

KEY_NAME = "AuxyScan"
TARGETS = (r"Software\Classes\*\shell", r"Software\Classes\Directory\shell")
LABEL = "Auxy ile tara"


def command_line(exe: str | None = None) -> str:
    if exe:  # kurulum programi: KURULAN exe (donmus mod: dogrudan arguman)
        return subprocess.list2cmdline([exe, "scan-file"]) + ' "%1"'
    return subprocess.list2cmdline([system.app_exe(windowless=True), *system.app_args(["scan-file"])]) + ' "%1"'


def _paths(target: str) -> tuple[str, str]:
    return f"{target}\\{KEY_NAME}", f"{target}\\{KEY_NAME}\\command"


def is_installed() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _paths(TARGETS[0])[1]):
            return True
    except FileNotFoundError:
        return False


def registered_command() -> str:
    """Kayitli komut satiri (yoksa bos)."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _paths(TARGETS[0])[1]) as k:
            return str(winreg.QueryValueEx(k, None)[0])
    except FileNotFoundError:
        return ""


def install(exe: str | None = None) -> None:
    cmd = command_line(exe)
    for target in TARGETS:
        base, command = _paths(target)
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, base, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, None, 0, winreg.REG_SZ, LABEL)
            winreg.SetValueEx(k, "Icon", 0, winreg.REG_SZ, exe or system.app_exe(windowless=True))
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, command, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, None, 0, winreg.REG_SZ, cmd)


def remove() -> None:
    for target in TARGETS:
        base, command = _paths(target)
        for key in (command, base):  # once alt anahtar
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
            except FileNotFoundError:
                pass
