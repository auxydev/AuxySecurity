"""Defender durumunu WMI uzerinden okur (PowerShell baslatmadan).

Namespace: root/Microsoft/Windows/Defender
  MSFT_MpComputerStatus -> calisma durumu (salt-okunur)
  MSFT_MpPreference     -> ayarlar
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime

NAMESPACE = r"root\Microsoft\Windows\Defender"

STATUS_FIELDS = (
    "AMServiceEnabled",
    "AntivirusEnabled",
    "AntispywareEnabled",
    "RealTimeProtectionEnabled",
    "BehaviorMonitorEnabled",
    "IoavProtectionEnabled",
    "OnAccessProtectionEnabled",
    "NISEnabled",
    "IsTamperProtected",
    "AMProductVersion",
    "AntivirusSignatureVersion",
    "AntivirusSignatureLastUpdated",
)

PREF_FIELDS = (
    "DisableRealtimeMonitoring",
    "MAPSReporting",
    "SubmitSamplesConsent",
    "PUAProtection",
    "EnableControlledFolderAccess",
    "EnableNetworkProtection",
)

MAPS_LABELS = {0: "Kapali", 1: "Temel", 2: "Gelismis"}
CFA_LABELS = {0: "Kapali", 1: "Acik", 2: "Yalnizca denetim"}
ON_OFF_LABELS = {0: "Kapali", 1: "Acik", 2: "Denetim modu"}


class DefenderError(RuntimeError):
    """Defender WMI sorgusu basarisiz oldu."""


@contextmanager
def com_apartment():
    """Bu is parcaciginda COM'u baslatir (WMI icin sart). Zaten baslatilmissa zararsizdir.

    pywin32 yalnizca ILK import eden is parcacigi icin COM baslatir; baska is parcaciklarinda
    `GetObject("winmgmts:...")` MK_E_SYNTAX ("Gecersiz sozdizimi") ile coker ve is parcacigi sessizce olur.
    """
    import pythoncom

    initialized = False
    try:
        pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
        initialized = True
    except pythoncom.com_error:
        pass  # RPC_E_CHANGED_MODE: bu is parcacigi baska modda zaten baslatilmis, sorun degil
    try:
        yield
    finally:
        if initialized:
            pythoncom.CoUninitialize()


@dataclass(frozen=True)
class DefenderStatus:
    status: dict
    prefs: dict

    @property
    def realtime_on(self) -> bool:
        return bool(self.status.get("RealTimeProtectionEnabled"))

    @property
    def tamper_protected(self) -> bool:
        return bool(self.status.get("IsTamperProtected"))


def _query_one(wmi_service, class_name: str, fields: tuple[str, ...]) -> dict:
    # SELECT * yerine tek ornek alinir; secili alanlar okunur.
    items = wmi_service.ExecQuery(f"SELECT * FROM {class_name}")
    for item in items:
        out = {}
        for name in fields:
            try:
                value = getattr(item, name)
            except AttributeError:
                value = None
            out[name] = _normalize(value)
        return out
    raise DefenderError(f"{class_name} icin kayit bulunamadi")


def _normalize(value):
    # pywin32 tarihleri pywintypes.datetime olarak dondurur
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, str) and len(value) == 25 and value[14] == "." and value[-4] in "+-":
        # DMTF: yyyymmddHHMMSS.ffffff+UUU (UTC)
        try:
            return datetime.strptime(value[:14], "%Y%m%d%H%M%S")
        except ValueError:
            return value
    return value


def read_status() -> DefenderStatus:
    """Defender durum ve ayarlarini oku. Yonetici yetkisi gerekmez."""
    try:
        import win32com.client  # gec import: ajan acilisinda yuk olmasin

        with com_apartment():
            wmi_service = win32com.client.GetObject(rf"winmgmts:\\.\{NAMESPACE}")
            status = _query_one(wmi_service, "MSFT_MpComputerStatus", STATUS_FIELDS)
            prefs = _query_one(wmi_service, "MSFT_MpPreference", PREF_FIELDS)
            del wmi_service  # COM nesnesi CoUninitialize'dan ONCE serbest kalsin
    except DefenderError:
        raise
    except Exception as exc:  # com_error vb.
        raise DefenderError(f"Defender WMI erisimi basarisiz: {exc}") from exc
    return DefenderStatus(status=status, prefs=prefs)
