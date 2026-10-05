"""Kurulum / kaldirma mantigi (kurulum programi ve `AuxySecurity.exe uninstall` kullanir).

Hedef yol, kisayol dizinleri ve kayit defteri anahtari PARAMETRELIDIR: testler gercek Program Files / Baslat Menusu /
HKLM'ye dokunmadan her adimi dener.

T1 riskini kapatan sey: uygulama `%ProgramFiles%` altina (yalnizca yonetici yazar) kurulur ve baslangic gorevi
oradaki exe'yi calistirir.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import winreg
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from auxy import __version__
from auxy.core import system

APP_NAME = "AuxySecurity"
PUBLISHER = "AuxySecurity"
ABOUT_URL = "https://github.com/auxydev/AuxySecurity"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\AuxySecurity"


def default_install_dir() -> Path:
    return Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / APP_NAME


def start_menu_dir() -> Path:
    base = os.environ.get("ProgramData", r"C:\ProgramData")
    return Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / APP_NAME


def desktop_dir() -> Path:
    return Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop"


@dataclass
class InstallOptions:
    dest: Path = field(default_factory=default_install_dir)
    start_menu: bool = True
    desktop: bool = False
    autostart: bool = False
    context_menu: bool = False
    gdpi: bool = False  # paketle gelen GoodbyeDPI'i hizmet olarak kaydet (kurucu varsayilani: acik)
    warp: bool = False  # WARP kurulu degilse winget ile arka planda kur (kurucu varsayilani: acik)
    start_menu_path: Path | None = None
    desktop_path: Path | None = None
    hive: int = winreg.HKEY_LOCAL_MACHINE
    reg_key: str = UNINSTALL_KEY


class InstallError(RuntimeError):
    pass


# ---------------- dosyalar ----------------
def extract_payload(zip_path: Path, dest: Path) -> int:
    """Uygulama zip'ini hedefe cikarir (zip-slip korumali). Dosya sayisini dondurur."""
    dest = Path(dest).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            target = (dest / info.filename).resolve()
            if dest != target and dest not in target.parents:
                raise InstallError(f"Zip içinde geçersiz yol (zip-slip): {info.filename}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            count += 1
    return count


def installed_size_kb(dest: Path) -> int:
    return sum(p.stat().st_size for p in Path(dest).rglob("*") if p.is_file()) // 1024


def verify_install(dest: Path) -> None:
    for exe in (system.GUI_EXE, system.CLI_EXE):
        if not (Path(dest) / exe).is_file():
            raise InstallError(f"Kurulum eksik: {exe} bulunamadı ({dest})")


# ---------------- kisayollar ----------------
def create_shortcut(path: Path, target: Path, workdir: Path, description: str, args: str = "") -> None:
    import win32com.client

    path.parent.mkdir(parents=True, exist_ok=True)
    sc = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(path))
    sc.TargetPath = str(target)
    sc.Arguments = args
    sc.WorkingDirectory = str(workdir)
    sc.IconLocation = f"{target},0"
    sc.Description = description
    sc.Save()


def create_shortcuts(opts: InstallOptions) -> list[Path]:
    exe = opts.dest / system.GUI_EXE
    made = []
    if opts.start_menu:
        base = opts.start_menu_path or start_menu_dir()
        for name, args, desc in ((f"{APP_NAME}.lnk", "", "AuxySecurity penceresini aç"),
                                 (f"{APP_NAME} tray ajanı.lnk", "agent", "AuxySecurity tray ajanını başlat")):
            create_shortcut(base / name, exe, opts.dest, desc, args)
            made.append(base / name)
    if opts.desktop:
        base = opts.desktop_path or desktop_dir()
        create_shortcut(base / f"{APP_NAME}.lnk", exe, opts.dest, "AuxySecurity penceresini aç")
        made.append(base / f"{APP_NAME}.lnk")
    return made


def remove_shortcuts(opts: InstallOptions) -> None:
    sm = opts.start_menu_path or start_menu_dir()
    shutil.rmtree(sm, ignore_errors=True)
    (( opts.desktop_path or desktop_dir()) / f"{APP_NAME}.lnk").unlink(missing_ok=True)


