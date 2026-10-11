"""Tor: resmi 'Tor Expert Bundle'i indirip dogrulama, yerel SOCKS5 vekili olarak calistirma, kopruler, yeni kimlik.

ONEMLI (durustluk): bu bir VPN DEGIL. Tor, yerel bir SOCKS5 vekili (127.0.0.1:9050) acar; trafigini yalnizca vekili
kullanan uygulamalar (tarayici, curl, nmap -sT --proxies vb.) Tor uzerinden gonderir. 'Windows vekili' secenegi sistem
vekilini bu adrese ayarlar: yalnizca vekil ayarina uyan uygulamalar etkilenir. Tum sistem trafigini zorlayan gercek
bir 'Tor VPN' icin ayri bir TUN surucusu gerekir (kapsam disi). Anonimlik icin Tor Browser en iyisidir.

Guvenlik:
- Paket yalnizca https://dist.torproject.org'dan indirilir; SHA-256 ayni siteden gelen 'sha256sums-signed-build.txt' ile
  dogrulanir. UYARI: bu butunluk denetimidir; sha256sums dosyasinin GPG imzasi (.asc) burada dogrulanmaz.
- Tor yonetici OLARAK calistirilmaz (kullanici yazilabilir klasorden gelen exe yukseltilmis calismamali).
- Kontrol portu yalnizca 127.0.0.1'de, cerez kimlik dogrulamasiyla.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import socket
import ssl
import subprocess
import tarfile
import tempfile
import time
import urllib.request
import winreg
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from auxy.core import paths, system
from auxy.core.service import AuxyError

DEFAULT_VERSION = "15.0.24"
DIST = "https://dist.torproject.org/torbrowser/"
MAX_DOWNLOAD = 150 * 1024 * 1024
SOCKS_PORT, CONTROL_PORT = 9050, 9051
INET_KEY = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
TRANSPORTS = {"obfs4": "lyrebird.exe", "snowflake": "snowflake-client.exe", "meek": "lyrebird.exe"}
BRIDGE_RE = re.compile(r"[A-Za-z0-9 .:=,/_\[\]+%@-]{6,600}")


@dataclass(frozen=True)
class TorStatus:
    installed: bool
    running: bool = False
    bootstrap: int = 0           # 0-100
    summary: str = ""
    version: str = ""


# ---------------------------------------------------------------- yollar / surum
def home() -> Path:
    return paths.home() / "tor"


def bundle_dir() -> Path:
    return home() / "bundle"


def tor_exe() -> Path | None:
    d = bundle_dir()
    return next(iter(sorted(d.rglob("tor.exe"))), None) if d.exists() else None


def installed_version() -> str:
    try:
        return (home() / "version.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def bundle_url(version: str) -> str:
    return f"{DIST}{version}/tor-expert-bundle-windows-x86_64-{version}.tar.gz"


def sums_url(version: str) -> str:
    return f"{DIST}{version}/sha256sums-signed-build.txt"


def _fetch(url: str, timeout: float = 30) -> bytes:
    if not url.startswith(DIST):
        raise AuxyError("Yalnızca dist.torproject.org'dan indirilir.")
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - https, sabit onekli
        return resp.read(MAX_DOWNLOAD + 1)


def latest_version(fetch: Callable = _fetch) -> str:
    """Kararli (alfa/beta olmayan) en yeni surum; ag yoksa ya da cozulemezse varsayilan."""
    try:
        html = fetch(DIST).decode("utf-8", "replace")
        versions = {tuple(int(x) for x in m.split(".")): m for m in re.findall(r'href="(\d+\.\d+(?:\.\d+)?)/"', html)}
        return versions[max(versions)] if versions else DEFAULT_VERSION
    except Exception:  # noqa: BLE001
        return DEFAULT_VERSION


def parse_sums(text: str, filename: str) -> str:
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == filename and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            return parts[0].lower()
    raise AuxyError(f"Doğrulama dosyasında {filename} için SHA-256 bulunamadı.")


def safe_extract(archive: Path, dest: Path) -> int:
    """tar.gz'yi guvenle cikarir (yol gecisi/baglanti/aygit reddedilir). Dosya sayisini dondurur."""
    dest = Path(dest).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    count = 0
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        for m in members:
            target = (dest / m.name).resolve()
            if dest != target and dest not in target.parents:
                raise AuxyError(f"Arşivde geçersiz yol: {m.name}")
            if m.issym() or m.islnk() or m.isdev():
                raise AuxyError(f"Arşivde izin verilmeyen girdi: {m.name}")
            count += int(m.isfile())
        tar.extractall(dest, members=members, filter="data")  # noqa: S202 - uyeler yukarida denetlendi
    return count


