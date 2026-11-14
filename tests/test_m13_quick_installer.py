"""Hızlı kurulum (başlat.bat): GERÇEK cmd.exe ile, sahte kurucu (.cmd) kullanılarak çalıştırılır.

Test kipi (AUXY_BAT_TEST=1): UAC yükseltmesi, soru/bekleme, sürüm/tanı ve uygulamayı açma atlanır;
kurucu yolu (AUXY_SETUP) ve kurulum klasörü (AUXY_INSTALLDIR) geçici dizine yönlendirilir. Sisteme dokunulmaz.
"""

import hashlib
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BAT = ROOT / "packaging" / "baslat.bat"

STUB = (
    "@echo off\r\n"
    "echo %*> \"%~dp0setup-args.txt\"\r\n"
    "if not \"%STUB_RC%\"==\"\" exit /b %STUB_RC%\r\n"
    "if \"%STUB_NOFILE%\"==\"1\" exit /b 0\r\n"
    "if not exist \"%AUXY_INSTALLDIR%\" mkdir \"%AUXY_INSTALLDIR%\"\r\n"
    "echo x> \"%AUXY_INSTALLDIR%\\AuxySecurity.exe\"\r\n"
    "exit /b 0\r\n"
)


@pytest.fixture
def kit(tmp_path):
    d = tmp_path / "AuxySecurity Kurulum"  # bosluklu yol
    d.mkdir()
    shutil.copy(BAT, d / "başlat.bat")
    (d / "setup.cmd").write_bytes(STUB.encode("ascii"))
    return d


def run(kit: Path, *args, sums: str | None = "match", stub_rc: str = "", nofile: bool = False):
    if sums == "match":
        digest = hashlib.sha256((kit / "setup.cmd").read_bytes()).hexdigest()
        (kit / "SHA256SUMS.txt").write_text(f"{digest}  AuxySecurity-Setup.exe\r\n", encoding="ascii")
    elif sums == "bad":
        (kit / "SHA256SUMS.txt").write_text(f"{'0' * 64}  AuxySecurity-Setup.exe\r\n", encoding="ascii")
    env = {**os.environ, "AUXY_BAT_TEST": "1", "AUXY_SETUP": str(kit / "setup.cmd"),
           "AUXY_INSTALLDIR": str(kit / "Program Files" / "AuxySecurity"), "STUB_RC": stub_rc,
           "STUB_NOFILE": "1" if nofile else ""}
    proc = subprocess.run(["cmd", "/c", str(kit / "başlat.bat"), *args], capture_output=True, env=env, timeout=120,
                          stdin=subprocess.DEVNULL)
    out = proc.stdout.decode("utf-8", "replace")
    args_file = kit / "setup-args.txt"
    setup_args = args_file.read_text(encoding="ascii", errors="replace").split() if args_file.exists() else None
    return proc.returncode, out, setup_args


pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="cmd.exe gerekir")


def test_bat_file_is_crlf_and_utf8_without_bom():
    data = BAT.read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf")                       # BOM olursa ilk satir bozulur
    assert b"\r\n" in data and b"\n" not in data.replace(b"\r\n", b"")  # cmd icin saf CRLF
    data.decode("utf-8")


def test_full_run_succeeds_with_default_choices_and_verified_hash(kit):
    rc, out, args = run(kit, "/nostart")
    assert rc == 0, out
    for n in range(1, 8):
        assert f"[{n}/7]" in out                                     # 7 adimin hepsi yazildi
    assert "SHA-256 doğrulandı" in out and "Kurulum tamamlandı" in out
    assert args == ["/S", "/AUTOSTART", "/CONTEXTMENU"]              # varsayilanlar: masaustu Hayir, GDPI/WARP Evet
    assert "^" not in out                                            # kacis karakteri ekrana sizmasin


def test_flags_disable_gdpi_and_warp(kit):
    rc, out, args = run(kit, "/nogdpi", "/nowarp", "/nostart")
    assert rc == 0, out
    assert args == ["/S", "/AUTOSTART", "/CONTEXTMENU", "/NOGDPI", "/NOWARP"]


def test_tampered_installer_is_refused_and_never_run(kit):
    rc, out, args = run(kit, "/nostart", sums="bad")
    assert rc == 1 and "SHA-256 uyuşmuyor" in out and "Kurulum tamamlanamadı" in out
    assert args is None                                              # kurucu HIC calistirilmadi


def test_missing_checksum_file_warns_but_continues(kit):
    rc, out, args = run(kit, "/nostart", sums=None)
    assert rc == 0 and "bütünlük denetimi atlandı" in out and args is not None


def test_missing_installer_fails_clearly(kit):
    (kit / "setup.cmd").unlink()
    rc, out, _ = run(kit, "/nostart", sums=None)
    assert rc == 1 and "AuxySecurity-Setup.exe bulunamadı" in out


def test_installer_error_code_is_reported(kit):
    rc, out, args = run(kit, "/nostart", stub_rc="3")
    assert rc == 1 and "çıkış kodu 3" in out and args is not None


def test_install_verification_catches_missing_app(kit):
    # kurucu "basarili" dondu ama uygulama dosyasi yok -> 6. adim yakalamali
    rc, out, args = run(kit, "/nostart", nofile=True)
    assert rc == 1 and "AuxySecurity.exe bulunamadı" in out and args is not None
    assert "Kurulum tamamlandı" not in out


def test_package_builder_creates_zip_with_turkish_name_and_matching_hash(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    import make_package

    fake = tmp_path / "AuxySecurity-Setup.exe"
    fake.write_bytes(b"MZ" + os.urandom(64))
    z = make_package.build(fake, tmp_path / "out")
    with zipfile.ZipFile(z) as zf:
        names = zf.namelist()
        folder = names[0].split("/")[0]
        assert {f"{folder}/başlat.bat", f"{folder}/AuxySecurity-Setup.exe", f"{folder}/SHA256SUMS.txt",
                f"{folder}/OKU-BENI.txt"} == set(names)
        assert zf.getinfo(f"{folder}/başlat.bat").flag_bits & 0x800     # UTF-8 dosya adi bayragi
        sums = zf.read(f"{folder}/SHA256SUMS.txt").decode()
        assert sums.split()[0] == hashlib.sha256(fake.read_bytes()).hexdigest()
        bat = zf.read(f"{folder}/başlat.bat")
        assert b"\r\n" in bat and not bat.startswith(b"\xef\xbb\xbf")
        assert "başlat.bat" in zf.read(f"{folder}/OKU-BENI.txt").decode("utf-8")
