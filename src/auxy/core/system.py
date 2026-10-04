"""Sistem yardimcilari: yonetici kontrolu, UAC ile yukseltme, tek ornek kilidi."""

from __future__ import annotations

import ctypes
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path

ERROR_CANCELLED = 1223  # UAC reddedildi
SEE_MASK_NOCLOSEPROCESS = 0x00000040
SW_HIDE, SW_SHOWNORMAL = 0, 1
WAIT_TIMEOUT = 0x102


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def python_exe(windowless: bool = False) -> str:
    exe = sys.executable
    if windowless:
        pyw = Path(exe).with_name("pythonw.exe")
        if pyw.exists():
            return str(pyw)
    return exe


def relaunch_as_admin(args: list[str], windowless: bool = False) -> bool:
    """`python -m auxy <args>` komutunu UAC ile yonetici olarak baslatir (beklemez).

    windowless=True: konsol penceresi acmadan (pythonw) calistirir (GUI icin).
    Kullanici UAC'yi reddederse False doner.
    """
    params = subprocess.list2cmdline(["-m", "auxy", *args])
    rc = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", python_exe(windowless), params, None, SW_SHOWNORMAL
    )
    return rc > 32


class _ShellExecuteInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", ctypes.c_ulong),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIconOrMonitor", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


def run_elevated_and_wait(args: list[str], timeout_s: float = 120) -> int | None:
    """`pythonw -m auxy <args>` komutunu gizli pencerede UAC ile calistirir ve bitmesini bekler.

    Donus: surecin cikis kodu; UAC reddedildiyse ya da sure asildiysa None.
    """
    kernel32 = ctypes.windll.kernel32
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    info = _ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = python_exe(windowless=True)
    info.lpParameters = subprocess.list2cmdline(["-m", "auxy", *args])
    info.nShow = SW_HIDE
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        return None  # ERROR_CANCELLED dahil
    handle = info.hProcess
    if not handle:
        return None
    try:
        if kernel32.WaitForSingleObject(handle, int(timeout_s * 1000)) == WAIT_TIMEOUT:
            return None
        code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        return int(code.value)
    finally:
        kernel32.CloseHandle(handle)


_held_mutexes: list = []


def acquire_single_instance(name: str) -> bool:
    """Ayni adli ikinci bir ornek calisiyorsa False doner."""
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    handle = kernel32.CreateMutexW(None, False, f"Local\\{name}")
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        return False
    _held_mutexes.append(handle)  # surec bitene kadar tut
    return True


def focus_window(title: str) -> bool:
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        return False
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    return True
