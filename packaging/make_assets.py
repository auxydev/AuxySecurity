"""Paketleme varliklari: .ico (tray simgesinden) ve Windows surum bilgisi dosyasi (version_info.txt).

Kullanim: python packaging/make_assets.py
"""

import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src"))

from auxy import __version__  # noqa: E402
from auxy.agent.icon import make_logo  # noqa: E402

out = Path(__file__).parent
# ---- ico: uygulama logosu (durumdan bagimsiz mavi kalkan), cok boyutlu
base = make_logo(256)
base.save(out / "auxy.ico", format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])

# ---- surum bilgisi
major, minor, patch = (int(x) for x in __version__.split("."))
text = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({major}, {minor}, {patch}, 0), prodvers=({major}, {minor}, {patch}, 0),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('041f04b0', [
      StringStruct('CompanyName', 'AuxySecurity'),
      StringStruct('FileDescription', 'AuxySecurity - Windows Güvenlik (Defender) kontrol paneli'),
      StringStruct('FileVersion', '{__version__}'),
      StringStruct('InternalName', 'AuxySecurity'),
      StringStruct('LegalCopyright', 'Tüm hakları saklıdır'),
      StringStruct('OriginalFilename', 'AuxySecurity.exe'),
      StringStruct('ProductName', 'AuxySecurity'),
      StringStruct('ProductVersion', '{__version__}')])]),
    VarFileInfo([VarStruct('Translation', [1055, 1200])])
  ]
)
"""
(out / "version_info.txt").write_text(text, encoding="utf-8")
print("yazildi:", out / "auxy.ico", out / "version_info.txt")
