"""Komut satiri girisi: python -m auxy <komut>"""

from __future__ import annotations

import argparse
import json
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
    from auxy.core import crashlog
    from auxy.gui.app import run  # gec import: CLI komutlari GUI kutuphanesini yuklemesin

    crashlog.install("pencere")

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


def _report(args, ok: bool, message: str, changed: bool = False, data=None) -> None:
    """GUI/tray'in yukseltilmis sureci icin sonucu dosyaya yazar (yalnizca izinli yol)."""
    if getattr(args, "result", None):
        try:
            actions.write_result(args.result, ok, message, changed, data)
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


def _ask_password(confirm: bool) -> str:
    import getpass

    pw = getpass.getpass("Parola: ")
    if confirm and getpass.getpass("Parola (tekrar): ") != pw:
        raise AuxyError("Parolalar uyuşmuyor.")
    return pw


def cmd_vault(args) -> int:
    from auxy.core import vault as vaultmod
    from auxy.core.vault import Vault

    targets = args.target or []
    try:
        if args.action == "import-key":  # kasa anahtari kayipsa da calisabilmeli: Vault.default() ACILMAZ
            if not targets:
                print("HATA: yedek dosyası ver: auxy vault import-key <dosya>", file=sys.stderr)
                return 2
            print(vaultmod.import_key_file(targets[0], _ask_password(confirm=False)))
            return 0
        vault = Vault.default()
        if args.action == "export-key":
            if not targets:
                print("HATA: hedef dosya ver: auxy vault export-key <dosya> (USB gibi veri dizini DIŞINDA)", file=sys.stderr)
                return 2
            out = vault.export_key_file(targets[0], _ask_password(confirm=True))
            print(f"Anahtar yedeği yazıldı: {out}\nBu dosya + parola olmadan kasa, Windows profili değişirse açılamaz; güvenli bir yerde sakla.")
            return 0
        if args.action == "add":
            if not targets:
                print("HATA: dosya yolu ver: auxy vault add <yol> [<yol> ...]", file=sys.stderr)
                return 2
            added, errors = vault.add_many(targets, args.reason)
            for item in added:
                print(f"Kasaya alındı: {item.name}  (id {item.id[:8]}, {item.size} bayt, sha256 {item.sha256[:16]}…)")
            for err in errors:
                print(f"HATA: {err}", file=sys.stderr)
            return 1 if errors else 0
        elif args.action == "list":
            items = vault.list()
            if not items:
                print("Kasa boş.")
            for i in items:
                print(f"{i.id[:8]}  {i.quarantined_at}  {i.size:>10} B  {i.original_path}  [{i.reason}]")
        else:
            if not targets:
                print(f"HATA: kayıt id'si ver: auxy vault {args.action} <id>", file=sys.stderr)
                return 2
            item = _find_vault_item(vault, targets[0])
            if args.action == "restore":
                out = vault.restore(item.id, args.to, args.overwrite)
                print(f"Geri yüklendi: {out}")
            else:  # delete
                if not args.yes:
                    print("HATA: kalıcı silme için --yes ekle (geri alınamaz).", file=sys.stderr)
                    return 2
                vault.delete(item.id)
                print(f"Kalıcı olarak silindi: {item.name}")
    except AuxyError as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 1
    return 0


def _find_vault_item(vault, prefix: str):
    matches = [i for i in vault.list() if i.id.startswith(prefix)]
    if len(matches) != 1:
        raise AuxyError(f"'{prefix}' ile eşleşen {len(matches)} kayıt var; tam id'yi (en az 8 karakter) ver.")
    return matches[0]


def _helper_guard(args, needs_admin: bool = True) -> bool:
    """Yukseltilmis yardimci modunda (--result) hala yonetici degilsek, sonsuz UAC dongusunu engelle."""
    if getattr(args, "result", None) and needs_admin and not system.is_admin():
        _report(args, False, "Yönetici yetkisi alınamadı.")
        return False
    return True


