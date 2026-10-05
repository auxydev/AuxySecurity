"""Ag araclari: GoodbyeDPI (Windows hizmeti) ve Cloudflare WARP (warp-cli) yonetimi.

- GoodbyeDPI: hizmet durumunu okumak yonetici GEREKTIRMEZ; baslat/durdur/kur/kaldir gerektirir (UAC, `netsvc` alt komutu).
- WARP: `warp-cli` ile baglan/kes, tunel protokolu (MASQUE/WireGuard) ve calisma kipi. Yonetici gerekmez.
- Kurulum programi GoodbyeDPI'i (uygulamayla birlikte paketlenen kopya) hizmet olarak kaydeder; WARP yoksa winget ile
  arka planda kurar. Her sey tekil islevlerdir ve test icin enjekte edilebilir.

Guvenlik: GoodbyeDPI hizmeti LocalSystem olarak calisir; exe'si kullanicinin yazabildigi bir klasorde ise (ornegin
Masaustu) kullanici hesabinda calisan zararli bir program onu degistirip SISTEM yetkisi alabilir. Bu yuzden hizmet yalnizca
yonetici-yazilabilir konumlardaki (Program Files vb.) exe'ye kaydedilir ve baska konumdaki hizmet `trusted()` ile uyarilir.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from auxy.core import system
from auxy.core.service import AuxyError

GDPI_SERVICE = "GoodbyeDPI"
GDPI_DRIVERS = ("WinDivert", "WinDivert14")  # goodbyedpi'nin yukledigi cekirdek surucusu (kaldirirken temizlenir)
GDPI_DEFAULT_ARGS = ("-5 --set-ttl 5 --dns-addr 77.88.8.8 --dns-port 1253 "
                     "--dnsv6-addr 2a02:6b8::feed:0ff --dnsv6-port 1253")  # Turkiye (DNS zorlamasini kaldirir) on ayari
GDPI_DESCRIPTION = "Turkiye icin DNS zorlamasini kaldirir (AuxySecurity tarafindan yonetilir)."
TOOLS_SUBDIR = Path("tools") / "goodbyedpi"
ARG_TOKEN = re.compile(r"^[A-Za-z0-9\-.:=_]+$")  # hizmet argumanlari: kabuk degil ama yine de dar tut

WARP_MODES = {  # warp-cli mode degeri -> gorunen ad
    "warp": "WARP (tüm trafik tünelden)",
    "warp+doh": "WARP + DNS (DoH)",
    "warp+dot": "WARP + DNS (DoT)",
    "doh": "Yalnızca DNS (DoH), tünel yok",
    "dot": "Yalnızca DNS (DoT), tünel yok",
    "proxy": "SOCKS5 proxy",
    "tunnel_only": "Yalnızca tünel (DNS dokunulmaz)",
}
WARP_PROTOCOLS = {"MASQUE": "MASQUE (HTTP/3, varsayılan)", "WireGuard": "WireGuard (eski)"}
WINGET_WARP_ID = "Cloudflare.Warp"

STATE_NAMES = {1: "stopped", 2: "start_pending", 3: "stop_pending", 4: "running", 5: "continue_pending",
               6: "pause_pending", 7: "paused"}
START_TYPES = {2: "auto", 3: "manual", 4: "disabled", 0: "boot", 1: "system"}


@dataclass(frozen=True)
class ServiceInfo:
    installed: bool
    state: str = "missing"        # running | stopped | start_pending | stop_pending | missing | unknown
    start_type: str = ""          # auto | manual | disabled
    binary: str = ""              # exe yolu
    arguments: str = ""           # exe'den sonraki arguman metni


@dataclass(frozen=True)
class WarpInfo:
    installed: bool
    status: str = "missing"       # Connected | Disconnected | Connecting | ...
    reason: str = ""
    mode: str = ""                # WARP_MODES anahtari (taninmazsa ham deger)
    protocol: str = ""            # MASQUE | WireGuard | ham deger
    service_running: bool | None = None
    error: str = ""


@dataclass(frozen=True)
class NetResult:
    ok: bool
    message: str
    changed: bool = False


# ---------------------------------------------------------------- GoodbyeDPI: okuma
def split_command_line(cmd: str) -> tuple[str, str]:
    """'"C:\\yol bosluklu\\x.exe" -5 --a b' -> (exe, 'arguman metni')."""
    cmd = cmd.strip()
    if cmd.startswith('"'):
        end = cmd.find('"', 1)
        if end == -1:
            return cmd[1:], ""
        return cmd[1:end], cmd[end + 1:].strip()
    m = re.match(r"^(.*?\.exe)\b\s*(.*)$", cmd, re.I)
    return (m.group(1), m.group(2).strip()) if m else (cmd, "")


def read_service(name: str = GDPI_SERVICE) -> ServiceInfo:
    """Hizmet durumu/yapilandirmasi. Yonetici gerekmez; hizmet yoksa installed=False."""
    import pywintypes
    import win32service

    try:
        scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
    except pywintypes.error:
        return ServiceInfo(False, "unknown")
    try:
        try:
            h = win32service.OpenService(scm, name, win32service.SERVICE_QUERY_STATUS | win32service.SERVICE_QUERY_CONFIG)
        except pywintypes.error as exc:
            return ServiceInfo(False, "missing") if exc.winerror == 1060 else ServiceInfo(False, "unknown")
        try:
            state = STATE_NAMES.get(win32service.QueryServiceStatus(h)[1], "unknown")
            cfg = win32service.QueryServiceConfig(h)
            exe, args = split_command_line(cfg[3])
            return ServiceInfo(True, state, START_TYPES.get(cfg[1], "?"), exe, args)
        finally:
            win32service.CloseServiceHandle(h)
    finally:
        win32service.CloseServiceHandle(scm)


def trusted_location(path: str, extra_roots: tuple[Path, ...] = ()) -> bool:
    """Exe yonetici-yazilabilir bir konumda mi? (Program Files / Windows / bu kurulum). Masaustu, Indirilenler vb. DEGIL."""
    if not path:
        return False
    roots = [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("SystemRoot"),
             os.environ.get("ProgramW6432")]
    allowed = [Path(r).resolve() for r in roots if r] + [Path(p).resolve() for p in extra_roots]
    inst = system.install_dir()
    if inst is not None:
        allowed.append(Path(inst).resolve())
    try:
        p = Path(path).resolve()
    except OSError:
        return False
    return any(p == a or a in p.parents for a in allowed)


def bundled_tools_dir() -> Path | None:
    """Kurulu uygulamayla gelen GoodbyeDPI klasoru (yalnizca paketlenmis surumde)."""
    inst = system.install_dir()
    if inst is None:
        return None
    d = Path(inst) / TOOLS_SUBDIR
    return d if (d / "x86_64" / "goodbyedpi.exe").exists() or (d / "x86" / "goodbyedpi.exe").exists() else None


def arch_exe(tools_dir: Path) -> Path:
    """Islemci mimarisine uygun goodbyedpi.exe."""
    x64 = os.environ.get("PROCESSOR_ARCHITECTURE", "").upper() == "AMD64" or bool(os.environ.get("PROCESSOR_ARCHITEW6432"))
    exe = tools_dir / ("x86_64" if x64 else "x86") / "goodbyedpi.exe"
    if not exe.exists():
        raise AuxyError(f"goodbyedpi.exe bulunamadı: {exe}")
    return exe


def validate_args(args: str) -> str:
    tokens = args.split()
    for t in tokens:
        if not ARG_TOKEN.match(t):
            raise AuxyError(f"Geçersiz GoodbyeDPI argümanı: {t!r}")
    return " ".join(tokens)


# ---------------------------------------------------------------- GoodbyeDPI: yonetim (yonetici)
def _open_scm(access):
    import win32service

    return win32service.OpenSCManager(None, None, access)


def _wait_state(handle, wanted: str, timeout_s: float) -> bool:
    import win32service

    end = time.time() + timeout_s
    while time.time() < end:
        if STATE_NAMES.get(win32service.QueryServiceStatus(handle)[1]) == wanted:
            return True
        time.sleep(0.25)
    return False


def service_control(op: str, name: str = GDPI_SERVICE, timeout_s: float = 15) -> NetResult:
    """op: start | stop. Yonetici gerekir."""
    import pywintypes
    import win32service

    if op not in ("start", "stop"):
        raise AuxyError(f"Geçersiz işlem: {op!r}")
    try:
        scm = _open_scm(win32service.SC_MANAGER_CONNECT)
        h = win32service.OpenService(scm, name, win32service.SERVICE_START | win32service.SERVICE_STOP
                                     | win32service.SERVICE_QUERY_STATUS)
    except pywintypes.error as exc:
        if exc.winerror == 1060:
            return NetResult(False, "GoodbyeDPI hizmeti kurulu değil.")
        if exc.winerror == 5:
            return NetResult(False, "Yönetici yetkisi gerekir.")
        return NetResult(False, f"Hizmete erişilemedi: {exc.strerror}")
    try:
        state = STATE_NAMES.get(win32service.QueryServiceStatus(h)[1])
        if op == "start":
            if state == "running":
                return NetResult(True, "Zaten çalışıyor.")
            try:
                win32service.StartService(h, None)
            except pywintypes.error as exc:
                return NetResult(False, f"Başlatılamadı: {exc.strerror}")
            return NetResult(True, "Başlatıldı.", True) if _wait_state(h, "running", timeout_s) \
                else NetResult(False, "Hizmet zamanında başlamadı.")
        if state == "stopped":
            return NetResult(True, "Zaten durdurulmuş.")
        try:
            win32service.ControlService(h, win32service.SERVICE_CONTROL_STOP)
        except pywintypes.error as exc:
            return NetResult(False, f"Durdurulamadı: {exc.strerror}")
        return NetResult(True, "Durduruldu.", True) if _wait_state(h, "stopped", timeout_s) \
            else NetResult(False, "Hizmet zamanında durmadı.")
    finally:
        win32service.CloseServiceHandle(h)
        win32service.CloseServiceHandle(scm)


def set_start_type(kind: str, name: str = GDPI_SERVICE) -> NetResult:
    """kind: auto | manual. Yonetici gerekir."""
    import pywintypes
    import win32service

    code = {"auto": win32service.SERVICE_AUTO_START, "manual": win32service.SERVICE_DEMAND_START}.get(kind)
    if code is None:
        raise AuxyError(f"Geçersiz başlangıç türü: {kind!r}")
    try:
        scm = _open_scm(win32service.SC_MANAGER_CONNECT)
        h = win32service.OpenService(scm, name, win32service.SERVICE_CHANGE_CONFIG | win32service.SERVICE_QUERY_CONFIG)
    except pywintypes.error as exc:
        return NetResult(False, "GoodbyeDPI hizmeti kurulu değil." if exc.winerror == 1060 else f"Erişilemedi: {exc.strerror}")
    try:
        if win32service.QueryServiceConfig(h)[1] == code:
            return NetResult(True, "Zaten bu ayarda.")
        win32service.ChangeServiceConfig(h, win32service.SERVICE_NO_CHANGE, code, win32service.SERVICE_NO_CHANGE,
                                         None, None, 0, None, None, None, None)
        return NetResult(True, "Windows ile otomatik başlatılacak." if kind == "auto" else "Elle başlatılacak.", True)
    except pywintypes.error as exc:
        return NetResult(False, f"Değiştirilemedi: {exc.strerror}")
    finally:
        win32service.CloseServiceHandle(h)
        win32service.CloseServiceHandle(scm)


def install_service(tools_dir: Path, name: str = GDPI_SERVICE, args: str | None = None,
                    trusted_roots: tuple[Path, ...] = ()) -> NetResult:
    """GoodbyeDPI hizmetini `tools_dir` icindeki exe'ye kaydeder (yonetici gerekir).

    - Hizmet VARSA: binPath yeni (guvenli) konuma tasinir; mevcut ARGUMANLAR, baslangic turu ve calisma durumu korunur.
    - Yoksa: Turkiye on ayariyla ELLE baslatilacak (demand) olarak olusturulur; calistirilmaz.
    """
    import pywintypes
    import win32service

    exe = arch_exe(Path(tools_dir))
    if not trusted_location(str(exe), extra_roots=trusted_roots):
        raise AuxyError(f"Güvenlik: {exe} yönetici-yazılabilir bir konumda değil; SİSTEM hizmeti olarak kaydedilmez.")
    existing = read_service(name)
    final_args = validate_args(args if args is not None else (existing.arguments if existing.installed else GDPI_DEFAULT_ARGS))
    bin_path = f'"{exe}" {final_args}'.strip()
    scm = _open_scm(win32service.SC_MANAGER_ALL_ACCESS)
    try:
        if existing.installed:
            if existing.binary.lower() == str(exe).lower() and existing.arguments == final_args:
                return NetResult(True, "GoodbyeDPI hizmeti zaten bu konumda.")
            was_running = existing.state == "running"
            if was_running:
                service_control("stop", name)
            h = win32service.OpenService(scm, name, win32service.SERVICE_CHANGE_CONFIG)
            try:
                win32service.ChangeServiceConfig(h, win32service.SERVICE_NO_CHANGE, win32service.SERVICE_NO_CHANGE,
                                                 win32service.SERVICE_NO_CHANGE, bin_path, None, 0, None, None, None, None)
            finally:
                win32service.CloseServiceHandle(h)
            if was_running:
                service_control("start", name)
            return NetResult(True, f"Hizmet güvenli konuma taşındı: {exe}", True)
        h = win32service.CreateService(scm, name, name, win32service.SERVICE_ALL_ACCESS,
                                       win32service.SERVICE_WIN32_OWN_PROCESS, win32service.SERVICE_DEMAND_START,
                                       win32service.SERVICE_ERROR_NORMAL, bin_path, None, 0, None, None, None)
        try:
            win32service.ChangeServiceConfig2(h, win32service.SERVICE_CONFIG_DESCRIPTION, GDPI_DESCRIPTION)
        finally:
            win32service.CloseServiceHandle(h)
        return NetResult(True, "GoodbyeDPI hizmeti kuruldu (elle başlatılır).", True)
    except pywintypes.error as exc:
        raise AuxyError(f"Hizmet kaydedilemedi: {exc.strerror}") from exc
    finally:
        win32service.CloseServiceHandle(scm)


def remove_service(name: str = GDPI_SERVICE, only_under: Path | None = None) -> NetResult:
    """Hizmeti (ve WinDivert surucusunu) kaldirir. `only_under`: hizmet exe'si bu klasorde DEGILSE dokunma."""
    import pywintypes
    import win32service

    info = read_service(name)
    if not info.installed:
        return NetResult(True, "Hizmet zaten yok.")
    if only_under is not None and Path(only_under).resolve() not in Path(info.binary).resolve().parents:
        return NetResult(True, "Hizmet başka bir konumu gösteriyor: dokunulmadı.")
    if info.state == "running":
        service_control("stop", name)
    scm = _open_scm(win32service.SC_MANAGER_ALL_ACCESS)
    try:
        for svc in (name, *GDPI_DRIVERS):
            try:
                h = win32service.OpenService(scm, svc, win32service.SERVICE_ALL_ACCESS)
            except pywintypes.error:
                continue
            try:
                if svc != name:
                    try:
                        win32service.ControlService(h, win32service.SERVICE_CONTROL_STOP)
                    except pywintypes.error:
                        pass
                win32service.DeleteService(h)
            finally:
                win32service.CloseServiceHandle(h)
    finally:
        win32service.CloseServiceHandle(scm)
    return NetResult(True, "GoodbyeDPI hizmeti kaldırıldı.", True)


