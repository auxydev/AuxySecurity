"""Tray ajaninin gercek zamanli yardimcilari. Hepsi OLAY TABANLI: bekleme sirasinda CPU kullanmaz.

- FolderWatcher        : klasorlere dusen yeni dosyalari (ReadDirectoryChangesW) otomatik tarar
- DefenderEventListener: Defender olay gunlugune abone olur (tehdit bulundu / islem uygulandi)
- UsbWatcher           : takilan cikarilabilir surucuyu tarar (WMI olay bildirimi)
- ScheduledScanner     : haftalik taramayi bos zamanda calistirir (tek zamanlayici)
"""

from __future__ import annotations

import ctypes
import os
import queue
import re
import threading
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from auxy.core import config as cfgmod
from auxy.core import scan, threats
from auxy.core.log import get_logger
from auxy.core.service import AuxyError

Notify = Callable[[str], None]

# ---------------- ortak yardimcilar ----------------
IGNORED_SUFFIXES = {".tmp", ".crdownload", ".part", ".partial", ".download", ".opdownload", ".!ut", ".temp"}
BATCH_LIMIT = 10       # bir yiginda bu kadar dosyadan fazlasi gelirse tek tek degil klasor olarak taranir
MAX_DIRS_PER_BATCH = 5
STABLE_POLL_S = 1.0
STABLE_TIMEOUT_S = 120


def should_scan(path: str) -> bool:
    """Gecici/yarim indirme dosyalarini ve olmayan yollari atla."""
    p = Path(path)
    name = p.name.lower()
    if p.suffix.lower() in IGNORED_SUFFIXES or name.startswith("~$") or name.startswith(".~"):
        return False
    return True


def plan_batch(paths_: list[str]) -> list[str]:
    """Az dosya: tek tek. Cok dosya (ornegin zip acma): benzersiz ust klasorler (en fazla 5)."""
    unique = list(dict.fromkeys(paths_))
    if len(unique) <= BATCH_LIMIT:
        return unique
    parents = list(dict.fromkeys(str(Path(p).parent) for p in unique))
    return parents[:MAX_DIRS_PER_BATCH]


def wait_until_stable(path: str, poll: float = STABLE_POLL_S, timeout: float = STABLE_TIMEOUT_S,
                      size_of: Callable[[str], int] | None = None,
                      sleep: Callable[[float], None] | None = None) -> bool:
    """Dosya boyutu iki olcum arasinda degismeyene kadar bekler. Dosya kaybolursa False."""
    size_of = size_of or (lambda p: os.path.getsize(p))
    sleep = sleep or time.sleep  # cagri aninda baglanir (testlerde degistirilebilsin)
    waited, last = 0.0, -1
    while waited <= timeout:
        try:
            size = size_of(path)
        except OSError:
            return False
        if size == last:
            return True
        last = size
        sleep(poll)
        waited += poll
    return False  # hala buyuyor: sonra yeni olay gelecek