def cmd_winsec_get(_args) -> int:
    from auxy.core import winsec

    svc = winsec.WinSecService()
    values = svc.get_all()
    saved = backup.load()
    for key, s in winsec.WINSEC_SETTINGS.items():
        mark = "  (değiştirildi, 'auxy winsec-revert' ile geri alınır)" if winsec.BACKUP_PREFIX + key in saved else ""
        reboot = "  [yeniden başlatma gerekir]" if s.reboot else ""
        print(f"  {key:<17} {s.label:<46}: {values[key]}{reboot}{mark}")
    dev = winsec.read_device_security()
    yn = lambda v: "bilinmiyor" if v is None else ("evet" if v else "hayır")  # noqa: E731
    print(f"  Secure Boot: {yn(dev.secure_boot)} | Sanallaştırma tabanlı güvenlik: {yn(dev.vbs_running)} | "
          f"Bellek bütünlüğü çalışıyor: {yn(dev.hvci_running)}")
    for p in winsec.read_security_center():
        print(f"  {p.category}: {p.name}  (etkin: {yn(p.enabled)}, güncel: {yn(p.up_to_date)})")
    try:
        for name, state in winsec.read_exploit_protection().items():
            print(f"  Exploit protection {name}: {winsec.EXPLOIT_STATES.get(state, state)}")
    except AuxyError as exc:
        print(f"  Exploit protection okunamadı: {exc}")
    return 0


def cmd_winsec_set(args) -> int:
    from auxy.core import winsec

    s = winsec.WINSEC_SETTINGS.get(args.key)
    if s is None or args.value not in s.choices:
        print(f"HATA: geçersiz ayar/değer. Ayarlar: {', '.join(winsec.WINSEC_SETTINGS)}", file=sys.stderr)
        return 2
    if not _helper_guard(args, s.needs_admin):
        return 3
    res = actions.apply_winsec(args.key, args.value)
    _report(args, res.ok, res.message, res.changed)
    print(("" if res.ok else "HATA: ") + f"{args.key}: {res.message}", file=None if res.ok else sys.stderr)
    return 0 if res.ok else 1


def cmd_winsec_revert(args) -> int:
    from auxy.core import winsec

    if not system.is_admin():
        early = _elevate_or_fail(args, ["winsec-revert", *([args.key] if args.key else [])])
        if early is not None:
            return early
    try:
        results = winsec.WinSecService().revert(args.key)
    except AuxyError as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        _pause_if_requested(args)
        return 1
    for r in results or []:
        print(f"{r.key}: {r.old} -> {r.new}  (orijinale dönüldü)")
    if not results:
        print("Geri alınacak değişiklik yok.")
    _pause_if_requested(args)
    return 0


def cmd_exclusion(args) -> int:
    if not _helper_guard(args):
        return 3
    try:
        res = actions.exclusion_op(args.op, args.kind, args.value or "")
    except AuxyError as exc:
        _report(args, False, str(exc))
        print(f"HATA: {exc}", file=sys.stderr)
        return 1
    _report(args, res.ok, res.message, res.changed, res.data)
    if not res.ok:
        print(f"HATA: {res.message}", file=sys.stderr)
        return 1
    if args.op == "list":
        for kind, items in (res.data or {}).items():
            for it in items:
                print(f"  [{kind}] {it}")
        print(res.message)
    else:
        print(res.message)
    return 0


def cmd_tpm_info(args) -> int:
    if not _helper_guard(args):
        return 3
    res = actions.read_tpm()
    _report(args, res.ok, res.message, False, res.data)
    print(json.dumps(res.data, ensure_ascii=False) if res.ok else f"HATA: {res.message}")
    return 0 if res.ok else 1


def cmd_scan_file(args) -> int:
    """Explorer sag-tik menusu: dosyayi/klasoru tarar, sonucu kutuyla gosterir."""
    from auxy.core import scan

    try:
        res = scan.ScanManager().run(scan.CUSTOM, args.path)
        msg = f"{res.summary()}\n\n{args.path}"
    except AuxyError as exc:
        msg = str(exc)
    if args.no_dialog:
        print(msg)
    else:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, msg, "AuxySecurity", 0x40)  # bilgi simgesi
    return 0


