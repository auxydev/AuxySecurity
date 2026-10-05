"""GUI'den bagimsiz gorunum mantigi (test edilebilir): genel saglik degerlendirmesi."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from auxy.core.defender import DefenderStatus

OK, WARN, CRIT = "ok", "warn", "crit"

SIGNATURE_WARN_DAYS = 3


@dataclass(frozen=True)
class Health:
    level: str
    title: str
    reasons: list[str] = field(default_factory=list)
    crit_count: int = 0  # tray rozeti: kritik sorun sayisi
    warn_count: int = 0  # kritik olmayan sorun sayisi

    @property
    def badge(self) -> int:
        """Rozette gosterilecek sayi: kritik varsa kritik sayisi, yoksa kritik olmayan sayisi."""
        return self.crit_count or self.warn_count


def signature_age_days(status: DefenderStatus, now: datetime | None = None) -> int | None:
    last = status.status.get("AntivirusSignatureLastUpdated")
    if not isinstance(last, datetime):
        return None
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    return max(0, (now - last).days)


def evaluate(status: DefenderStatus, now: datetime | None = None) -> Health:
    s = status.status
    crit: list[str] = []
    warn: list[str] = []

    if not s.get("AMServiceEnabled") or not s.get("AntivirusEnabled"):
        crit.append("Microsoft Defender antivirüs kapalı.")
    if not s.get("RealTimeProtectionEnabled"):
        crit.append("Gerçek zamanlı koruma kapalı.")

    age = signature_age_days(status, now)
    if age is not None and age >= SIGNATURE_WARN_DAYS:
        warn.append(f"Virüs imzaları {age} gündür güncellenmedi.")
    if not s.get("BehaviorMonitorEnabled"):
        warn.append("Davranış izleme kapalı.")
    if status.prefs.get("MAPSReporting") == 0:
        warn.append("Bulut korumalı koruma kapalı.")
    if not s.get("IsTamperProtected"):
        warn.append("Tamper Protection kapalı.")

    if crit:
        return Health(CRIT, "Cihazın korunmuyor", crit + warn, len(crit), len(warn))
    if warn:
        return Health(WARN, "Dikkat edilmesi gerekenler var", warn, 0, len(warn))
    return Health(OK, "Cihazın korunuyor", ["Tüm temel korumalar açık ve güncel."])
