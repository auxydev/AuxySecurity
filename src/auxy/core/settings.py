"""Yonetilebilen Defender ayarlari ve izinli deger listesi.

PowerShell komutuna yalnizca bu tablodaki sabit parametre adlari ve dogrulanmis
bool/int degerleri girer; kullanici girdisi komuta gomulmez.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Setting:
    key: str
    label: str
    ps_param: str  # Set-MpPreference parametresi
    pref_field: str  # MSFT_MpPreference alani (WMI)
    choices: dict[str, bool | int]  # kullanici adi -> ham (WMI) deger
    tamper_guarded: bool = False  # Tamper Protection acikken degistirilemez

    def name_of(self, raw) -> str:
        for name, value in self.choices.items():
            if value == raw and type(value) is type(raw):
                return name
        return f"?({raw})"

    def ps_literal(self, raw) -> str:
        if isinstance(raw, bool):
            return "$true" if raw else "$false"
        if isinstance(raw, int):
            return str(int(raw))
        raise ValueError(f"Gecersiz ham deger: {raw!r}")


# Hizli anahtar olarak sunulan ayarlar (maps uc seviyeli oldugu icin ayri kontrol)
TOGGLE_KEYS = ("realtime", "pua", "cfa", "netprot")

SETTINGS: dict[str, Setting] = {
    s.key: s
    for s in (
        Setting(
            "realtime", "Gerçek zamanlı koruma", "DisableRealtimeMonitoring",
            "DisableRealtimeMonitoring", {"on": False, "off": True}, tamper_guarded=True,
        ),
        Setting(
            "maps", "Bulut koruma (MAPS)", "MAPSReporting", "MAPSReporting",
            {"off": 0, "basic": 1, "advanced": 2}, tamper_guarded=True,
        ),
        Setting(
            "pua", "İstenmeyen uygulama koruması", "PUAProtection", "PUAProtection",
            {"off": 0, "on": 1, "audit": 2},
        ),
        Setting(
            "cfa", "Denetimli klasör erişimi", "EnableControlledFolderAccess",
            "EnableControlledFolderAccess", {"off": 0, "on": 1, "audit": 2},
        ),
        Setting(
            "netprot", "Ağ koruması", "EnableNetworkProtection",
            "EnableNetworkProtection", {"off": 0, "on": 1, "audit": 2},
        ),
    )
}