def cmd_context_menu(args) -> int:
    from auxy.core import contextmenu

    if args.action == "install":
        contextmenu.install()
        print("Sağ tık menüsü eklendi (Windows 11: 'Daha fazla seçenek göster' altında).")
    elif args.action == "remove":
        contextmenu.remove()
        print("Sağ tık menüsü kaldırıldı.")
    else:
        print("Kurulu: " + ("evet" if contextmenu.is_installed() else "hayır"))
    return 0


def cmd_defender_quarantine(args) -> int:
    if not _helper_guard(args):
        return 3
    if args.op == "offline-scan" and not args.yes and not args.result:
        print("HATA: çevrimdışı tarama bilgisayarı YENİDEN BAŞLATIR; onaylamak için --yes ekle.", file=sys.stderr)
        return 2
    res = actions.defender_quarantine_op(args.op, args.path or "", args.to or "")
    _report(args, res.ok, res.message, res.changed, res.data)
    if not res.ok:
        print(f"HATA: {res.message}", file=sys.stderr)
        return 1
    if args.op == "list":
        for it in res.data or []:
            print(f"  [{it['threat']}] {it['path']}  ({it['quarantined_at']})")
    print(res.message)
    return 0


def cmd_firewall_rule(args) -> int:
    reading = args.op in ("list", "list-blocks")
    if not _helper_guard(args, needs_admin=not reading):
        return 3
    res = actions.firewall_op(args.op, args.value or "")
    _report(args, res.ok, res.message, res.changed, res.data)
    if not res.ok:
        print(f"HATA: {res.message}", file=sys.stderr)
        return 1
    for r in res.data or []:
        print(f"  {r['name']:<42} {r['profile']:<8} {r['display_name']}  -> {r['program']}")
    print(res.message)
    return 0


def cmd_netsvc(args) -> int:
    from auxy.core import netservices as ns

    if args.op == "status":
        g, w = ns.read_service(), ns.read_warp()
        if g.installed:
            safe = "" if ns.trusted_location(g.binary) else "  [UYARI: exe kullanıcının yazabildiği bir konumda]"
            print(f"GoodbyeDPI: {g.state} (başlangıç: {g.start_type}) {g.binary}{safe}")
        else:
            print("GoodbyeDPI: kurulu değil")
        if w.installed:
            print(f"WARP      : {w.status} ({w.reason}) kip={w.mode} protokol={w.protocol}")
        else:
            print("WARP      : kurulu değil")
        return 0
    admin_op = args.op in actions.NET_ADMIN_OPS
    if not _helper_guard(args, needs_admin=admin_op):
        return 3
    res = actions.net_op(args.op, args.value or "")
    _report(args, res.ok, res.message, res.changed)
    print(("" if res.ok else "HATA: ") + res.message, file=None if res.ok else sys.stderr)
    return 0 if res.ok else 1


def cmd_revert_all(args) -> int:
    if not _helper_guard(args):
        return 3
    res = actions.revert_all()
    _report(args, res.ok, res.message, res.changed)
    print(("" if res.ok else "HATA: ") + res.message, file=None if res.ok else sys.stderr)
    return 0 if res.ok else 1


def cmd_cleanup(args) -> int:
    from auxy.core import cleanup

    steps = cleanup.run(remove_data=args.remove_data, revert_settings=args.revert_settings,
                        force_vault=args.force_vault)
    for s in steps:
        print(f" {'✔' if s.ok else '✘'} {s.name:<20} {s.detail}")
    return 0 if all(s.ok for s in steps) else 1