def install(version: str | None = None, progress: Callable[[str], None] = lambda m: None,
            fetch: Callable = _fetch) -> str:
    """Tor'u indirir, SHA-256 dogrular, cikarir. Internet gerekir. Mesaj dondurur."""
    if system.is_admin():
        raise AuxyError("Tor yönetici olarak kurulmaz: uygulamayı normal kullanıcı olarak aç.")
    version = version or latest_version(fetch)
    name = f"tor-expert-bundle-windows-x86_64-{version}.tar.gz"
    progress(f"Doğrulama dosyası alınıyor (Tor {version})…")
    expected = parse_sums(fetch(sums_url(version)).decode("utf-8", "replace"), name)
    progress("Paket indiriliyor (~21 MB)…")
    data = fetch(bundle_url(version), 600)
    if len(data) > MAX_DOWNLOAD:
        raise AuxyError("İndirilen dosya beklenenden büyük; iptal edildi.")
    if hashlib.sha256(data).hexdigest() != expected:
        raise AuxyError("SHA-256 uyuşmuyor: indirilen dosya bozuk ya da değiştirilmiş. Kurulmadı.")
    progress("Doğrulandı, çıkarılıyor…")
    home().mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False, dir=home()) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)
    try:
        stage = home() / "bundle.new"
        shutil.rmtree(stage, ignore_errors=True)
        safe_extract(tmp_path, stage)
        if not any(stage.rglob("tor.exe")):
            shutil.rmtree(stage, ignore_errors=True)
            raise AuxyError("Pakette tor.exe bulunamadı.")
        shutil.rmtree(bundle_dir(), ignore_errors=True)
        stage.rename(bundle_dir())
    finally:
        tmp_path.unlink(missing_ok=True)
    (home() / "version.txt").write_text(version, encoding="utf-8")
    return f"Tor {version} kuruldu (SHA-256 doğrulandı)."


# ---------------------------------------------------------------- yapilandirma
def bridge_lines(kind: str) -> list[str]:
    """Paketle gelen varsayilan kopru satirlari (pt_config.json). Bulunamazsa bos liste."""
    cfg = next(iter(bundle_dir().rglob("pt_config.json")), None) if bundle_dir().exists() else None
    if cfg is None:
        return []
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
        return [str(x) for x in data.get("bridges", {}).get(kind, [])]
    except (OSError, json.JSONDecodeError, AttributeError):
        return []


def clean_bridge(line: str) -> str:
    line = line.strip()
    if line.lower().startswith("bridge "):
        line = line[7:].strip()
    if not BRIDGE_RE.fullmatch(line):
        raise AuxyError("Geçersiz köprü satırı.")
    return line


def build_torrc(socks_port: int = SOCKS_PORT, control_port: int = CONTROL_PORT, bridges: list[str] | None = None,
                data_dir: Path | None = None, pt_dir: Path | None = None) -> str:
    data_dir = data_dir or home() / "data"
    lines = [f"SocksPort 127.0.0.1:{socks_port}", f"ControlPort 127.0.0.1:{control_port}", "CookieAuthentication 1",
             f"DataDirectory {data_dir}", "ClientOnly 1", "AvoidDiskWrites 1", "Log notice stdout"]
    if bridges:
        cleaned = [clean_bridge(b) for b in bridges]
        lines.append("UseBridges 1")
        root = pt_dir or bundle_dir()
        for t in sorted({c.split()[0] for c in cleaned}):
            exe = TRANSPORTS.get(t)
            found = next(iter(root.rglob(exe)), None) if exe and root.exists() else None
            if found:
                lines.append(f"ClientTransportPlugin {t} exec {found}")
        lines += [f"Bridge {c}" for c in cleaned]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- kontrol portu
