"""GUI ve tray'in ortak eylem katmani: yetki yoksa UAC ister, sonucu geri dondurur.

Yukseltilmis islemler `python -m auxy <komut> ... --result <dosya>` olarak gizli pencerede,
UAC ile calisir; sonuc (JSON) yalnizca %TEMP%'te `auxy-result-` onekli dosyaya yazilir.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from auxy.core import system
from auxy.core.service import AuxyError, DefenderService

RESULT_PREFIX = "auxy-result-"


@dataclass(frozen=True)
class ActionResult:
    ok: bool
    message: str
    changed: bool = False
    data: object = None


def result_path_allowed(path: str) -> bool:
    """Yukseltilmis surecin yazacagi sonuc dosyasi yalnizca gecici dizinde, bilinen on ekle olabilir."""
    p = Path(path).resolve()
    return p.parent == Path(tempfile.gettempdir()).resolve() and p.name.startswith(RESULT_PREFIX)


def write_result(path: str, ok: bool, message: str, changed: bool = False, data=None) -> None:
    if not result_path_allowed(path):
        raise ValueError("Gecersiz sonuc dosyasi yolu")
    payload = json.dumps({"ok": ok, "message": message, "changed": changed, "data": data}).encode("utf-8")
    from auxy.core import hardening

    with hardening.open_result_file(path) as f:  # baglanti/hardlink/TOCTOU saldirilarina karsi guvenli acis
        f.write(payload)


def run_elevated(args: list[str], denied_message: str = "Yönetici izni verilmedi.",
                 timeout_s: float = 120) -> ActionResult:
    """`auxy <args> --result <tmp>` komutunu UAC ile calistirip sonucunu okur."""
    fd, tmp = tempfile.mkstemp(prefix=RESULT_PREFIX, suffix=".json")
    os.close(fd)
    try:
        code = system.run_elevated_and_wait([*args, "--result", tmp], timeout_s)
        if code is None:
            return ActionResult(False, denied_message)
        try:
            data = json.loads(Path(tmp).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ActionResult(False, f"İşlem sonucu okunamadı (çıkış kodu {code}).")
        return ActionResult(bool(data["ok"]), str(data["message"]), bool(data.get("changed")),
                            data.get("data"))
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _describe(res) -> ActionResult:
    if res.changed:
        return ActionResult(True, f"{res.old} → {res.new}", True)
    return ActionResult(True, f"zaten {res.new}", False)


def cancel_scan() -> ActionResult:
    """Calisan taramayi iptal eder (yonetici gerekir; degilsek UAC ister)."""
    from auxy.core import scan

    if system.is_admin():
        code, out = scan.cancel_scan_command()
        ok = code == 0
        return ActionResult(ok, "Tarama iptal edildi." if ok else f"İptal edilemedi: {out.strip()[-200:]}")
    return run_elevated(["scan-cancel"], "Yönetici izni verilmedi; tarama iptal edilemedi.")


def apply_setting(key: str, value: str) -> ActionResult:
    """Defender ayarini uygular. Yonetici degilsek UAC penceresi acar (gizli yardimci surec)."""
    if system.is_admin():
        try:
            return _describe(DefenderService().set(key, value))
        except AuxyError as exc:
            return ActionResult(False, str(exc))
    return run_elevated(["set", key, value])


def apply_winsec(key: str, value: str) -> ActionResult:
    """Windows guvenlik ayari (guvenlik duvari, SmartScreen, Memory Integrity). Gerekirse UAC."""
    from auxy.core import winsec

    setting = winsec.WINSEC_SETTINGS.get(key)
    if setting is not None and not setting.needs_admin or system.is_admin():
        try:
            res = winsec.WinSecService().set(key, value)
        except AuxyError as exc:
            return ActionResult(False, str(exc))
        msg = f"{res.old} → {res.new}" if res.changed else f"zaten {res.new}"
        if res.changed and setting is not None and setting.reboot:
            msg += " (yeniden başlatma gerekir)"
        return ActionResult(True, msg, res.changed)
    return run_elevated(["winsec-set", key, value])


def autostart_op(op: str) -> ActionResult:
    """Oturum acilisinda baslatma gorevi: install / remove. Yonetici gerekir (degilsek UAC)."""
    from auxy.core import autostart

    if op not in ("install", "remove"):
        return ActionResult(False, f"Geçersiz işlem: {op!r}")
    if system.is_admin():
        try:
            autostart.install() if op == "install" else autostart.remove()
        except AuxyError as exc:
            return ActionResult(False, str(exc))
        return ActionResult(True, "Başlangıç görevi kuruldu." if op == "install" else "Başlangıç görevi kaldırıldı.", True)
    return run_elevated(["autostart", op])


def revert_all() -> ActionResult:
    """Defender + Windows guvenlik ayarlarinin HEPSINI orijinal degerlerine dondurur (yonetici; degilsek UAC)."""
    from auxy.core import winsec

    if system.is_admin():
        parts, ok = [], True
        try:
            parts += [f"{r.key}: {r.old}→{r.new}" for r in DefenderService().revert()]
        except AuxyError as exc:
            ok = False
            parts.append(f"Defender: {exc}")
        try:
            parts += [f"{r.key}: {r.old}→{r.new}" for r in winsec.WinSecService().revert()]
        except AuxyError as exc:
            ok = False
            parts.append(f"Windows güvenlik: {exc}")
        return ActionResult(ok, "; ".join(parts) or "Geri alınacak değişiklik yok.", bool(parts))
    return run_elevated(["revert-all"])


def firewall_op(op: str, value: str = "") -> ActionResult:
    """Guvenlik duvari kurallari. list / list-blocks yonetici GEREKTIRMEZ; digerleri (UAC)."""
    from auxy.core import firewall as fw

    if op not in fw.OPS:
        return ActionResult(False, f"Geçersiz işlem: {op!r}")
    try:
        if op in ("list", "list-blocks"):
            return fw.run_op(op)
        if op == "block":
            fw.validate_program(value)  # gecersiz girdi UAC'ye hic gitmesin
        elif op == "unblock":
            fw.unblock_name_or_path_check(value)
        else:
            fw._clean_name(value)
        if system.is_admin():
            return fw.run_op(op, value)
    except AuxyError as exc:
        return ActionResult(False, str(exc))
    return run_elevated(["firewall-rule", op, value])


def defender_quarantine_op(op: str, path: str = "", to_dir: str = "") -> ActionResult:
    """Defender karantinasi / tehdit temizleme / cevrimdisi tarama. Hepsi yonetici gerektirir (degilsek UAC).

    op: list | restore | clean | offline-scan.  offline-scan bilgisayari YENIDEN BASLATIR: cagiran onay almalidir.
    """
    from auxy.core import defender_quarantine as dq

    if op not in ("list", "restore", "clean", "offline-scan"):
        return ActionResult(False, f"Geçersiz işlem: {op!r}")
    try:
        if op == "restore":
            dq.validate_restore_path(path)  # gecersiz girdi UAC'ye hic gitmesin
        if system.is_admin():
            return dq.run_op(op, path, to_dir)
    except AuxyError as exc:
        return ActionResult(False, str(exc))
    args = ["defender-quarantine", op]
    if op == "restore":
        args.append(path)
        if to_dir:
            args += ["--to", to_dir]
    return run_elevated(args, timeout_s=300 if op == "offline-scan" else 120)


def exclusion_op(op: str, kind: str, value: str = "") -> ActionResult:
    """Defender dislamalari (list/add/remove). Hepsi yonetici gerektirir (okuma dahil)."""
    from auxy.core import exclusions

    if system.is_admin():
        try:
            return exclusions.run_op(op, kind, value)
        except AuxyError as exc:
            return ActionResult(False, str(exc))
    exclusions.validate_op(op, kind, value)  # gecersiz girdi UAC'ye hic gitmesin
    return run_elevated(["exclusion", op, kind, value])


NET_ADMIN_OPS = ("gdpi-start", "gdpi-stop", "gdpi-auto", "gdpi-manual", "gdpi-install", "gdpi-remove")
NET_WARP_OPS = ("warp-connect", "warp-disconnect", "warp-protocol", "warp-mode")


def run_net_op(op: str, value: str = "") -> ActionResult:
    """Ag araci islemini bu surecte yapar (GoodbyeDPI islemleri yonetici ister)."""
    from auxy.core import netservices as ns

    try:
        if op == "gdpi-start":
            res = ns.service_control("start")
        elif op == "gdpi-stop":
            res = ns.service_control("stop")
        elif op == "gdpi-auto":
            res = ns.set_start_type("auto")
        elif op == "gdpi-manual":
            res = ns.set_start_type("manual")
        elif op == "gdpi-install":
            tools = ns.bundled_tools_dir()
            if tools is None:
                return ActionResult(False, "Paketlenmiş GoodbyeDPI bulunamadı (yalnızca kurulu sürümde var).")
            res = ns.install_service(tools)
        elif op == "gdpi-remove":
            res = ns.remove_service()
        elif op == "warp-connect":
            res = ns.warp_op("connect")
        elif op == "warp-disconnect":
            res = ns.warp_op("disconnect")
        elif op == "warp-protocol":
            res = ns.warp_op("protocol", value)
        elif op == "warp-mode":
            res = ns.warp_op("mode", value)
        else:
            return ActionResult(False, f"Geçersiz işlem: {op!r}")
    except AuxyError as exc:
        return ActionResult(False, str(exc))
    return ActionResult(res.ok, res.message, res.changed)


def net_op(op: str, value: str = "") -> ActionResult:
    """Ag araclari (GoodbyeDPI / WARP). WARP islemleri yonetici GEREKTIRMEZ; GoodbyeDPI hizmeti islemleri gerektirir (UAC)."""
    if op not in NET_ADMIN_OPS + NET_WARP_OPS:
        return ActionResult(False, f"Geçersiz işlem: {op!r}")
    if op in NET_WARP_OPS or system.is_admin():
        return run_net_op(op, value)
    return run_elevated(["netsvc", op, value] if value else ["netsvc", op])


DNS_ADMIN_OPS = ("apply", "reset", "flush", "enforce")
PRIVACY_ADMIN_OPS = ("mac-on", "mac-off")


def run_dns_op(op: str, value: str = "", adapters: list[int] | None = None, doh: bool = False,
               strict: bool = False) -> ActionResult:
    """DNS islemini bu surecte yapar (yonetici gerekir)."""
    from auxy.core import dns

    try:
        if op == "apply":
            return ActionResult(True, dns.apply(value, list(adapters or []), doh, strict), True)
        if op == "reset":
            return ActionResult(True, dns.reset(list(adapters or [])), True)
        if op == "flush":
            return ActionResult(True, dns.flush_cache(), True)
        if op == "enforce":
            from auxy.core import dnsscope

            done = dnsscope.enforce()
            return ActionResult(True, " ".join(done) or "Ağa bağlı DNS kuralı: değişiklik gerekmedi.", bool(done))
    except AuxyError as exc:
        return ActionResult(False, str(exc))
    return ActionResult(False, f"Geçersiz işlem: {op!r}")


def dns_op(op: str, value: str = "", adapters: list[int] | None = None, doh: bool = False,
           strict: bool = False) -> ActionResult:
    """DNS atama / sifirlama / onbellek temizleme. Yonetici gerekir (degilsek UAC). Gecersiz girdi UAC'ye gitmez."""
    from auxy.core import dns

    if op not in DNS_ADMIN_OPS:
        return ActionResult(False, f"Geçersiz işlem: {op!r}")
    try:
        if op == "apply":
            _v4, _v6, template, _n = dns.resolve_servers(value)  # girdiyi UAC'den ONCE doğrula
            if doh and not template:
                return ActionResult(False, "Bu DNS için şifreli (DoH) adres bilinmiyor.")
        if op in ("apply", "reset") and not adapters:
            return ActionResult(False, "En az bir ağ bağdaştırıcısı seç.")
    except AuxyError as exc:
        return ActionResult(False, str(exc))
    if system.is_admin():
        return run_dns_op(op, value, adapters, doh, strict)
    args = ["dns", op] + ([value] if value else [])
    if adapters:
        args += ["--adapters", ",".join(str(int(a)) for a in adapters)]
    if doh:
        args.append("--doh")
    if strict:
        args.append("--strict")
    return run_elevated(args, timeout_s=120)