# ---------------- klasor izleme ----------------
class FolderWatcher:
    def __init__(self, folders: list[str], manager: scan.ScanManager, notify: Notify,
                 on_threat: Callable[[str, list[str]], None] | None = None, recursive: bool = False):
        self.folders = [f for f in folders if Path(f).is_dir()]
        self._recursive = recursive
        self._manager = manager
        self._notify = notify
        self._on_threat = on_threat
        self._queue: queue.Queue[str] = queue.Queue()
        self._stop = threading.Event()
        self._observer = None
        self._thread: threading.Thread | None = None
        self._log = get_logger()

    def start(self) -> None:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        outer = self

        class Handler(FileSystemEventHandler):
            def on_created(self, event):
                if not event.is_directory:
                    outer.enqueue(event.src_path)

            def on_moved(self, event):  # .crdownload -> gercek ad
                if not event.is_directory:
                    outer.enqueue(event.dest_path)

        self._observer = Observer()
        for folder in self.folders:
            self._observer.schedule(Handler(), folder, recursive=self._recursive)
        self._observer.start()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="auxy-folder-scan")
        self._thread.start()
        self._log.info("Klasor izleme basladi: %s", self.folders)

    def stop(self) -> None:
        self._stop.set()
        self._queue.put("")  # worker'i uyandir
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=3)
        self._log.info("Klasor izleme durdu")

    def enqueue(self, path: str) -> None:
        if should_scan(path):
            self._queue.put(path)

    def _worker(self) -> None:
        while not self._stop.is_set():
            first = self._queue.get()  # olay gelene kadar uyur
            if self._stop.is_set():
                return
            try:
                self._process_batch(first)
            except Exception:  # bir dosya hatasi izlemeyi oldurmesin; nedenini gunluge yaz
                self._log.exception("klasor izleme: toplu tarama hatasi")

    def _process_batch(self, first: str) -> None:
        batch = [first] if first else []
        time.sleep(2)  # kisa toplama penceresi (zip acma gibi seller icin)
        while True:
            try:
                p = self._queue.get_nowait()
                if p:
                    batch.append(p)
            except queue.Empty:
                break
        unique = list(dict.fromkeys(batch))
        if len(unique) <= BATCH_LIMIT:  # az dosya: her birinin yazimi bitsin
            unique = [p for p in unique if wait_until_stable(p) or Path(p).exists()]
        # cok dosya (zip acma): tek tek bekleme yok, klasor bir kez taranir
        for target in plan_batch(unique):
            self._scan_one(target)

    def _scan_one(self, target: str) -> None:
        for attempt in range(5):
            try:
                res = self._manager.run(scan.CUSTOM, target, quiet=True)
            except scan.ScanBusyError:
                if self._stop.wait(30):  # baska tarama suruyor: sonra tekrar dene
                    return
                continue
            except AuxyError as exc:  # dosya araya kaybolmus olabilir
                self._log.info("otomatik tarama atlandi (%s): %s", target, exc)
                return
            if res.threats:
                self._notify(f"Tehdit bulundu: {', '.join(res.threats)}\n{Path(target).name}")
                if self._on_threat:
                    self._on_threat(res.threats[0], [target])
            return


# ---------------- Defender olay gunlugu ----------------
@dataclass(frozen=True)
class DefenderEvent:
    event_id: int
    threat: str
    severity: str
    path: str
    action: str


def parse_event_xml(xml_text: str) -> DefenderEvent | None:
    """Defender 1116/1117 olayi XML'i. Alan adlari yerellestirilmez (EventData/Data Name)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    ns = {"e": "http://schemas.microsoft.com/win/2004/08/events/event"}
    eid = root.find("e:System/e:EventID", ns)
    if eid is None or not (eid.text or "").strip().isdigit():
        return None
    data = {d.get("Name", ""): (d.text or "") for d in root.findall("e:EventData/e:Data", ns)}
    return DefenderEvent(int(eid.text), data.get("Threat Name", ""), data.get("Severity Name", ""),
                         threats.clean_resource(data.get("Path", "")), data.get("Action Name", ""))


class DefenderEventListener:
    """EvtSubscribe ile ITME (push) tabanli abonelik: poll yok."""

    QUERY = "*[System[(EventID=1116 or EventID=1117)]]"
    CHANNEL = "Microsoft-Windows-Windows Defender/Operational"

    def __init__(self, on_event: Callable[[DefenderEvent], None]):
        self._on_event = on_event
        self._handle = None
        self._log = get_logger()

    def start(self) -> None:
        import win32evtlog

        self._win32evtlog = win32evtlog
        self._handle = win32evtlog.EvtSubscribe(
            self.CHANNEL, win32evtlog.EvtSubscribeToFutureEvents, Query=self.QUERY,
            Callback=self._callback, Context=None,
        )
        self._log.info("Defender olay aboneligi basladi")

    def _callback(self, reason, context, event):
        if reason != self._win32evtlog.EvtSubscribeActionDeliver:
            return
        try:
            xml = self._win32evtlog.EvtRender(event, self._win32evtlog.EvtRenderEventXml)
            ev = parse_event_xml(xml)
            if ev:
                self._on_event(ev)
        except Exception as exc:  # callback hata firlatmamali
            self._log.warning("olay islenemedi: %s", exc)

    def stop(self) -> None:
        self._handle = None  # PyHANDLE serbest birakilinca abonelik kapanir


# ---------------- USB ----------------
DRIVE_REMOVABLE = 2


def is_removable_drive(drive: str) -> bool:
    return ctypes.windll.kernel32.GetDriveTypeW(drive.rstrip("\\") + "\\") == DRIVE_REMOVABLE


class UsbWatcher:
    def __init__(self, manager: scan.ScanManager, notify: Notify):
        self._manager = manager
        self._notify = notify
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._log = get_logger()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="auxy-usb")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        try:
            svc = win32com.client.GetObject(r"winmgmts:\\.\root\cimv2")
            events = svc.ExecNotificationQuery("SELECT * FROM Win32_VolumeChangeEvent WHERE EventType = 2")
            while not self._stop.is_set():
                try:
                    ev = events.NextEvent(5000)  # 5 sn zaman asimi: bekleme WMI'da, CPU yok
                except Exception:
                    continue  # zaman asimi
                self._handle(str(ev.DriveName))
        except Exception as exc:
            self._log.warning("USB izleme durdu: %s", exc)
        finally:
            pythoncom.CoUninitialize()

    def _handle(self, drive: str) -> None:
        if not is_removable_drive(drive):
            return
        root = drive.rstrip("\\") + "\\"
        self._notify(f"Sürücü takıldı ({drive}); taranıyor…")
        try:
            res = self._manager.run(scan.CUSTOM, root)
        except AuxyError as exc:
            self._notify(f"{drive} taranamadı: {exc}")
            return
        self._notify(f"{drive}: {res.summary()}")


# ---------------- zamanlanmis tarama ----------------
def next_run(now: datetime, weekday: int, hour: int) -> datetime:
    """`now`'dan sonraki (haftanin gunu, saat) ani. Tam o an ise sonraki haftaya atlar."""
    candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    candidate += timedelta(days=(weekday - now.weekday()) % 7)
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate


