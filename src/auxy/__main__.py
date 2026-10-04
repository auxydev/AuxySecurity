"""Komut satiri girisi: python -m auxy <komut>"""

from __future__ import annotations

import argparse
import sys

from auxy import __version__
from auxy.core import defender, system


def _yn(value) -> str:
    return "ACIK " if value else "KAPALI"


def cmd_status(_args) -> int:
    try:
        st = defender.read_status()
    except defender.DefenderError as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 1

    s, p = st.status, st.prefs
    print(f"AuxySecurity {__version__}  |  Yonetici: {'evet' if system.is_admin() else 'hayir'}")
    print("-" * 52)
    print("DURUM (salt-okunur)")
    print(f"  Defender servisi          : {_yn(s['AMServiceEnabled'])}")
    print(f"  Antivirus                 : {_yn(s['AntivirusEnabled'])}")
    print(f"  Gercek zamanli koruma     : {_yn(s['RealTimeProtectionEnabled'])}")
    print(f"  Davranis izleme           : {_yn(s['BehaviorMonitorEnabled'])}")
    print(f"  Tamper Protection         : {_yn(s['IsTamperProtected'])}")
    print(f"  Imza surumu               : {s['AntivirusSignatureVersion']}")
    print(f"  Imza guncelleme           : {s['AntivirusSignatureLastUpdated']}")
    print(f"  Urun surumu               : {s['AMProductVersion']}")
    print("AYARLAR")
    print(f"  Bulut koruma (MAPS)       : {defender.MAPS_LABELS.get(p['MAPSReporting'], p['MAPSReporting'])}")
    print(f"  PUA koruma                : {defender.ON_OFF_LABELS.get(p['PUAProtection'], p['PUAProtection'])}")
    print(f"  Denetimli klasor erisimi  : {defender.CFA_LABELS.get(p['EnableControlledFolderAccess'], p['EnableControlledFolderAccess'])}")
    print(f"  Ag korumasi               : {defender.ON_OFF_LABELS.get(p['EnableNetworkProtection'], p['EnableNetworkProtection'])}")
    if st.tamper_protected:
        print("\nNot: Tamper Protection acik; koruma ayarlari programatik degistirilemez.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="auxy", description="AuxySecurity")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="Defender durumunu goster").set_defaults(func=cmd_status)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