# ---------------------------------------------------------------- WARP
def warp_cli_path() -> Path | None:
    for env in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        base = os.environ.get(env)
        if base:
            p = Path(base) / "Cloudflare" / "Cloudflare WARP" / "warp-cli.exe"
            if p.exists():
                return p
    return None


def _run_warp(args: list[str], timeout: float = 15, cli: Path | None = None) -> subprocess.CompletedProcess:
    exe = cli or warp_cli_path()
    if exe is None:
        raise AuxyError("Cloudflare WARP kurulu değil.")
    return subprocess.run([str(exe), "--accept-tos", *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW)


def normalize_mode(raw: str) -> str:
    """JSON'daki operation_mode ('doh', 'warp_doh', ...) -> warp-cli mode degeri ('doh', 'warp+doh', ...)."""
    low = (raw or "").lower()
    if low in WARP_MODES:
        return low
    alt = low.replace("_", "+")
    return alt if alt in WARP_MODES else raw


def normalize_protocol(raw: str) -> str:
    low = (raw or "").lower()
    return {"masque": "MASQUE", "wireguard": "WireGuard"}.get(low, raw)


def read_warp() -> WarpInfo:
    cli = warp_cli_path()
    if cli is None:
        return WarpInfo(False)
    try:
        st = json.loads(_run_warp(["-j", "status"], cli=cli).stdout or "{}")
        raw = json.loads(_run_warp(["-j", "settings"], cli=cli).stdout or "{}").get("settings", {})
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, AuxyError) as exc:
        return WarpInfo(True, "unknown", error=str(exc))
    svc = read_service("CloudflareWARP")
    return WarpInfo(True, str(st.get("status", "unknown")), str(st.get("reason", "")),
                    normalize_mode(str(raw.get("operation_mode", ""))),
                    normalize_protocol(str(raw.get("warp_tunnel_protocol", ""))),
                    svc.state == "running" if svc.installed else None)


