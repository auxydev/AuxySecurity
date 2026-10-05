"""Oturum acilisinda tray ajanini yuksek yetkiyle (UAC istemsiz) baslatan Gorev Zamanlayici gorevi.

Registry `Run` anahtari yukseltilmis surec baslatamaz; "en yuksek yetkiyle calistir" ozellikli
bir gorev baslatabilir. Gorev yalnizca bu kullanicinin oturum acisinda calisir.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape, unescape

from auxy.core import system
from auxy.core.service import AuxyError

TASK_NAME = "AuxySecurity"
DELAY = "PT30S"  # acilisi yavaslatmamak icin 30 sn gecikme
REPEAT = "PT10M"  # ajan olduyse (surec olumu/yerel cokme) en gec 10 dk sonra yeniden baslar; calisirken IgnoreNew yenisini engeller


@dataclass(frozen=True)
class AutostartStatus:
    installed: bool
    last_result: str = ""


def build_task_xml(user: str, exe: str, workdir: str, arguments: str = "-m auxy agent",
                   now: datetime | None = None) -> str:
    start = (now or datetime.now()).strftime("%Y-%m-%dT%H:%M:%S")
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>AuxySecurity tray ajani (oturum acilisinda, yuksek yetkiyle)</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{escape(user)}</UserId>
      <Delay>{DELAY}</Delay>
    </LogonTrigger>
    <TimeTrigger>
      <StartBoundary>{start}</StartBoundary>
      <Repetition>
        <Interval>{REPEAT}</Interval>
      </Repetition>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{escape(user)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <StartWhenAvailable>true</StartWhenAvailable>
    <Enabled>true</Enabled>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(exe)}</Command>
      <Arguments>{escape(arguments)}</Arguments>
      <WorkingDirectory>{escape(workdir)}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def project_dir() -> str:
    """Gorev calisma dizini: proje koku (src/auxy/core/autostart.py -> ... -> kok). os.getcwd() KULLANILMAZ:
    yukseltilmis yardimci surecte calisma dizini System32 olurdu."""
    root = Path(__file__).resolve().parents[3]
    return str(root if root.is_dir() else Path.home())


def _current_user() -> str:
    return f"{os.environ.get('USERDOMAIN', '')}\\{os.environ['USERNAME']}".lstrip("\\")


def _schtasks(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["schtasks", *args], capture_output=True, text=True, errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def install(exe: str | None = None, arguments: str | None = None, workdir: str | None = None) -> None:
    """Gorevi kurar. Parametreler verilmezse calisan uygulamanin exe'si kullanilir; kurulum programi ise
    KURULAN exe'yi acikca verir (kendi exe'si degil)."""
    if not system.is_admin():
        raise AuxyError("Gorevi kurmak icin yonetici yetkisi gerekir.")
    xml = build_task_xml(_current_user(), exe or system.app_exe(windowless=True), workdir or project_dir(),
                         arguments if arguments is not None else system.launch_params(["agent"]))
    fd, path = tempfile.mkstemp(suffix=".xml")
    os.close(fd)
    try:
        with open(path, "w", encoding="utf-16") as f:
            f.write(xml)
        proc = _schtasks("/Create", "/TN", TASK_NAME, "/XML", path, "/F")
    finally:
        os.remove(path)
    if proc.returncode != 0:
        raise AuxyError(f"schtasks basarisiz: {(proc.stderr or proc.stdout).strip()}")


def remove() -> None:
    if not system.is_admin():
        raise AuxyError("Gorevi kaldirmak icin yonetici yetkisi gerekir.")
    if not status().installed:
        return
    proc = _schtasks("/Delete", "/TN", TASK_NAME, "/F")
    if proc.returncode != 0:
        raise AuxyError(f"schtasks basarisiz: {(proc.stderr or proc.stdout).strip()}")


def is_installed() -> bool:
    """Hizli kontrol (yalnizca schtasks /Query)."""
    return _schtasks("/Query", "/TN", TASK_NAME).returncode == 0


def registered_command() -> str:
    """Gorevin calistirdigi exe yolu (yoksa bos)."""
    proc = _schtasks("/Query", "/TN", TASK_NAME, "/XML")
    if proc.returncode != 0:
        return ""
    m = re.search(r"<Command>(.*?)</Command>", proc.stdout, re.S)
    return unescape(m.group(1)) if m else ""


def status() -> AutostartStatus:
    if _schtasks("/Query", "/TN", TASK_NAME).returncode != 0:
        return AutostartStatus(False)
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command",
         f"(Get-ScheduledTaskInfo -TaskName '{TASK_NAME}').LastTaskResult"],
        capture_output=True, text=True, errors="replace", creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return AutostartStatus(True, proc.stdout.strip() or "?")