def run_privacy_op(op: str, value: str = "") -> ActionResult:
    from auxy.core import privacy

    try:
        if op in ("mac-on", "mac-off"):
            return ActionResult(True, privacy.set_mac_randomization(op == "mac-on", value), True)
        key, _, state = op.rpartition("-")
        if key in privacy.FLAGS and state in ("on", "off"):
            return ActionResult(True, privacy.set_flag(key, state == "on"), True)
    except AuxyError as exc:
        return ActionResult(False, str(exc))
    return ActionResult(False, f"Geçersiz işlem: {op!r}")


def privacy_op(op: str, value: str = "") -> ActionResult:
    """Gizlilik ayarlari. Reklam kimligi/kisisellestirme (HKCU) yonetici ISTEMEZ; MAC rastgelelestirme ister (UAC)."""
    if op in PRIVACY_ADMIN_OPS and not system.is_admin():
        if not value or any(c in value for c in '"\r\n'):
            return ActionResult(False, "Geçersiz arayüz adı.")
        return run_elevated(["privacy", op, value])
    return run_privacy_op(op, value)


def _validate_preset_admin(dns_value: str, adapters, macs_on, macs_off, fw_on) -> None:
    from auxy.core import dns as dnsmod
    from auxy.core import presets

    if dns_value and dns_value != "__reset__":
        dnsmod.resolve_servers(dns_value)
    if dns_value and not adapters:
        raise AuxyError("En az bir ağ bağdaştırıcısı seç.")
    for name in [*macs_on, *macs_off]:
        if not name or any(c in name for c in '"\r\n'):
            raise AuxyError("Geçersiz arayüz adı.")
    for k in fw_on:
        if k not in presets.FW_KEYS:
            raise AuxyError(f"Geçersiz güvenlik duvarı anahtarı: {k!r}")