def cmd_uninstall(args) -> int:
    """Kurulu surumu kaldirir (yonetici gerekir). Veri varsayilan olarak KORUNUR."""
    import ctypes

    from auxy.core import install

    dest = system.install_dir()
    if dest is None:
        print("HATA: 'uninstall' yalnızca kurulu (paketlenmiş) sürümde çalışır.", file=sys.stderr)
        return 2

    def box(text: str, flags: int) -> int:
        return ctypes.windll.user32.MessageBoxW(0, text, "AuxySecurity", flags)

    if not system.is_admin():
        extra = [a for a in ("--quiet", "--remove-data", "--force-vault") if getattr(args, a[2:].replace("-", "_"), False)]
        return 0 if system.relaunch_as_admin(["uninstall", *extra], windowless=True) else 1
    if not args.quiet and box("AuxySecurity kaldırılsın mı?\n\nKarantina kasan ve ayarların KORUNUR (silmek için "
                              "komut satırından --remove-data).", 0x24) != 6:  # MB_YESNO | MB_ICONQUESTION, IDYES=6
        return 1
    try:
        steps = install.uninstall(install.InstallOptions(dest=dest), remove_data=args.remove_data,
                                  force_vault=args.force_vault, log=lambda m: None)
    except Exception as exc:  # noqa: BLE001
        if not args.quiet:
            box(f"Kaldırma başarısız:\n{exc}", 0x10)
        print(f"HATA: {exc}", file=sys.stderr)
        return 1
    if not args.quiet:
        box("AuxySecurity kaldırıldı.\n\n" + "\n".join(f"• {s}" for s in steps), 0x40)
    print("\n".join(steps))
    return 0


def cmd_migrate_data(args) -> int:
    from auxy.core import migrate

    plan = migrate.pending_plan()
    if plan is None:
        print("Taşınacak eski veri yok.")
        return 0
    print(f"Eski veri: {plan.source}\nHedef    : {plan.target}")
    print("Kopyalanacak:", ", ".join(plan.to_copy) or "-")
    if plan.blocked:
        print("Hedefte zaten var (dokunulmaz):", ", ".join(plan.blocked))
    if not args.yes:
        print("Uygulamak için --yes ekle (eski veri SİLİNMEZ, kopyalanır).")
        return 0
    for line in migrate.migrate(plan):
        print(" -", line)
    return 0


def cmd_doctor(args) -> int:
    from auxy.core import doctor

    results = doctor.run_checks()
    if args.json:
        import json as _json

        print(_json.dumps([r.to_dict() for r in results], ensure_ascii=False, indent=2))
    else:
        print(doctor.format_report(results))
    return 1 if doctor.summarize(results)[2] else 0


def cmd_agent(_args) -> int:
    from auxy.core import crashlog
    from auxy.core.log import get_logger

    crashlog.install("ajan")
    from auxy.agent.tray import run

    try:
        return run()
    except Exception as exc:  # ajan beklenmedik sekilde coktu: nedeni gunluge yaz, cikis kodu != 0
        # (Gorev Zamanlayici "hata durumunda yeniden baslat" ayariyla ajani yeniden baslatir)
        get_logger().critical("AJAN COKTU", exc_info=(type(exc), exc, exc.__traceback__))
        return 1


def cmd_autostart(args) -> int:
    from auxy.core import autostart

    if args.action == "status":
        st = autostart.status()
        print("Kurulu: " + ("evet" if st.installed else "hayir"))
        if st.installed:
            print(f"Son calisma sonucu: {st.last_result}")
        return 0
    if not _helper_guard(args):
        return 3
    tail = ["autostart", args.action]
    early = _elevate_or_fail(args, tail)
    if early is not None:
        return early
    if args.action == "install":
        from auxy.core import hardening

        risk = hardening.install_location_risk()
        if risk.risky:
            print("UYARI: " + risk.detail + "\n       " + "; ".join(risk.paths), file=sys.stderr)
    res = actions.autostart_op(args.action)  # yonetici oldugumuz icin dogrudan calisir
    _report(args, res.ok, res.message, res.changed)
    print(("" if res.ok else "HATA: ") + res.message, file=None if res.ok else sys.stderr)
    _pause_if_requested(args)
    return 0 if res.ok else 1


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


# Yukseltilmis YARDIMCI modunda (--result verilmis) calistirilmasina izin verilen alt komutlar. Yukseltme gerektiren
# her islem buradan gecer; digerleri (gui, agent, scan, vault ...) yukseltilmis surecte calismayi REDDEDER.
ELEVATED_ALLOWED = frozenset({
    "set", "scan-cancel", "winsec-set", "exclusion", "tpm-info", "autostart", "defender-quarantine",
    "firewall-rule", "revert-all", "netsvc",
})


