"""Tarama yoneticisi: MpCmdRun.exe uzerinden hizli / tam / ozel tarama, imza guncelleme, gecmis.

Defender tarama ilerleme yuzdesi sunmaz; arayuz belirsiz ilerleme + gecen sure gosterir.
Hizli/ozel tarama ve imza guncelleme yonetici gerektirmez; taramayi IPTAL etmek gerektirir.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from auxy.core import paths, threats
from auxy.core.log import get_logger
from auxy.core.service import AuxyError

QUICK, FULL, CUSTOM = 1, 2, 3
TYPE_NAMES = {QUICK: "Hızlı tarama", FULL: "Tam tarama", CUSTOM: "Özel tarama"}
HISTORY_LIMIT = 50

COMPLETED, CANCELLED, FAILED = "completed", "cancelled", "failed"


class ScanBusyError(AuxyError):
    pass


@dataclass(frozen=True)
class ScanResult:
    scan_type: int
    path: str
    started: str  # ISO, yerel saat
    seconds: float
    status: str
    exit_code: int | None
    threats: list[str]  # tarama sirasinda/sonrasinda bulunan yeni tehdit adlari

    @property
    def title(self) -> str:
        return TYPE_NAMES.get(self.scan_type, "Tarama")

    def summary(self) -> str:
        if self.status == CANCELLED:
            return f"{self.title} iptal edildi."
        if self.status == FAILED:
            return f"{self.title} başarısız oldu (çıkış kodu {self.exit_code})."
        if self.threats:
            return f"{self.title} bitti: {len(self.threats)} tehdit bulundu ({', '.join(self.threats)})."
        return f"{self.title} bitti: tehdit bulunamadı."


def mpcmdrun_path() -> Path:
    base = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Microsoft/Windows Defender/Platform"

    def version_key(p: Path):
        try:
            return tuple(int(x) for x in p.name.replace("-", ".").split("."))
        except ValueError:
            return ()

    if base.exists():
        for d in sorted((p for p in base.iterdir() if p.is_dir()), key=version_key, reverse=True):
            exe = d / "MpCmdRun.exe"
            if exe.exists():
                return exe
    fallback = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Windows Defender/MpCmdRun.exe"
    if fallback.exists():
        return fallback
    raise AuxyError("MpCmdRun.exe bulunamadı; Microsoft Defender kurulu görünmüyor.")


def build_scan_args(scan_type: int, path: str | None = None) -> list[str]:
    if scan_type not in TYPE_NAMES:
        raise AuxyError(f"Geçersiz tarama türü: {scan_type}")
    args = ["-Scan", "-ScanType", str(scan_type)]
    if scan_type == CUSTOM:
        if not path or not Path(path).exists():
            raise AuxyError(f"Taranacak yol bulunamadı: {path!r}")
        args += ["-File", str(Path(path))]
    return args


def _flags() -> int:
    return subprocess.CREATE_NO_WINDOW


class ScanManager:
    """Ayni anda tek tarama. run() bloklar; arayuz bunu iscide cagirir."""

    def __init__(self):
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._cancel_requested = False
        self._log = get_logger()

    @property
    def running(self) -> bool:
        return self._proc is not None

    def run(self, scan_type: int, path: str | None = None) -> ScanResult:
        args = build_scan_args(scan_type, path)
        with self._lock:
            if self._proc is not None:
                raise ScanBusyError("Zaten bir tarama çalışıyor.")
            self._cancel_requested = False
            started = datetime.now()
            self._proc = subprocess.Popen(
                [str(mpcmdrun_path()), *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                creationflags=_flags(),
            )
            proc = self._proc
        self._log.info("TARAMA basladi: %s %s", TYPE_NAMES[scan_type], path or "")
        try:
            out, _ = proc.communicate()
        finally:
            with self._lock:
                self._proc = None
        seconds = (datetime.now() - started).total_seconds()
        if self._cancel_requested:
            status = CANCELLED
        elif proc.returncode == 0:
            status = COMPLETED
        else:
            status = FAILED
            self._log.error("tarama basarisiz rc=%s cikti=%s", proc.returncode,
                            out.decode("utf-8", "replace")[-400:])
        found = self._new_threats(started) if status == COMPLETED else []
        result = ScanResult(scan_type, path or "", started.isoformat(timespec="seconds"),
                            round(seconds, 1), status, proc.returncode, found)
        append_history(result)
        self._log.info("TARAMA bitti: %s", result.summary())
        return result

    @staticmethod
    def _new_threats(since: datetime) -> list[str]:
        try:
            names = [d.name for d in threats.read_detections()
                     if d.time and d.time >= since.replace(microsecond=0)]
        except AuxyError:
            return []
        return sorted(set(names))

    def mark_cancel_requested(self) -> None:
        self._cancel_requested = True


def cancel_scan_command() -> tuple[int, str]:
    """MpCmdRun -Scan -Cancel (yonetici gerekir). (cikis kodu, cikti)"""
    proc = subprocess.run(
        [str(mpcmdrun_path()), "-Scan", "-Cancel"], capture_output=True, creationflags=_flags(),
        timeout=60,
    )
    return proc.returncode, proc.stdout.decode("utf-8", "replace")


def update_signatures() -> tuple[bool, str]:
    """Imzalari gunceller (yonetici gerekmez, ~20 sn). (basarili, mesaj)"""
    proc = subprocess.run(
        [str(mpcmdrun_path()), "-SignatureUpdate"], capture_output=True, creationflags=_flags(),
        timeout=300,
    )
    out = proc.stdout.decode("utf-8", "replace")
    ver = next((ln.split(":", 1)[1].strip() for ln in out.splitlines()
                if ln.startswith("AntiVirus Signature Version")), "?")
    if proc.returncode == 0:
        return True, f"İmzalar güncel (sürüm {ver})."
    return False, f"İmza güncelleme başarısız (çıkış kodu {proc.returncode})."


# ---- gecmis ----
def load_history() -> list[ScanResult]:
    try:
        raw = json.loads(paths.scan_history_file().read_text(encoding="utf-8"))
        return [ScanResult(**r) for r in raw]
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        return []


def append_history(result: ScanResult) -> None:
    items = [*load_history(), result][-HISTORY_LIMIT:]
    target = paths.scan_history_file()
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps([asdict(i) for i in items], indent=1), encoding="utf-8")
    os.replace(tmp, target)


def format_duration(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60:02d}:{s % 60:02d}"