def run_preset_admin(dns: str = "", adapters=(), doh: bool = False, strict: bool = False, macs_on=(), macs_off=(),
                     fw_on=()) -> ActionResult:
    """Ön ayarın yönetici gerektiren adımları TEK süreçte (yönetici gerekir)."""
    from auxy.core import dns as dnsmod
    from auxy.core import privacy, winsec

    parts, ok = [], True
    try:
        if dns == "__reset__":
            parts.append(dnsmod.reset(list(adapters)))
        elif dns:
            parts.append(dnsmod.apply(dns, list(adapters), doh, strict))
    except AuxyError as exc:
        ok = False
        parts.append(f"DNS: {exc}")
    for name, on in [*[(n, True) for n in macs_on], *[(n, False) for n in macs_off]]:
        try:
            parts.append(privacy.set_mac_randomization(on, name))
        except AuxyError as exc:
            ok = False
            parts.append(f"MAC {name}: {exc}")
    for key in fw_on:
        try:
            winsec.WinSecService().set(key, "on")
            parts.append(f"güvenlik duvarı {key}: açık")
        except AuxyError as exc:
            ok = False
            parts.append(f"{key}: {exc}")
    return ActionResult(ok, "; ".join(parts) or "Yönetici adımı yok.", bool(parts))


def preset_admin(dns: str = "", adapters=(), doh: bool = False, strict: bool = False, macs_on=(), macs_off=(),
                 fw_on=()) -> ActionResult:
    """Ön ayarın yönetici adımlarını TEK UAC isteminde çalıştırır. Girdiler UAC'den ÖNCE doğrulanır."""
    try:
        _validate_preset_admin(dns, list(adapters), list(macs_on), list(macs_off), list(fw_on))
    except AuxyError as exc:
        return ActionResult(False, str(exc))
    if system.is_admin():
        return run_preset_admin(dns, adapters, doh, strict, macs_on, macs_off, fw_on)
    args = ["presetadmin"]
    if dns:
        args += ["--dns", dns, "--adapters", ",".join(str(int(a)) for a in adapters)]
    if doh:
        args.append("--doh")
    if strict:
        args.append("--strict")
    for n in macs_on:
        args += ["--mac-on", n]
    for n in macs_off:
        args += ["--mac-off", n]
    for k in fw_on:
        args += ["--fw-on", k]
    return run_elevated(args, timeout_s=180)


def read_tpm() -> ActionResult:
    from auxy.core import winsec

    if system.is_admin():
        try:
            return ActionResult(True, "TPM okundu.", data=winsec.read_tpm())
        except AuxyError as exc:
            return ActionResult(False, str(exc))
    return run_elevated(["tpm-info"])
