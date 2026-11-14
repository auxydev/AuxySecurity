"""Hızlı kurulum paketi: AuxySecurity-Kurulum-<sürüm>.zip

İçerik (zip içinde tek klasör):
  başlat.bat              çift tıkla -> adım adım kurar (UAC ister)
  AuxySecurity-Setup.exe  kurulum programı (scripts/build_installer.ps1 çıktısı)
  SHA256SUMS.txt          başlat.bat kurucuyu çalıştırmadan önce bunu doğrular
  OKU-BENI.txt            kısa açıklama

Kullanım: python scripts/make_package.py [kurucu_yolu] [çıktı_klasörü]
Varsayılan kurucu: %TEMP%\\auxy-build\\AuxySecurity-Setup.exe ; çıktı: aynı klasör.
"""

from __future__ import annotations

import hashlib
import os
import sys
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src"))

from auxy import __version__  # noqa: E402

BAT_NAME = "başlat.bat"
README = """AuxySecurity {v} - Hızlı Kurulum
================================

1. Bu zip'i bir klasöre ÇIKAR (zip'in içinden çalıştırma).
2. "başlat.bat" dosyasına çift tıkla.
3. Windows yönetici izni (UAC) isterse "Evet" de.
4. Sorulara E (evet) / H (hayır) ile cevap ver. Kararsızsan 60 saniye bekle: varsayılan seçilir.

Hiçbir şey sormadan kurmak için komut isteminde:  başlat.bat /auto
Diğer seçenekler: /nogdpi (GoodbyeDPI kurma)  /nowarp (WARP indirme)  /nostart (sonunda açma)

Ne yapar?
  [1] Sistemi denetler (64 bit Windows 10/11)
  [2] Yönetici izni ister
  [3] AuxySecurity-Setup.exe dosyasını SHA-256 ile doğrular (bozuk/değiştirilmişse durur)
  [4] Seçeneklerini sorar (otomatik başlatma, sağ tık menüsü, masaüstü kısayolu, GoodbyeDPI, WARP)
  [5] Kurar (Program Files\\AuxySecurity)
  [6] Kurulumu denetler (sürüm + tanı)
  [7] Uygulamayı açar

Kaldırma: Ayarlar > Uygulamalar > AuxySecurity  (ayarların ve karantina kasan korunur)
SHA-256 (AuxySecurity-Setup.exe): {h}
"""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(setup: Path, out_dir: Path, bat_src: Path | None = None) -> Path:
    bat_src = bat_src or root / "packaging" / "baslat.bat"
    if not setup.exists():
        raise SystemExit(f"Kurulum programı yok: {setup}  (önce scripts\\build.ps1 ve scripts\\build_installer.ps1)")
    digest = sha256(setup)
    folder = f"AuxySecurity-Kurulum-{__version__}"
    out_dir.mkdir(parents=True, exist_ok=True)
    zpath = out_dir / f"{folder}.zip"
    bat = bat_src.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")  # cmd icin CRLF
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr(f"{folder}/{BAT_NAME}", bat)                      # Turkce ad: zip UTF-8 bayragi otomatik
        z.write(setup, f"{folder}/AuxySecurity-Setup.exe")
        z.writestr(f"{folder}/SHA256SUMS.txt", f"{digest}  AuxySecurity-Setup.exe\r\n")
        z.writestr(f"{folder}/OKU-BENI.txt", README.format(v=__version__, h=digest).replace("\n", "\r\n").encode("utf-8"))
    return zpath


if __name__ == "__main__":
    default = Path(os.environ.get("AUXY_BUILD_DIR") or Path(os.environ["TEMP"]) / "auxy-build")
    setup = Path(sys.argv[1]) if len(sys.argv) > 1 else default / "AuxySecurity-Setup.exe"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else default
    z = build(setup, out)
    print(f"Paket: {z} ({z.stat().st_size / 1e6:.1f} MB)")
