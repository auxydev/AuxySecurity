"""`auxy doctor`: ortam ve kurulum tanisi. Her kontrol bagimsiz; biri hata verirse doctor COKMEZ, o kontrol ✘ olur.

Hicbir sey DEGISTIRMEZ (kasa anahtari olusturmaz, gorev kurmaz, ayar yazmaz); yalnizca okur.
"""

from __future__ import annotations

import importlib
import importlib.metadata as md
import re
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

OK, WARN, FAIL, INFO = "ok", "warn", "fail", "info"
SYMBOLS = {OK: "✔", WARN: "⚠", FAIL: "✘", INFO: "•"}
REQUIRED = {  # import adi -> dagitim adi
    "win32com": "pywin32", "customtkinter": "customtkinter", "pystray": "pystray", "PIL": "pillow",
    "cryptography": "cryptography", "watchdog": "watchdog", "tkinterdnd2": "tkinterdnd2",
}
LOG_ERROR = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ (?P<lvl>ERROR|CRITICAL) (?P<msg>.*)$")


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str
    hint: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _check(name: str, fn: Callable[[], Check | list[Check]]) -> list[Check]:
    try:
        out = fn()
        return out if isinstance(out, list) else [out]
    except Exception as exc:  # doctor kendisi cokmemeli
        return [Check(name, FAIL, f"kontrol calistirilamadi: {type(exc).__name__}: {exc}")]


# ---------------- tek tek kontroller ----------------
def check_python() -> Check:
    if getattr(sys, "frozen", False):
        from auxy import __version__

        return Check("Sürüm", OK, f"AuxySecurity {__version__} (paketlenmiş, {Path(sys.executable).parent})")
    v = sys.version_info
    exe = sys.executable
    store = "WindowsApps" in exe
    if v < (3, 12):
        return Check("Python", FAIL, f"{v.major}.{v.minor}.{v.micro} ({exe})", "Python 3.12 veya üstü gerekir.")
    if store:
        return Check("Python", WARN, f"{v.major}.{v.minor}.{v.micro} Microsoft Store sürümü ({exe})",
                     "Store Python %LOCALAPPDATA% yazımlarını sanallaştırır: kasa/yedek/günlük Python paketinin özel "
                     "alanında durur ve paket kaldırılırsa silinir. Anahtar yedeğini al; v1.0 paketi bunu çözecek.")
    return Check("Python", OK, f"{v.major}.{v.minor}.{v.micro} ({exe})")


def check_dependencies() -> list[Check]:
    out = []
    for module, dist in REQUIRED.items():
        try:
            mod = importlib.import_module(module)
            try:
                version = md.version(dist)
            except md.PackageNotFoundError:  # paketlenmis surumde dist-info yok; iceri aktarma yeterli
                version = str(getattr(mod, "__version__", "gömülü"))
            out.append(Check(f"Bağımlılık: {dist}", OK, version))
        except Exception as exc:
            out.append(Check(f"Bağımlılık: {dist}", FAIL, f"içe aktarılamadı: {exc}", f"pip install {dist}"))
    return out


def check_admin() -> Check:
    from auxy.core import system

    admin = system.is_admin()
    return Check("Yönetici yetkisi", INFO, "evet" if admin else "hayır (ayar değişikliklerinde UAC istenir)")


def check_defender() -> list[Check]:
    from auxy.core import defender

    t0 = time.perf_counter()
    st = defender.read_status()
    ms = (time.perf_counter() - t0) * 1000
    s = st.status
    out = [Check("Defender WMI erişimi", OK, f"{ms:.0f} ms")]
    out.append(Check("Defender servisi", OK if s.get("AMServiceEnabled") and s.get("AntivirusEnabled") else FAIL,
                     f"servis={s.get('AMServiceEnabled')}, antivirüs={s.get('AntivirusEnabled')}",
                     "" if s.get("AntivirusEnabled") else "Defender kapalı: başka bir antivirüs birincil olabilir."))
    out.append(Check("Gerçek zamanlı koruma", OK if st.realtime_on else FAIL,
                     "açık" if st.realtime_on else "KAPALI", "" if st.realtime_on else "Windows Güvenlik'ten aç."))
    last = s.get("AntivirusSignatureLastUpdated")
    if isinstance(last, datetime):
        age = (datetime.now(timezone.utc).replace(tzinfo=None) - last).days
        out.append(Check("Virüs imzaları", OK if age < 3 else WARN, f"{s.get('AntivirusSignatureVersion')} ({age} gün önce)",
                         "" if age < 3 else "auxy update-signatures"))
    out.append(Check("Tamper Protection", INFO, "açık" if st.tamper_protected else "kapalı"))
    return out


def check_mpcmdrun() -> Check:
    from auxy.core import scan

    return Check("MpCmdRun.exe", OK, str(scan.mpcmdrun_path()))