class _LastInput(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def idle_seconds() -> float:
    info = _LastInput(ctypes.sizeof(_LastInput), 0)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
    return (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000.0


class _PowerStatus(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                ("BatteryLifeTime", ctypes.c_uint), ("BatteryFullLifeTime", ctypes.c_uint)]


def on_ac_power() -> bool:
    st = _PowerStatus()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(st)):
        return True
    return st.ACLineStatus != 0  # 0 = pilde; 1/255 = prize/bilinmiyor


IDLE_REQUIRED_S = 300
RETRY_S = 600
GIVE_UP_AFTER = timedelta(hours=6)


class ScheduledScanner:
    """Tek bir Event.wait zamanlayicisi. Bos degilse ya da pildeyse 10 dk sonra tekrar dener, 6 saat sonra vazgecer."""

    def __init__(self, sched: cfgmod.ScheduledScan, manager: scan.ScanManager, notify: Notify,
                 now: Callable[[], datetime] = datetime.now, idle: Callable[[], float] = idle_seconds,
                 ac: Callable[[], bool] = on_ac_power):
        self._s, self._manager, self._notify = sched, manager, notify
        self._now, self._idle, self._ac = now, idle, ac
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._log = get_logger()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True, name="auxy-schedule")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            due = next_run(self._now(), self._s.weekday, self._s.hour)
            if self._stop.wait(max(1.0, (due - self._now()).total_seconds())):
                return
            self._attempt(due)

    def _attempt(self, due: datetime) -> bool:
        """Kosullar uygunsa tarar. True: tarama yapildi (ya da vazgecildi)."""
        while not self._stop.is_set():
            if self._now() - due > GIVE_UP_AFTER:
                self._log.info("Zamanlanmis tarama bu hafta atlandi (uygun an bulunamadi)")
                return True
            if self._idle() >= IDLE_REQUIRED_S and self._ac():
                kind = scan.FULL if self._s.kind == "full" else scan.QUICK
                try:
                    res = self._manager.run(kind)
                    self._notify(f"Zamanlanmış tarama: {res.summary()}")
                except AuxyError as exc:
                    self._notify(f"Zamanlanmış tarama yapılamadı: {exc}")
                return True
            if self._stop.wait(RETRY_S):
                return False
        return False


def safe_name(path: str) -> str:
    return re.sub(r"[\r\n]", " ", Path(path).name)