# ---------------- Uygulamalar ve ozellikler kaydi ----------------
def register_uninstall(opts: InstallOptions) -> None:
    exe = opts.dest / system.GUI_EXE
    values = {
        "DisplayName": (winreg.REG_SZ, APP_NAME),
        "DisplayVersion": (winreg.REG_SZ, __version__),
        "Publisher": (winreg.REG_SZ, PUBLISHER),
        "InstallLocation": (winreg.REG_SZ, str(opts.dest)),
        "DisplayIcon": (winreg.REG_SZ, str(exe)),
        "UninstallString": (winreg.REG_SZ, f'"{exe}" uninstall'),
        "QuietUninstallString": (winreg.REG_SZ, f'"{exe}" uninstall --quiet'),
        "URLInfoAbout": (winreg.REG_SZ, ABOUT_URL),
        "NoModify": (winreg.REG_DWORD, 1),
        "NoRepair": (winreg.REG_DWORD, 1),
        "EstimatedSize": (winreg.REG_DWORD, installed_size_kb(opts.dest)),
    }
    with winreg.CreateKeyEx(opts.hive, opts.reg_key, 0, winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
        for name, (kind, value) in values.items():
            winreg.SetValueEx(k, name, 0, kind, value)


def unregister_uninstall(opts: InstallOptions) -> None:
    try:
        winreg.DeleteKeyEx(opts.hive, opts.reg_key, winreg.KEY_WOW64_64KEY)
    except FileNotFoundError:
        pass


def read_install_location(hive: int = winreg.HKEY_LOCAL_MACHINE, reg_key: str = UNINSTALL_KEY) -> Path | None:
    try:
        with winreg.OpenKey(hive, reg_key, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            return Path(winreg.QueryValueEx(k, "InstallLocation")[0])
    except FileNotFoundError:
        return None


# ---------------- calisan surecler ----------------
def stop_running_instances(dest: Path) -> list[str]:
    """Kurulum klasorundeki exe'leri calistiran surecleri sonlandirir (guncelleme/kaldirma icin). Yalnizca bizim exe'ler."""
    stopped = []
    # Kendimizi (ve PyInstaller onedir onyukleyici ust surecimizi) OLDURME: kaldirici kurulu exe'den calisir
    keep = [os.getpid(), os.getppid()]
    for exe in (system.GUI_EXE, system.CLI_EXE):
        cmd = ["taskkill", "/F", "/IM", exe]
        for pid in keep:
            cmd += ["/FI", f"PID ne {pid}"]
        proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                              creationflags=subprocess.CREATE_NO_WINDOW)
        if proc.returncode == 0:
            stopped.append(exe)
    return stopped


# ---------------- kurulum / kaldirma ----------------
def install(zip_path: Path, opts: InstallOptions, log=print) -> list[str]:
    """Uygulamayi kurar. Her adim `log` ile bildirilir. Basarisiz adimda InstallError."""
    steps = []
    log("Çalışan örnekler kapatılıyor…")
    stopped = stop_running_instances(opts.dest)
    if stopped:
        steps.append("kapatıldı: " + ", ".join(stopped))
    gdpi_was_running = _stop_our_gdpi(opts.dest)  # calisan goodbyedpi.exe uzerine yazilamaz (guncelleme)
    log(f"Dosyalar kopyalanıyor: {opts.dest}")
    n = extract_payload(zip_path, opts.dest)
    verify_install(opts.dest)
    steps.append(f"{n} dosya kopyalandı")
    if opts.start_menu or opts.desktop:
        log("Kısayollar oluşturuluyor…")
        made = create_shortcuts(opts)
        steps.append(f"{len(made)} kısayol")
    log("Uygulamalar ve özellikler kaydı yazılıyor…")
    register_uninstall(opts)
    steps.append("kaldırma kaydı yazıldı")
    if opts.autostart:
        from auxy.core import autostart

        log("Başlangıç görevi kuruluyor…")
        autostart.install(exe=str(opts.dest / system.GUI_EXE), arguments="agent", workdir=str(opts.dest))
        steps.append("başlangıç görevi kuruldu")
    if opts.context_menu:
        from auxy.core import contextmenu

        contextmenu.install(exe=str(opts.dest / system.GUI_EXE))
        steps.append("sağ tık menüsü kuruldu")
    steps += install_network_tools(opts, log)
    if gdpi_was_running:
        steps.append(_restart_gdpi())
    return steps


def _stop_our_gdpi(dest: Path) -> bool:
    """Hizmet BU kurulumdaki exe'yi calistiriyorsa durdurur; calisiyorduysa True."""
    try:
        from auxy.core import netservices as ns

        info = ns.read_service()
        if info.installed and info.state == "running" and Path(dest).resolve() in Path(info.binary).resolve().parents:
            return ns.service_control("stop").ok
    except Exception:  # noqa: BLE001 - guncelleme dosya kopyalamada zaten hata verir
        pass
    return False


def _restart_gdpi() -> str:
    from auxy.core import netservices as ns

    try:
        return "GoodbyeDPI yeniden başlatıldı" if ns.service_control("start").ok else "GoodbyeDPI yeniden başlatılamadı"
    except Exception as exc:  # noqa: BLE001
        return f"GoodbyeDPI yeniden başlatılamadı: {exc}"


def install_network_tools(opts: InstallOptions, log=print) -> list[str]:
    """GoodbyeDPI hizmeti + WARP. Hicbir adim kurulumu BASARISIZ yapmaz (ag araclari istege bagli ek)."""
    from auxy.core import netservices as ns

    steps = []
    if opts.gdpi:
        tools = opts.dest / ns.TOOLS_SUBDIR
        try:
            if not (tools / "x86_64" / "goodbyedpi.exe").exists() and not (tools / "x86" / "goodbyedpi.exe").exists():
                steps.append("GoodbyeDPI paketi bu kurulumda yok: atlandı")
            else:
                log("GoodbyeDPI hizmeti kaydediliyor…")
                steps.append("GoodbyeDPI: " + ns.install_service(tools).message)
        except Exception as exc:  # noqa: BLE001 - istege bagli
            steps.append(f"GoodbyeDPI kurulamadı: {exc}")
    if opts.warp:
        log("Cloudflare WARP denetleniyor / kuruluyor (arka plan)…")
        try:
            steps.append("WARP: " + ns.install_warp().message)
        except Exception as exc:  # noqa: BLE001
            steps.append(f"WARP kurulamadı: {exc}")
    return steps


def uninstall(opts: InstallOptions, remove_data: bool = False, force_vault: bool = False, log=print) -> list[str]:
    """Sistem girdilerini kaldirir; dosyalari CIKISTAN SONRA siler (calisan exe kendini silemez). Veri korunur (varsayilan)."""
    steps = []
    stop_others = stop_running_instances(opts.dest)  # kendi surecimiz de listede olabilir: taskkill kendini oldurmesin
    del stop_others
    from auxy.core import autostart, cleanup, contextmenu

    # yalnizca BU kurulumu gosteren girdileri kaldir (gelistirme/baska kurulum girdilerine dokunma)
    here = str(opts.dest).lower()
    if autostart.is_installed():
        if here in autostart.registered_command().lower():
            log("Başlangıç görevi kaldırılıyor…")
            autostart.remove()
            steps.append("başlangıç görevi kaldırıldı")
        else:
            steps.append("başlangıç görevi başka bir kurulumu gösteriyor: dokunulmadı")
    if contextmenu.is_installed():
        if here in contextmenu.registered_command().lower():
            contextmenu.remove()
            steps.append("sağ tık menüsü kaldırıldı")
        else:
            steps.append("sağ tık menüsü başka bir kurulumu gösteriyor: dokunulmadı")
    try:  # yalnizca bu kurulumdaki GoodbyeDPI'i kaldir; kullanicinin baska konumdaki hizmetine dokunma. WARP kalir.
        from auxy.core import netservices as ns

        steps.append("GoodbyeDPI: " + ns.remove_service(only_under=opts.dest).message)
    except Exception as exc:  # noqa: BLE001
        steps.append(f"GoodbyeDPI kaldırılamadı: {exc}")
    remove_shortcuts(opts)
    steps.append("kısayollar kaldırıldı")
    unregister_uninstall(opts)
    steps.append("kaldırma kaydı silindi")
    if remove_data:
        for s in cleanup.run(remove_data=True, force_vault=force_vault):
            if s.name == "Veri":
                steps.append(f"veri: {s.detail}")
    else:
        from auxy.core import paths

        steps.append(f"veri korundu: {paths.home()}")
    schedule_delete(opts.dest)
    steps.append(f"dosyalar çıkıştan sonra silinecek: {opts.dest}")
    return steps


def schedule_delete(dest: Path, delay_s: int = 3) -> None:
    """Calisan kaldirici kendi exe'sini silemez: cikistan sonra klasoru silen ayrik bir cmd baslatir."""
    # birkac deneme: onyukleyici/DLL kilitleri birakilana kadar bekle (DETACHED_PROCESS ile CREATE_NO_WINDOW birlikte
    # kullanilamaz; gercek testte cmd hic calismadi)
    cmd = (f'ping -n {delay_s + 1} 127.0.0.1 > nul & for /l %i in (1,1,5) do '
           f'@(if exist "{dest}" (rmdir /s /q "{dest}" 2>nul & ping -n 3 127.0.0.1 > nul))')
    base = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    kw = dict(close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # TEK DIZGE ver: liste verilirse subprocess icerideki tirnaklari kacirir ve cmd komutu bozuk okur
    line = f"cmd.exe /d /c {cmd}"
    try:  # ust surecin job'i kapaninca oldurulmesin
        subprocess.Popen(line, creationflags=base | 0x01000000, **kw)  # CREATE_BREAKAWAY_FROM_JOB
    except OSError:  # job kopmaya izin vermiyor
        subprocess.Popen(line, creationflags=base, **kw)