def check_data_dir() -> list[Check]:
    from auxy.core import paths

    home = paths.home()
    out = []
    probe = home / ".doctor-yazma-testi"
    probe.write_text("x", encoding="utf-8")
    probe.unlink()
    size = sum(p.stat().st_size for p in home.rglob("*") if p.is_file())
    out.append(Check("Veri dizini", OK, f"{home} ({size / 1024:.0f} KB, yazılabilir)"))
    return out


def check_config() -> Check:
    from auxy.core import config as cfgmod

    f = cfgmod.config_file()
    if not f.exists():
        return Check("Yapılandırma", INFO, "config.json yok (varsayılanlar kullanılıyor)")
    import json

    try:
        json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return Check("Yapılandırma", WARN, f"config.json bozuk, varsayılanlar kullanılıyor: {exc}",
                     "Ayarlar sayfasında bir ayarı kaydedince dosya yenilenir.")
    c = cfgmod.load()
    on = [n for n, v in (("indirilenler izleme", c.watch_enabled), ("USB tarama", c.usb_scan),
                         ("haftalık tarama", c.scheduled.enabled), ("tehdit bildirimi", c.event_notifications)) if v]
    return Check("Yapılandırma", OK, "açık yardımcılar: " + (", ".join(on) or "yok"))


def check_backup() -> Check:
    from auxy.core import paths

    f = paths.backup_file()
    if not f.exists():
        return Check("Ayar yedeği", INFO, "değiştirilmiş ayar yok")
    import json

    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return Check("Ayar yedeği", WARN, "backup.json bozuk (bir sonraki işlemde kenara alınır)")
    return Check("Ayar yedeği", INFO, f"{len(data)} kayıt (orijinale dönmek için auxy revert / winsec-revert)")


def check_vault() -> list[Check]:
    from auxy.core import paths, vault

    root = paths.home() / "vault"
    key_file = root / "vault.key"
    if not root.exists() or not (root / "vault.db").exists():
        return [Check("Karantina kasası", INFO, "henüz oluşturulmadı")]
    if not key_file.exists():
        return [Check("Karantina kasası", FAIL, "vault.key yok: kasadaki dosyalar açılamaz",
                      "auxy vault import-key <yedek.auxkey>")]
    import win32crypt

    try:
        key = win32crypt.CryptUnprotectData(key_file.read_bytes(), None, None, None, 0)[1]
    except Exception as exc:
        return [Check("Karantina kasası", FAIL, f"anahtar çözülemedi: {exc}", "auxy vault import-key <yedek.auxkey>")]
    v = vault.Vault(root, key)  # anahtar zaten var: yeni anahtar uretilmez
    items = v.list()
    verdict = v.verify_key(key)
    status = OK if verdict is not False else FAIL
    return [Check("Karantina kasası", status, f"{len(items)} kayıt; anahtar "
                  + ("dosyaları açıyor" if verdict else "kayıt yok, doğrulanamadı" if verdict is None else "dosyaları AÇMIYOR"),
                  "" if status == OK else "auxy vault import-key <yedek.auxkey>"),
            Check("Kasa anahtar yedeği", INFO, "Anahtarı yedeklediysen sorun yok; yedek yoksa: auxy vault export-key <dosya>")]


def check_agent() -> Check:
    from auxy.core import system

    running = system.is_agent_running()
    return Check("Tray ajanı", OK if running else INFO, "çalışıyor" if running else "çalışmıyor (auxy agent)")


def check_autostart() -> list[Check]:
    from auxy.core import autostart

    if not autostart.is_installed():
        return [Check("Başlangıç görevi", INFO, "kurulu değil (Ayarlar → Başlangıç)")]
    import subprocess

    xml = subprocess.run(["schtasks", "/Query", "/TN", autostart.TASK_NAME, "/XML"], capture_output=True,
                         text=True, errors="replace", creationflags=subprocess.CREATE_NO_WINDOW).stdout
    cmd = re.search(r"<Command>(.*?)</Command>", xml)
    wd = re.search(r"<WorkingDirectory>(.*?)</WorkingDirectory>", xml)
    out = [Check("Başlangıç görevi", OK, "kurulu")]
    if cmd and not Path(cmd.group(1)).exists():
        out.append(Check("Görev programı", FAIL, f"bulunamadı: {cmd.group(1)}",
                         "Proje/Python taşındıysa: auxy autostart remove, sonra install"))
    if wd and not Path(wd.group(1)).exists():
        out.append(Check("Görev çalışma dizini", WARN, f"bulunamadı: {wd.group(1)}", "Görevi yeniden kur."))
    if "<Repetition>" not in xml:
        out.append(Check("Görev çökme kurtarma", WARN, "tekrarlanan tetikleyici yok (ajan ölürse yeniden başlamaz)",
                         "Görevi yeniden kur: auxy autostart remove, sonra install"))
    return out


