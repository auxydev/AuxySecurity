"""Komut satiri girisi: python -m auxy <komut>"""

from __future__ import annotations

import argparse
import sys

from auxy import __version__
from auxy.core import actions, backup, defender, system
from auxy.core.service import AuxyError, DefenderService
from auxy.core.settings import SETTINGS


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


def cmd_gui(_args) -> int:
    from auxy.gui.app import run  # gec import: CLI komutlari GUI kutuphanesini yuklemesin

    run()
    return 0


def cmd_get(args) -> int:
    values = DefenderService().get_all()
    saved = backup.load()
    if args.key:
        if args.key not in SETTINGS:
            print(f"HATA: Bilinmeyen ayar. Gecerli: {', '.join(SETTINGS)}", file=sys.stderr)
            return 2
        print(values[args.key])
        return 0
    for key, setting in SETTINGS.items():
        mark = "  (degistirildi, 'auxy revert' ile geri alinir)" if key in saved else ""
        print(f"  {key:<8} {setting.label:<32}: {values[key]}{mark}")
    return 0


def _elevate_or_fail(args, argv_tail: list[str]) -> int | None:
    """Yonetici degilse: --elevate varsa UAC ile yeniden baslat, yoksa hata ver."""
    if system.is_admin():
        return None
    if getattr(args, "elevate", False):
        ok = system.relaunch_as_admin([*argv_tail, "--pause"])  # gorunur konsol: sonucu goster
        print("Yonetici penceresi acildi." if ok else "UAC reddedildi veya acilamadi.")
        return 0 if ok else 1
    print("HATA: Yonetici yetkisi gerekli. Yonetici terminalinden calistir "
          "ya da komuta --elevate ekle.", file=sys.stderr)
    return 3


def _pause_if_requested(args) -> None:
    if getattr(args, "pause", False):
        input("\nKapatmak icin Enter'a bas...")


def _report(args, ok: bool, message: str, changed: bool = False) -> None:
    """GUI/tray'in yukseltilmis sureci icin sonucu dosyaya yazar (yalnizca izinli yol)."""
    if getattr(args, "result", None):
        try:
            actions.write_result(args.result, ok, message, changed)
        except (OSError, ValueError):
            pass


def cmd_scan(args) -> int:
    from auxy.core import scan

    kinds = {"quick": scan.QUICK, "full": scan.FULL, "custom": scan.CUSTOM}
    if args.kind == "custom" and not args.path:
        print("HATA: özel tarama için yol ver: auxy scan custom <yol>", file=sys.stderr)
        return 2
    print(f"{scan.TYPE_NAMES[kinds[args.kind]]} başlıyor… (bitene kadar bekler)")
    try:
        res = scan.ScanManager().run(kinds[args.kind], args.path)
    except AuxyError as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 1
    print(f"{res.summary()}  ({scan.format_duration(res.seconds)})")
    return 0 if res.status == scan.COMPLETED else 1


def cmd_scan_cancel(args) -> int:
    from auxy.core import scan

    res = actions.cancel_scan() if system.is_admin() else None
    if res is None:
        print("HATA: yönetici yetkisi gerekli.", file=sys.stderr)
        return 3
    _report(args, res.ok, res.message)
    print(res.message)
    return 0 if res.ok else 1


def cmd_threats(_args) -> int:
    from auxy.core import threats

    items = threats.read_detections()
    if not items:
        print("Kayıtlı tehdit tespiti yok.")
        return 0
    for d in items:
        when = d.time.strftime("%Y-%m-%d %H:%M") if d.time else "?"
        state = "işlem uygulandı" if d.handled else "beklemede"
        print(f"{when}  {d.severity:<11} {d.name}  [{state}]")
        for p in d.paths:
            print(f"    {p}")
    return 0


def cmd_update_signatures(_args) -> int:
    from auxy.core import scan

    print("İmzalar güncelleniyor… (~20 sn)")
    ok, msg = scan.update_signatures()
    print(msg)
    return 0 if ok else 1


def cmd_agent(_args) -> int:
    from auxy.agent.tray import run

    return run()


def cmd_autostart(args) -> int:
    from auxy.core import autostart

    if args.action == "status":
        st = autostart.status()
        print("Kurulu: " + ("evet" if st.installed else "hayir"))
        if st.installed:
            print(f"Son calisma sonucu: {st.last_result}")
        return 0
    tail = ["autostart", args.action]
    early = _elevate_or_fail(args, tail)
    if early is not None:
        return early
    try:
        autostart.install() if args.action == "install" else autostart.remove()
    except AuxyError as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        _pause_if_requested(args)
        return 1
    print("Baslangic gorevi " + ("kuruldu." if args.action == "install" else "kaldirildi."))
    _pause_if_requested(args)
    return 0