def warp_op(op: str, value: str = "", cli: Path | None = None) -> NetResult:
    """op: connect | disconnect | protocol | mode. Yonetici gerekmez."""
    if op == "connect":
        args = ["connect"]
    elif op == "disconnect":
        args = ["disconnect"]
    elif op == "protocol":
        if value not in WARP_PROTOCOLS:
            raise AuxyError(f"Geçersiz protokol: {value!r}")
        args = ["tunnel", "protocol", "set", value]
    elif op == "mode":
        if value not in WARP_MODES:
            raise AuxyError(f"Geçersiz kip: {value!r}")
        args = ["mode", value]
    else:
        raise AuxyError(f"Geçersiz işlem: {op!r}")
    try:
        proc = _run_warp(args, timeout=30, cli=cli)
    except subprocess.TimeoutExpired:
        return NetResult(False, "WARP yanıt vermedi (zaman aşımı).")
    if proc.returncode != 0:
        return NetResult(False, f"WARP hata verdi: {_short(proc.stderr or proc.stdout) or proc.returncode}")
    done = {"connect": "WARP bağlantı isteği gönderildi.", "disconnect": "WARP bağlantısı kesildi.",
            "protocol": f"Protokol {value} olarak ayarlandı.", "mode": f"Kip {WARP_MODES.get(value, value)} olarak ayarlandı."}
    return NetResult(True, done[op], True)  # warp-cli'nin uzun/ingilizce ciktisi gosterilmez