def _control(commands: list[str], port: int = CONTROL_PORT, timeout: float = 4.0) -> list[str]:
    """Cerez ile kimlik dogrular, komutlari gonderir, yanit satirlarini dondurur."""
    cookie = home() / "data" / "control_auth_cookie"
    if not cookie.exists():
        raise AuxyError("Tor kontrol çerezi yok (Tor çalışmıyor).")
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as s:
        f = s.makefile("rw", newline="\r\n", encoding="utf-8")
        f.write(f"AUTHENTICATE {cookie.read_bytes().hex()}\r\n")
        f.flush()
        first = f.readline()
        if not first.startswith("250"):
            raise AuxyError(f"Tor kimlik doğrulaması reddedildi: {first.strip()}")
        out = []
        for c in commands:
            f.write(c + "\r\n")
            f.flush()
            while True:
                line = f.readline()
                if not line:
                    break
                out.append(line.strip())
                if len(line) > 3 and line[:3].isdigit() and line[3] == " ":
                    break
        return out


def parse_bootstrap(lines: list[str]) -> tuple[int, str]:
    for line in lines:
        m = re.search(r'PROGRESS=(\d+).*?SUMMARY="([^"]*)"', line)
        if m:
            return int(m.group(1)), m.group(2)
    return 0, ""


def status() -> TorStatus:
    if tor_exe() is None:
        return TorStatus(False)
    try:
        pct, summary = parse_bootstrap(_control(["GETINFO status/bootstrap-phase"]))
        return TorStatus(True, True, pct, summary, installed_version())
    except (OSError, AuxyError, ValueError):
        return TorStatus(True, False, 0, "", installed_version())


def start(bridges: list[str] | None = None) -> str:
    """Tor'u arka planda baslatir (yonetici DEGIL). Baglanma ilerlemesi `status()` ile izlenir."""
    if system.is_admin():
        raise AuxyError("Tor yönetici olarak çalıştırılmaz: uygulamayı normal kullanıcı olarak aç.")
    exe = tor_exe()
    if exe is None:
        raise AuxyError("Tor kurulu değil. Önce 'Tor'u kur'a bas.")
    if status().running:
        return "Tor zaten çalışıyor."
    (home() / "data").mkdir(parents=True, exist_ok=True)
    rc = home() / "torrc"
    rc.write_text(build_torrc(bridges=bridges, pt_dir=bundle_dir()), encoding="utf-8")
    log = open(home() / "tor.log", "ab")  # noqa: SIM115 - alt surec boyunca acik kalir
    proc = subprocess.Popen([str(exe), "-f", str(rc)], cwd=str(exe.parent), stdout=log, stderr=log,
                            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
    (home() / "tor.pid").write_text(str(proc.pid), encoding="utf-8")
    return "Tor başlatıldı; ağa bağlanıyor…"


def stop() -> str:
    """Temiz kapatma (SIGNAL SHUTDOWN); olmazsa kaydedilen PID'yi sonlandirir. Sistem vekilini de geri alir."""
    try:
        _control(["SIGNAL SHUTDOWN"])
    except (OSError, AuxyError):
        try:
            pid = int((home() / "tor.pid").read_text(encoding="utf-8"))
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        except (OSError, ValueError):
            pass
    (home() / "tor.pid").unlink(missing_ok=True)
    try:
        set_system_proxy(False)
    except AuxyError:
        pass
    return "Tor durduruldu."


def new_identity() -> str:
    _control(["SIGNAL NEWNYM"])
    return "Yeni Tor devresi istendi (yeni kimlik)."


# ---------------------------------------------------------------- Windows vekili
def _proxy_backup() -> Path:
    return home() / "proxy_backup.json"


def get_system_proxy() -> tuple[bool, str]:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, INET_KEY) as k:
            enabled = bool(winreg.QueryValueEx(k, "ProxyEnable")[0])
            try:
                server = str(winreg.QueryValueEx(k, "ProxyServer")[0])
            except FileNotFoundError:
                server = ""
            return enabled, server
    except OSError:
        return False, ""


def _notify_proxy_change() -> None:
    import ctypes

    wininet = ctypes.windll.wininet
    wininet.InternetSetOptionW(None, 39, None, 0)  # SETTINGS_CHANGED
    wininet.InternetSetOptionW(None, 37, None, 0)  # REFRESH