def check_context_menu() -> Check:
    from auxy.core import contextmenu

    return Check("Sağ tık menüsü", INFO, "kurulu" if contextmenu.is_installed() else "kurulu değil")


def check_install_location() -> Check:
    from auxy.core import autostart, hardening

    r = hardening.install_location_risk()
    if not r.risky:
        return Check("Kurulum konumu", OK, r.detail)
    elevated_auto = autostart.is_installed()
    return Check("Kurulum konumu", WARN, r.detail + (" Başlangıç görevi KURULU: yüksek yetkiyle çalışıyor." if elevated_auto else ""),
                 "Yalnızca kendi kullandığın, başkasının erişmediği bir bilgisayarda kabul edilebilir; v1.0 kurulumu Program Files'a yapılacak.")


def check_log(window_hours: int = 24) -> list[Check]:
    from auxy.core import paths

    f = paths.log_dir() / "auxy.log"
    if not f.exists():
        return [Check("Günlük", INFO, "henüz kayıt yok")]
    cutoff = datetime.now() - timedelta(hours=window_hours)
    errors = []
    for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
        m = LOG_ERROR.match(line)
        if m and datetime.strptime(m.group("ts"), "%Y-%m-%d %H:%M:%S") >= cutoff:
            errors.append(m.group("msg"))
    size = f.stat().st_size / 1024
    if not errors:
        return [Check("Günlük", OK, f"{size:.0f} KB; son {window_hours} saatte hata yok")]
    return [Check("Günlük", WARN, f"son {window_hours} saatte {len(errors)} hata; sonuncusu: {errors[-1][:120]}",
                  "Ayrıntı için Günlük sayfası / auxy.log")]


def check_scan_lock() -> Check:
    from auxy.core import system

    lock = system.ScanLock()
    if lock.acquire():
        lock.release()
        return Check("Tarama kilidi", OK, "boşta (şu an tarama yok)")
    return Check("Tarama kilidi", INFO, "bir tarama sürüyor")


def check_legacy_data() -> Check:
    from auxy.core import migrate

    plan = migrate.pending_plan()
    if plan is None:
        return Check("Eski veri", INFO, "taşınacak eski (sanallaştırılmış) veri yok")
    items = ", ".join(plan.to_copy)
    return Check("Eski veri", WARN, f"Store Python veri dizininde taşınmamış veri var: {plan.source} ({items})",
                 "auxy migrate-data --yes (eski veri silinmez, kopyalanır)")


def check_network_tools() -> Check:
    from auxy.core import netservices as ns

    g = ns.read_service()
    if not g.installed:
        return Check("GoodbyeDPI", INFO, "hizmet kurulu değil")
    detail = f"{g.state}, başlangıç: {g.start_type}, {g.binary}"
    if not ns.trusted_location(g.binary):
        return Check("GoodbyeDPI", WARN, detail + " — SİSTEM hizmeti, kullanıcının yazabildiği bir klasördeki exe'yi "
                     "çalıştırıyor (yetki yükseltme riski)",
                     "Ağ güvenliği sayfası → 'Güvenli konuma taşı' (kurulu sürümde) ya da exe'yi Program Files'a taşı")
    return Check("GoodbyeDPI", OK, detail)


CHECKS: tuple[tuple[str, Callable], ...] = (
    ("python", check_python), ("deps", check_dependencies), ("admin", check_admin), ("defender", check_defender),
    ("mpcmdrun", check_mpcmdrun), ("data", check_data_dir), ("config", check_config), ("backup", check_backup),
    ("vault", check_vault), ("agent", check_agent), ("autostart", check_autostart), ("ctx", check_context_menu),
    ("location", check_install_location), ("legacy", check_legacy_data), ("nettools", check_network_tools), ("log", check_log), ("lock", check_scan_lock),
)


def run_checks() -> list[Check]:
    results: list[Check] = []
    for name, fn in CHECKS:
        results += _check(name, fn)
    return results


def summarize(results: list[Check]) -> tuple[int, int, int]:
    return (sum(r.status == OK for r in results), sum(r.status == WARN for r in results),
            sum(r.status == FAIL for r in results))


def format_report(results: list[Check]) -> str:
    lines = []
    for r in results:
        lines.append(f" {SYMBOLS[r.status]} {r.name:<26} {r.detail}")
        if r.hint and r.status in (WARN, FAIL):
            lines.append(f"     → {r.hint}")
    ok, warn, fail = summarize(results)
    lines.append("")
    lines.append(f"Özet: {ok} tamam, {warn} uyarı, {fail} hata")
    return "\n".join(lines)