def _short(text: str, limit: int = 140) -> str:
    """Birden cok satirli arac ciktisindan tek, kisa, anlamli satir (ilk bos olmayan)."""
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line if len(line) <= limit else line[: limit - 1] + "…"
    return ""

def install_warp(timeout_s: float = 900) -> NetResult:
    """WARP kurulu degilse resmi paketi winget ile sessizce kurar (internet gerekir; MSI UAC isteyebilir)."""
    if warp_cli_path() is not None:
        return NetResult(True, "WARP zaten kurulu.")
    try:
        proc = subprocess.run(
            ["winget", "install", "--id", WINGET_WARP_ID, "-e", "--source", "winget", "--silent",
             "--accept-package-agreements", "--accept-source-agreements"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout_s,
            creationflags=subprocess.CREATE_NO_WINDOW)
    except FileNotFoundError:
        return NetResult(False, "winget bulunamadı; WARP'ı https://one.one.one.one adresinden kur.")
    except subprocess.TimeoutExpired:
        return NetResult(False, "WARP kurulumu zaman aşımına uğradı.")
    if proc.returncode == 0 and warp_cli_path() is not None:
        return NetResult(True, "WARP kuruldu.", True)
    tail = (proc.stdout or proc.stderr or "").strip().splitlines()[-1:] or [""]
    return NetResult(False, f"WARP kurulamadı (winget çıkış {proc.returncode}): {tail[0]}")