def cmd_set(args) -> int:
    allowed = SETTINGS[args.key].choices
    if args.value not in allowed:
        print(f"HATA: {args.key} icin gecersiz deger {args.value!r}. "
              f"Gecerli: {', '.join(allowed)}", file=sys.stderr)
        return 2
    early = _elevate_or_fail(args, ["set", args.key, args.value])
    if early is not None:
        return early
    try:
        res = DefenderService().set(args.key, args.value)
    except AuxyError as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        _report(args, False, str(exc))
        _pause_if_requested(args)
        return 1
    _report(args, True, f"{res.old} → {res.new}" if res.changed else f"zaten {res.new}",
            res.changed)
    if res.changed:
        print(f"{res.key}: {res.old} -> {res.new}   (geri almak icin: auxy revert {res.key})")
    else:
        print(f"{res.key}: zaten {res.new}, degisiklik yok.")
    _pause_if_requested(args)
    return 0


def cmd_revert(args) -> int:
    tail = ["revert", *([args.key] if args.key else [])]
    early = _elevate_or_fail(args, tail)
    if early is not None:
        return early
    try:
        results = DefenderService().revert(args.key)
    except AuxyError as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        _pause_if_requested(args)
        return 1
    if not results:
        print("Geri alinacak degisiklik yok.")
    for r in results:
        print(f"{r.key}: {r.old} -> {r.new}  (orijinale donuldu)")
    _pause_if_requested(args)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="auxy", description="AuxySecurity")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Defender durumunu goster").set_defaults(func=cmd_status)

    sub.add_parser("gui", help="Pencereyi ac").set_defaults(func=cmd_gui)

    p_get = sub.add_parser("get", help="Yonetilen ayarlari goster")
    p_get.add_argument("key", nargs="?", help=f"({', '.join(SETTINGS)})")
    p_get.set_defaults(func=cmd_get)

    p_set = sub.add_parser("set", help="Bir ayari degistir (yonetici)")
    p_set.add_argument("key", choices=list(SETTINGS))
    p_set.add_argument("value", help="on/off, maps icin off/basic/advanced, digerleri on/off/audit")
    p_set.add_argument("--elevate", action="store_true", help="UAC ile yonetici olarak calistir")
    p_set.add_argument("--pause", action="store_true", help=argparse.SUPPRESS)
    p_set.add_argument("--result", help=argparse.SUPPRESS)
    p_set.set_defaults(func=cmd_set)

    p_scan = sub.add_parser("scan", help="Tarama başlat (bitene kadar bekler)")
    p_scan.add_argument("kind", choices=["quick", "full", "custom"])
    p_scan.add_argument("path", nargs="?", help="özel tarama için dosya/klasör")
    p_scan.set_defaults(func=cmd_scan)

    p_sc = sub.add_parser("scan-cancel", help=argparse.SUPPRESS)
    p_sc.add_argument("--result", help=argparse.SUPPRESS)
    p_sc.set_defaults(func=cmd_scan_cancel)

    sub.add_parser("threats", help="Tehdit tespitlerini listele").set_defaults(func=cmd_threats)
    sub.add_parser("update-signatures", help="Virüs imzalarını güncelle").set_defaults(
        func=cmd_update_signatures)

    sub.add_parser("agent", help="Tray ajanini baslat").set_defaults(func=cmd_agent)

    p_auto = sub.add_parser("autostart", help="Oturum acilisinda baslatma gorevi")
    p_auto.add_argument("action", choices=["install", "remove", "status"])
    p_auto.add_argument("--elevate", action="store_true")
    p_auto.add_argument("--pause", action="store_true", help=argparse.SUPPRESS)
    p_auto.set_defaults(func=cmd_autostart)

    p_rev = sub.add_parser("revert", help="Ayari orijinal degerine dondur (yonetici)")
    p_rev.add_argument("key", nargs="?", choices=list(SETTINGS))
    p_rev.add_argument("--elevate", action="store_true")
    p_rev.add_argument("--pause", action="store_true", help=argparse.SUPPRESS)
    p_rev.set_defaults(func=cmd_revert)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
