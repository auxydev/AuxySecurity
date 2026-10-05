# -*- mode: python ; coding: utf-8 -*-
# PyInstaller tanimi: AuxySecurity.exe (pencereli: GUI, tray ajani, yukseltilmis yardimci) +
# auxy.exe (konsol: komut satiri). Ikisi AYNI klasoru (onedir) paylasir.
#
# Derleme:  .\scripts\build.ps1
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

hidden = (
    collect_submodules("auxy")
    + ["win32com", "win32com.client", "win32com.shell", "win32timezone", "pythoncom", "pywintypes", "win32crypt",
       "win32evtlog", "win32api", "win32con", "win32gui", "win32ui", "pystray._win32", "tkinterdnd2",
       "customtkinter", "PIL", "cryptography", "watchdog", "watchdog.observers.read_directory_changes"]
)
datas = collect_data_files("customtkinter") + collect_data_files("tkinterdnd2")

excludes = ["pytest", "pytest_mock", "psutil", "coverage", "ruff", "pip", "setuptools", "wheel", "unittest.mock",
            "numpy", "matplotlib", "scipy", "pandas", "IPython"]

a = Analysis(
    ["entry.py"], pathex=["../src"], binaries=[], datas=datas, hiddenimports=hidden, hookspath=[],
    runtime_hooks=[], excludes=excludes, win_no_prefer_redirects=False, win_private_assemblies=False,
    cipher=block_cipher, noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

common = dict(icon="auxy.ico", version="version_info.txt", strip=False, upx=False)

gui_exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="AuxySecurity", console=False, **common)
cli_exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="auxy", console=True, **common)

coll = COLLECT(gui_exe, cli_exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False, name="AuxySecurity")