def _enforce_elevated_allowlist(args) -> bool:
    """Yukseltilmis (yonetici) yardimci surecte yalnizca izinli alt komutlar calisir (UAC onayinin kapsamini daraltir)."""
    if getattr(args, "result", None) and system.is_admin() and args.command not in ELEVATED_ALLOWED:
        print(f"HATA: '{args.command}' yukseltilmis modda calistirilamaz.", file=sys.stderr)
        return False
    return True


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

    p_vault = sub.add_parser("vault", help="Karantina kasası")
    p_vault.add_argument("action", choices=["add", "list", "restore", "delete", "export-key", "import-key"])
    p_vault.add_argument("target", nargs="*", help="add: dosya yolları; restore/delete: kayıt id'si; "
                                                   "export-key/import-key: yedek dosyası")
    p_vault.add_argument("--reason", default="Elle eklendi")
    p_vault.add_argument("--to", help="restore: farklı hedef yol")
    p_vault.add_argument("--overwrite", action="store_true")
    p_vault.add_argument("--yes", action="store_true", help="delete: onay")
    p_vault.set_defaults(func=cmd_vault)

    sub.add_parser("winsec-get", help="Güvenlik duvarı, SmartScreen, cihaz güvenliği durumu").set_defaults(
        func=cmd_winsec_get)
    p_ws = sub.add_parser("winsec-set", help="Windows güvenlik ayarını değiştir (gerekirse UAC)")
    p_ws.add_argument("key")
    p_ws.add_argument("value")
    p_ws.add_argument("--result", help=argparse.SUPPRESS)
    p_ws.set_defaults(func=cmd_winsec_set)
    p_wr = sub.add_parser("winsec-revert", help="Windows güvenlik ayarını orijinaline döndür")
    p_wr.add_argument("key", nargs="?")
    p_wr.add_argument("--elevate", action="store_true")
    p_wr.add_argument("--pause", action="store_true", help=argparse.SUPPRESS)
    p_wr.set_defaults(func=cmd_winsec_revert)
    p_ex = sub.add_parser("exclusion", help="Defender dışlamaları (UAC ister)")
    p_ex.add_argument("op", choices=["list", "add", "remove"])
    p_ex.add_argument("kind", choices=["path", "extension", "process"])
    p_ex.add_argument("value", nargs="?")
    p_ex.add_argument("--result", help=argparse.SUPPRESS)
    p_ex.set_defaults(func=cmd_exclusion)
    p_tp = sub.add_parser("tpm-info", help="TPM durumu (UAC ister)")
    p_tp.add_argument("--result", help=argparse.SUPPRESS)
    p_tp.set_defaults(func=cmd_tpm_info)

    p_sf = sub.add_parser("scan-file", help="Bir dosya/klasörü tara ve sonucu kutuyla göster")
    p_sf.add_argument("path")
    p_sf.add_argument("--no-dialog", action="store_true", help=argparse.SUPPRESS)
    p_sf.set_defaults(func=cmd_scan_file)

    p_cm = sub.add_parser("context-menu", help="Explorer sağ tık menüsü 'Auxy ile tara'")
    p_cm.add_argument("action", choices=["install", "remove", "status"])
    p_cm.set_defaults(func=cmd_context_menu)

    p_dq = sub.add_parser("defender-quarantine", help="Defender karantinası / etkin tehdit temizleme / çevrimdışı tarama (UAC)")
    p_dq.add_argument("op", choices=["list", "restore", "clean", "offline-scan"])
    p_dq.add_argument("path", nargs="?", help="restore: geri yüklenecek dosyanın yolu")
    p_dq.add_argument("--to", help="restore: farklı hedef klasör")
    p_dq.add_argument("--yes", action="store_true", help="offline-scan: yeniden başlatmayı onayla")
    p_dq.add_argument("--result", help=argparse.SUPPRESS)
    p_dq.set_defaults(func=cmd_defender_quarantine)

    p_ns = sub.add_parser("netsvc", help="Ağ araçları: GoodbyeDPI hizmeti ve Cloudflare WARP (durum yönetici istemez)")
    p_ns.add_argument("op", choices=["status", *actions.NET_ADMIN_OPS, *actions.NET_WARP_OPS])
    p_ns.add_argument("value", nargs="?", help="warp-protocol: MASQUE|WireGuard; warp-mode: warp|warp+doh|doh|...")
    p_ns.add_argument("--result", help=argparse.SUPPRESS)
    p_ns.set_defaults(func=cmd_netsvc)

    p_fr = sub.add_parser("firewall-rule", help="Güvenlik duvarı kuralları (listeleme yönetici istemez)")
    p_fr.add_argument("op", choices=["list", "list-blocks", "disable", "enable", "block", "unblock"])
    p_fr.add_argument("value", nargs="?", help="disable/enable: kural adı; block/unblock: program yolu (unblock: kural adı da olur)")
    p_fr.add_argument("--result", help=argparse.SUPPRESS)
    p_fr.set_defaults(func=cmd_firewall_rule)

    p_ra = sub.add_parser("revert-all", help="Tüm ayarları orijinaline döndür (UAC)")
    p_ra.add_argument("--result", help=argparse.SUPPRESS)
    p_ra.set_defaults(func=cmd_revert_all)

    p_cl = sub.add_parser("cleanup", help="Kaldırma temizliği: sağ tık menüsü, başlangıç görevi (veriye dokunmaz)")
    p_cl.add_argument("--revert-settings", action="store_true", help="değiştirilen ayarları orijinaline döndür (UAC)")
    p_cl.add_argument("--remove-data", action="store_true", help="veri dizinini (günlük, yedek, KASA) sil")
    p_cl.add_argument("--force-vault", action="store_true", help="kasada dosya varken de veriyi sil (kalıcı kayıp!)")
    p_cl.set_defaults(func=cmd_cleanup)

    p_un = sub.add_parser("uninstall", help="Kurulu sürümü kaldır (yönetici; veri varsayılan olarak korunur)")
    p_un.add_argument("--quiet", action="store_true", help="onay/bilgi kutusu gösterme")
    p_un.add_argument("--remove-data", action="store_true", help="veri dizinini de sil (kasada dosya varsa reddeder)")
    p_un.add_argument("--force-vault", action="store_true", help="kasada dosya varken de veriyi sil (kalıcı kayıp!)")
    p_un.set_defaults(func=cmd_uninstall)

    p_mg = sub.add_parser("migrate-data", help="Store Python'un sanallaştırılmış eski veri dizininden gerçek dizine kopyala")
    p_mg.add_argument("--yes", action="store_true", help="kopyalamayı uygula (eski veri silinmez)")
    p_mg.set_defaults(func=cmd_migrate_data)

    p_doc = sub.add_parser("doctor", help="Ortam ve kurulum tanısı (hiçbir şeyi değiştirmez)")
    p_doc.add_argument("--json", action="store_true", help="makine okunur çıktı")
    p_doc.set_defaults(func=cmd_doctor)

    sub.add_parser("agent", help="Tray ajanini baslat").set_defaults(func=cmd_agent)

    p_auto = sub.add_parser("autostart", help="Oturum acilisinda baslatma gorevi")
    p_auto.add_argument("action", choices=["install", "remove", "status"])
    p_auto.add_argument("--elevate", action="store_true")
    p_auto.add_argument("--pause", action="store_true", help=argparse.SUPPRESS)
    p_auto.add_argument("--result", help=argparse.SUPPRESS)
    p_auto.set_defaults(func=cmd_autostart)

    p_rev = sub.add_parser("revert", help="Ayari orijinal degerine dondur (yonetici)")
    p_rev.add_argument("key", nargs="?", choices=list(SETTINGS))
    p_rev.add_argument("--elevate", action="store_true")
    p_rev.add_argument("--pause", action="store_true", help=argparse.SUPPRESS)
    p_rev.set_defaults(func=cmd_revert)

    if argv is None and len(sys.argv) == 1 and system.is_frozen():
        argv = ["gui"]  # paketlenmis penceresiz exe: cift tiklayinca pencere acilir
    args = parser.parse_args(argv)
    if not _enforce_elevated_allowlist(args):
        return 4
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
