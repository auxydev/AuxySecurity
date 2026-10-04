"""Sistem yardimcilari: yonetici kontrolu, UAC ile yukseltme, tek ornek kilidi."""

from __future__ import annotations

import ctypes
import os
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


def instance_suffix() -> str:
    """Test icin: AUXY_INSTANCE ortam degiskeni, mutex/olay adlarini ayirir (calisan ajana dokunmadan test)."""
    return os.environ.get("AUXY_INSTANCE", "")


def agent_mutex_name() -> str:
    return "AuxySecurityAgent" + instance_suffix()


CONFIG_EVENT_BASE = "Local\\AuxyConfigChanged"


def _config_event():
    k = ctypes.windll.kernel32
    k.CreateEventW.restype = wintypes.HANDLE
    k.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    return k.CreateEventW(None, False, False, CONFIG_EVENT_BASE + instance_suffix())  # otomatik sifirlanan, adli olay


def signal_config_changed() -> None:
    """GUI ayari kaydedince ajani aninda uyandirir (yoklama yok)."""
    k = ctypes.windll.kernel32
    h = _config_event()
    if h:
        k.SetEvent.argtypes = [wintypes.HANDLE]
        k.SetEvent(h)
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.CloseHandle(h)


class ConfigWaiter:
    """Ajan tarafi: olay gelene kadar uyur. wake() ile (cikista) bekleme sonlandirilir."""

    def __init__(self):
        self._h = _config_event()
        k = ctypes.windll.kernel32
        k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k.WaitForSingleObject.restype = wintypes.DWORD
        k.SetEvent.argtypes = [wintypes.HANDLE]

    def wait(self) -> None:
        ctypes.windll.kernel32.WaitForSingleObject(self._h, 0xFFFFFFFF)

    def wake(self) -> None:
        ctypes.windll.kernel32.SetEvent(self._h)


def is_agent_running() -> bool:
    k = ctypes.windll.kernel32
    k.OpenMutexW.restype = wintypes.HANDLE
    k.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    h = k.OpenMutexW(0x00100000, False, "Local\\" + agent_mutex_name())  # SYNCHRONIZE
    if h:
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.CloseHandle(h)
        return True
    return False


class ScanLock:
    """Surecler arasi (GUI / tray / ajan) tek tarama kilidi: adli mutex.

    Mutex sahipligi is parcacigina baglidir; acquire() ve release() AYNI is parcaciginda cagrilmalidir
    (ScanManager.run bunu zaten tek is parcaciginda yapar). Sahibi olen surecin mutex'i "terk edilmis"
    sayilir ve devralinir; boylece cokmus bir surec kalici kilit birakmaz.
    """

    NAME = "Local\\AuxyScanLock"

    def __init__(self):
        self._h = None

    def acquire(self) -> bool:
        k = ctypes.windll.kernel32
        k.CreateMutexW.restype = wintypes.HANDLE
        k.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k.WaitForSingleObject.restype = wintypes.DWORD
        h = k.CreateMutexW(None, False, self.NAME + instance_suffix())
        if not h:
            return True  # kilit olusturulamadi: engelleme
        rc = k.WaitForSingleObject(h, 0)
        if rc in (0, 0x80):  # WAIT_OBJECT_0, WAIT_ABANDONED
            self._h = h
            return True
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.CloseHandle(h)
        return False

    def release(self) -> None:
        if self._h:
            k = ctypes.windll.kernel32
            k.ReleaseMutex.argtypes = [wintypes.HANDLE]
            k.CloseHandle.argtypes = [wintypes.HANDLE]
            k.ReleaseMutex(self._h)
            k.CloseHandle(self._h)
            self._h = None


def focus_window(title: str) -> bool:
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        return False
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    return True