def set_system_proxy(enabled: bool, port: int = SOCKS_PORT) -> str:
    """Windows (WinINET) vekilini Tor SOCKS5'e ayarlar / eski haline dondurur. Yonetici gerekmez."""
    home().mkdir(parents=True, exist_ok=True)
    try:
        if enabled:
            if not _proxy_backup().exists():  # yalnizca ILK acista eski ayari yedekle
                cur_en, cur_srv = get_system_proxy()
                _proxy_backup().write_text(json.dumps({"enable": cur_en, "server": cur_srv}), encoding="utf-8")
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, INET_KEY, 0, winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, "ProxyServer", 0, winreg.REG_SZ, f"socks=127.0.0.1:{port}")
                winreg.SetValueEx(k, "ProxyEnable", 0, winreg.REG_DWORD, 1)
            msg = "Windows vekili Tor'a ayarlandı (yalnızca vekil ayarına uyan uygulamalar etkilenir)."
        else:
            if not _proxy_backup().exists():
                return "Windows vekili zaten değiştirilmemiş."
            old = json.loads(_proxy_backup().read_text(encoding="utf-8"))
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, INET_KEY, 0, winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, "ProxyServer", 0, winreg.REG_SZ, old.get("server", ""))
                winreg.SetValueEx(k, "ProxyEnable", 0, winreg.REG_DWORD, 1 if old.get("enable") else 0)
            _proxy_backup().unlink(missing_ok=True)
            msg = "Windows vekili eski haline döndü."
    except (OSError, json.JSONDecodeError) as exc:
        raise AuxyError(f"Windows vekili değiştirilemedi: {exc}") from exc
    try:
        _notify_proxy_change()
    except OSError:
        pass
    return msg


def system_proxy_is_tor(port: int = SOCKS_PORT) -> bool:
    enabled, server = get_system_proxy()
    return enabled and server == f"socks=127.0.0.1:{port}"


# ---------------------------------------------------------------- dogrulama (Tor uzerinden)
def socks5_connect(host: str, port: int, proxy: tuple[str, int] = ("127.0.0.1", SOCKS_PORT),
                   timeout: float = 20) -> socket.socket:
    """Alan adini VEKILE cozdurerek (DNS sizintisi yok) SOCKS5 CONNECT."""
    s = socket.create_connection(proxy, timeout=timeout)
    try:
        s.sendall(b"\x05\x01\x00")
        if s.recv(2) != b"\x05\x00":
            raise AuxyError("SOCKS5 el sıkışması reddedildi.")
        h = host.encode("idna")
        s.sendall(b"\x05\x01\x00\x03" + bytes([len(h)]) + h + port.to_bytes(2, "big"))
        reply = s.recv(10)
        if len(reply) < 2 or reply[1] != 0:
            raise AuxyError(f"Tor bağlantıyı reddetti (kod {reply[1] if len(reply) > 1 else '?'}).")
        return s
    except Exception:
        s.close()
        raise


def check_tor(port: int = SOCKS_PORT) -> dict:
    """check.torproject.org'a Tor uzerinden sorar: {'IsTor': bool, 'IP': str}. Kullanici isteyince."""
    raw = socks5_connect("check.torproject.org", 443, ("127.0.0.1", port))
    with ssl.create_default_context().wrap_socket(raw, server_hostname="check.torproject.org") as s:
        s.sendall(b"GET /api/ip HTTP/1.0\r\nHost: check.torproject.org\r\nConnection: close\r\n\r\n")  # 1.0: parcali yok
        data = b""
        while chunk := s.recv(4096):
            data += chunk
    try:
        return json.loads(data.split(b"\r\n\r\n", 1)[-1].decode("utf-8", "replace"))
    except json.JSONDecodeError as exc:
        raise AuxyError("Tor denetim yanıtı çözülemedi.") from exc


def wait_bootstrap(timeout: float = 90, poll: float = 1.5) -> TorStatus:
    end = time.time() + timeout
    st = status()
    while time.time() < end and st.running and st.bootstrap < 100:
        time.sleep(poll)
        st = status()
    return st
