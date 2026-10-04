"""Defender tehdit tespitlerini WMI'dan okur (yonetici gerekmez).

MSFT_MpThreatDetection: tespit olaylari (zaman, dosya yollari, islem sonucu)
MSFT_MpThreat         : tehdit tanimi (ad, siddet)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from auxy.core.defender import NAMESPACE, DefenderError

SEVERITY = {0: "Bilinmiyor", 1: "Düşük", 2: "Orta", 4: "Yüksek", 5: "Çok yüksek"}
_RESOURCE_PREFIX = re.compile(r"^[A-Za-z]+:_")


@dataclass(frozen=True)
class Detection:
    threat_id: int
    name: str
    severity: str
    paths: list[str] = field(default_factory=list)
    time: datetime | None = None
    handled: bool = False  # Defender islemi (karantina/temizleme) basarili mi
    active: bool = False


def clean_resource(resource: str) -> str:
    """'file:_C:\\x\\y.exe' -> 'C:\\x\\y.exe'"""
    return _RESOURCE_PREFIX.sub("", resource, count=1)


def parse_dmtf(value: str) -> datetime | None:
    """'20261004195413.691000+000' (UTC'den sapma dakika) -> saat dilimli datetime."""
    m = re.fullmatch(r"(\d{14})\.(\d{6})([+-]\d{3})", value)
    if not m:
        return None
    base = datetime.strptime(m.group(1), "%Y%m%d%H%M%S")
    offset = timedelta(minutes=int(m.group(3)))
    return (base - offset).replace(tzinfo=timezone.utc)


def to_local_naive(value) -> datetime | None:
    """WMI tarihini yerel saatte saat dilimsiz datetime'a cevirir."""
    if isinstance(value, str):
        value = parse_dmtf(value)
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is not None:
        return value.astimezone().replace(tzinfo=None)
    return value


def _fetch(service, class_name: str) -> list:
    return list(service.ExecQuery(f"SELECT * FROM {class_name}"))


def read_detections(limit: int = 200) -> list[Detection]:
    """En yeni tespitler basta."""
    try:
        import win32com.client

        service = win32com.client.GetObject(rf"winmgmts:\\.\{NAMESPACE}")
        threats = {}
        for t in _fetch(service, "MSFT_MpThreat"):
            threats[t.ThreatID] = t
        out = []
        for d in _fetch(service, "MSFT_MpThreatDetection"):
            t = threats.get(d.ThreatID)
            out.append(
                Detection(
                    threat_id=int(d.ThreatID),
                    name=str(getattr(t, "ThreatName", None) or f"Tehdit {d.ThreatID}"),
                    severity=SEVERITY.get(getattr(t, "SeverityID", 0), "Bilinmiyor"),
                    paths=[clean_resource(r) for r in (d.Resources or [])],
                    time=to_local_naive(d.InitialDetectionTime),
                    handled=bool(d.ActionSuccess),
                    active=bool(getattr(t, "IsActive", False)),
                )
            )
    except Exception as exc:
        raise DefenderError(f"Tehditler okunamadı: {exc}") from exc
    out.sort(key=lambda x: x.time or datetime.min, reverse=True)
    return out[:limit]
