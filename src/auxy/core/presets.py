"""Ön ayarlar: tek tikla birden cok ayari birlikte degistiren profiller (hiz, guvenilirlik, gizlilik...).

Akis: `capture_state()` mevcut durumu okur -> `build_plan(key, state)` NE degisecegini hesaplar (zaten istenen degerdekiler
atlanir) -> kullanici onaylar -> `execute(plan)` uygular. Yonetici gerektirenler (DNS, rastgele MAC, guvenlik duvari)
TEK bir UAC isteminde birlestirilir. Uygulamadan once onceki durum `preset_state.json`'a yazilir; `revert()` onu geri yukler.

Her on ayar acik ve sinirlidir (DNS, sifreli DNS, WARP, Tor, gizlilik anahtarlari, guvenlik duvari profilleri). Defender
korumalarina, GoodbyeDPI'a ya da dosyalara DOKUNMAZ.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from auxy.core import dns, netservices, paths, privacy, tor
from auxy.core.service import AuxyError

STATE_FILE = "preset_state.json"
FW_KEYS = ("fw_domain", "fw_private", "fw_public")


@dataclass(frozen=True)
class PresetInfo:
    key: str
    name: str
    tagline: str
    bullets: tuple[str, ...]


PRESETS: dict[str, PresetInfo] = {p.key: p for p in (
    PresetInfo("hiz", "En iyi hız", "Yavaş interneti hızlandır.",
               ("Bu ağda ÖLÇÜLEN en hızlı DNS (şifresiz)", "WARP ve Tor kapalı (ek gecikme yok)")),
    PresetInfo("guvenilir", "En güvenilir bağlantı", "Kopmayan, zararlı sitelerden korunan bağlantı.",
               ("Quad9 DNS (zararlı alan adlarını engeller)", "Şifreli DNS, olmazsa şifresize düşer (kopma yok)",
                "Güvenlik duvarı tüm ağ profillerinde açık")),
    PresetInfo("gizli", "En gizli bağlantı", "Ağdakilerin ve operatörün göremediği internet.",
               ("Şifreli DNS (Cloudflare, sıkı mod)", "WARP açık (trafik şifreli)", "Reklam kimliği ve kişiselleştirme kapalı",
                "Rastgele Wi-Fi MAC adresi")),
    PresetInfo("tor", "Maksimum gizlilik (Tor)", "En gizli ayarlar + Tor. Yavaştır.",
               ("'En gizli bağlantı'daki her şey", "Tor çalışır ve Windows vekili Tor'a ayarlanır")),
    PresetInfo("yurt", "Yurt / kısıtlı ağ", "Yavaş ya da müdahaleli yurt/kampüs ağları için.",
               ("Bu ağda ölçülen, kirletmeyen en iyi DNS (+ şifreli)", "WARP tüm trafiği tünelden geçirir")),
)}

SPECS: dict[str, dict] = {
    "hiz": dict(dns="best", doh=False, strict=False, warp=False, tor=False, flags=None, mac=None, fw=False),
    "guvenilir": dict(dns="quad9", doh=True, strict=False, warp=None, tor=False, flags=None, mac=None, fw=True),
    "gizli": dict(dns="cloudflare", doh=True, strict=True, warp="warp+doh", tor=False,
                  flags={"ad_id": False, "tailored": False}, mac=True, fw=False),
    "tor": dict(dns="cloudflare", doh=True, strict=True, warp="warp+doh", tor=True,
                flags={"ad_id": False, "tailored": False}, mac=True, fw=False),
    "yurt": dict(dns="best", doh=True, strict=False, warp="warp", tor=None, flags=None, mac=None, fw=False),
}


@dataclass(frozen=True)
class State:
    adapters: tuple[dns.Adapter, ...]
    warp: netservices.WarpInfo
    flags: dict[str, bool | None]
    macs: dict[str, bool]
    tor: tor.TorStatus
    tor_proxy: bool
    gdpi: netservices.ServiceInfo
    fw: dict[str, str] = field(default_factory=dict)       # fw_domain.. -> on/off
    active: str = ""                                      # son uygulanan on ayar


@dataclass(frozen=True)
class Change:
    kind: str            # dns | warp-mode | warp-conn | flag | mac | tor | tor-proxy | fw
    target: str          # kind'a gore: dns degeri / mod / anahtar adi ...
    label: str
    before: str
    after: str
    admin: bool = False
    extra: tuple = ()    # dns: (doh, strict)


@dataclass
class Plan:
    preset: str
    changes: list[Change] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)       # zaten istenen degerde / atlananlar
    dns_best: str = ""                                    # 'best' ise secilen DNS aciklamasi

    @property
    def needs_admin(self) -> bool:
        return any(c.admin for c in self.changes)


# ---------------------------------------------------------------- durum
def state_path() -> Path:
    return paths.home() / STATE_FILE


def load_record() -> dict:
    try:
        return json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_record(data: dict) -> None:
    state_path().parent.mkdir(parents=True, exist_ok=True)
    state_path().write_text(json.dumps(data, indent=1), encoding="utf-8")


def capture_state() -> State:
    from auxy.core import winsec

    try:
        fw = winsec.WinSecService().get_many(FW_KEYS)
    except Exception:  # noqa: BLE001 - okunamazsa guvenlik duvari adimi atlanir
        fw = {}
    return State(tuple(dns.read_adapters()), netservices.read_warp(),
                 {k: privacy.get_flag(k) for k in privacy.FLAGS}, privacy.read_mac_randomization(), tor.status(),
                 tor.system_proxy_is_tor(), netservices.read_service(), fw, load_record().get("active", ""))


# ---------------------------------------------------------------- plan
def _dns_now(adapters) -> str:
    return "; ".join(f"{a.name}: {', '.join(a.v4) or '—'}" for a in adapters) or "—"


def resolve_best(state: State, bench: Callable = dns.benchmark) -> tuple[str, str]:
    """Bu agda en iyi DNS: (dns degeri | '', aciklama). Hazir ayara karsilik gelmeyen/olcum yoksa ('' = degistirme)."""
    extra = [(a.v4[0], f"Şu anki ({a.name})") for a in state.adapters if a.v4]
    results = bench(extra)
    best = dns.best(results)
    if best is None:
        return "", "Güvenilir ölçüm yok (ağ DNS'i engelliyor olabilir)"
    key = dns.preset_for_address(best.server)
    if key is None:
        return "", f"En iyi şu anki DNS ({best.label}, {best.ms:.0f} ms): değiştirilmedi"
    return key, f"{dns.PRESETS[key].name} ({best.ms:.0f} ms, bu ağdaki en hızlı)"


def build_plan(key: str, state: State, best: tuple[str, str] | None = None) -> Plan:
    """Mevcut duruma gore degisiklik listesi. Zaten istenen degerdekiler `notes`'a gider. Saf mantik (ag/yazma yok)."""
    if key not in SPECS:
        raise AuxyError(f"Bilinmeyen ön ayar: {key!r}")
    spec = SPECS[key]
    plan = Plan(key)
    sel = [a for a in state.adapters]
    # ---- DNS
    target = spec["dns"]
    if target == "best":
        value, why = best or ("", "ölçüm yapılmadı")
        plan.dns_best = why
        target = value
    if target and sel:
        v4, _v6, template, name = dns.resolve_servers(target)
        doh = bool(spec["doh"] and template)
        same = all(set(a.v4) >= set(v4) and bool(a.v4) and a.v4[0] == v4[0] for a in sel) and (
            not doh or load_record().get("dns_doh") == target)
        if same:
            plan.notes.append(f"DNS zaten {name}.")
        else:
            plan.changes.append(Change("dns", target, "DNS sunucusu", _dns_now(sel),
                                       name + (" + şifreli (sıkı)" if doh and spec["strict"] else " + şifreli" if doh else ""),
                                       True, (doh, bool(spec["strict"] and doh))))
    elif spec["dns"] == "best":
        plan.notes.append(f"DNS: {plan.dns_best or 'değiştirilmedi'}")
    elif not sel:
        plan.notes.append("Bağlı fiziksel ağ yok: DNS adımı atlandı.")
    # ---- WARP
    w = state.warp
    wspec = spec["warp"]
    if wspec is not None:
        if not w.installed:
            plan.notes.append("WARP kurulu değil: WARP adımları atlandı (Ağ güvenliği sayfasından kurabilirsin).")
        elif wspec is False:
            if w.status in ("Connected", "Connecting"):
                plan.changes.append(Change("warp-conn", "disconnect", "WARP", "bağlı", "bağlantı kesik"))
        else:
            if w.mode != wspec:
                plan.changes.append(Change("warp-mode", wspec, "WARP kipi", netservices.WARP_MODES.get(w.mode, w.mode or "?"),
                                           netservices.WARP_MODES[wspec]))
            if w.status not in ("Connected", "Connecting"):
                plan.changes.append(Change("warp-conn", "connect", "WARP", "bağlı değil", "bağlı"))
    # ---- gizlilik anahtarlari
    for fk, want in (spec["flags"] or {}).items():
        cur = state.flags.get(fk)
        effective = True if cur is None else cur  # kayit yok = Windows varsayilani: acik
        if effective != want:
            label = privacy.FLAGS[fk][2]
            plan.changes.append(Change("flag", fk, label, "açık" if cur in (True, None) else "kapalı",
                                       "açık" if want else "kapalı"))
    # ---- rastgele MAC
    if spec["mac"] is not None:
        for iface, on in state.macs.items():
            if on != spec["mac"]:
                plan.changes.append(Change("mac", iface, f"Rastgele MAC ({iface})", "kapalı" if not on else "açık",
                                           "açık" if spec["mac"] else "kapalı", True))
        if not state.macs:
            plan.notes.append("Wi-Fi arayüzü yok: rastgele MAC atlandı.")
    # ---- guvenlik duvari
    if spec["fw"]:
        for fk in FW_KEYS:
            if state.fw.get(fk) == "off":
                plan.changes.append(Change("fw", fk, "Güvenlik duvarı: " + {"fw_domain": "etki alanı", "fw_private": "özel",
                                                                          "fw_public": "genel"}[fk] + " ağ", "kapalı", "açık", True))
    # ---- Tor
    t = state.tor
    if spec["tor"] is True:
        if not t.installed:
            plan.notes.append("Tor kurulu değil: 'DNS ve gizlilik' sayfasından kur, sonra bu ön ayarı yeniden uygula.")
        else:
            if not t.running:
                plan.changes.append(Change("tor", "start", "Tor", "durdu", "çalışıyor"))
            if not state.tor_proxy:
                plan.changes.append(Change("tor-proxy", "on", "Windows vekili", "kapalı", "Tor'a ayarlı"))
    elif spec["tor"] is False:
        if t.running:
            plan.changes.append(Change("tor", "stop", "Tor", "çalışıyor", "durdu"))
        if state.tor_proxy:
            plan.changes.append(Change("tor-proxy", "off", "Windows vekili", "Tor'a ayarlı", "eski haline"))
    # ---- uyarilar
    if any(c.kind == "dns" for c in plan.changes):
        warp_on = w.installed and w.status in ("Connected", "Connecting") and not any(
            c.kind == "warp-conn" and c.target == "disconnect" for c in plan.changes)
        if warp_on:
            plan.warnings.append("WARP bağlıyken DNS'i WARP yönetir: seçilen DNS sistemde görünür ama WARP bağlıyken etkisiz kalabilir.")
        g = state.gdpi
        if g.installed and g.state == "running" and dns.gdpi_dns_redirect(g.arguments, True):
            plan.warnings.append("GoodbyeDPI çalışıyor ve DNS'i kendi sunucusuna yönlendiriyor (--dns-addr): DNS ayarı etkisiz kalır.")
    if state.active == key and not plan.changes:
        plan.notes.append("Bu ön ayar zaten uygulanmış.")
    return plan


def describe(plan: Plan) -> str:
    """Onay kutusu icin okunur ozet."""
    info = PRESETS[plan.preset]
    lines = [f"'{info.name}' şunları değiştirecek:", ""]
    lines += [f"• {c.label}: {c.before} → {c.after}" for c in plan.changes] or ["• (değişecek bir şey yok)"]
    if plan.notes:
        lines += ["", *[f"ℹ {n}" for n in plan.notes]]
    if plan.warnings:
        lines += ["", *[f"⚠ {w}" for w in plan.warnings]]
    if plan.needs_admin:
        lines += ["", "Bazı adımlar yönetici izni ister (tek bir UAC penceresi)."]
    lines += ["", "İstediğin zaman 'Önceki ayarlara dön' ile geri alabilirsin."]
    return "\n".join(lines)


# ---------------------------------------------------------------- uygulama
@dataclass(frozen=True)
class StepResult:
    label: str
    ok: bool
    message: str


def _snapshot(state: State, key: str) -> dict:
    return {"active": key, "previous": {
        "flags": state.flags, "macs": state.macs, "warp_mode": state.warp.mode,
        "warp_connected": state.warp.status in ("Connected", "Connecting"), "tor_running": state.tor.running,
        "tor_proxy": state.tor_proxy, "fw": state.fw, "adapters": [a.index for a in state.adapters]}}


def execute(plan: Plan, state: State, admin_runner: Callable | None = None) -> list[StepResult]:
    """Plani uygular. `admin_runner(dns=…, adapters=…, doh=…, strict=…, macs_on=…, macs_off=…, fw_on=…)` TEK UAC ile
    yonetici adimlarini yapar (actions.preset_admin). Bir adim hata verse digerleri yine denenir."""
    results: list[StepResult] = []
    if not plan.changes:
        return [StepResult("Ön ayar", True, "Değişecek bir şey yoktu.")]
    record = _snapshot(state, plan.preset)
    old = load_record()
    if "previous" in old and old.get("active"):       # zincir: ilk onceki durum korunur (geri alinca asil haline donsun)
        record["previous"] = old["previous"]
    admin = [c for c in plan.changes if c.admin]
    if admin and admin_runner is not None:
        d = next((c for c in admin if c.kind == "dns"), None)
        res = admin_runner(dns=d.target if d else "", adapters=[a.index for a in state.adapters] if d else [],
                           doh=bool(d and d.extra[0]), strict=bool(d and d.extra[1]),
                           macs_on=[c.target for c in admin if c.kind == "mac" and c.after == "açık"],
                           macs_off=[c.target for c in admin if c.kind == "mac" and c.after == "kapalı"],
                           fw_on=[c.target for c in admin if c.kind == "fw"])
        ok = bool(res.ok)
        for c in admin:
            results.append(StepResult(c.label, ok, res.message if not ok else f"{c.after}"))
        if d and ok:
            record["dns_doh"] = d.target if d.extra[0] else ""
    for c in plan.changes:
        if c.admin:
            continue
        try:
            results.append(StepResult(c.label, True, _run_step(c)))
        except (AuxyError, OSError) as exc:
            results.append(StepResult(c.label, False, str(exc)))
    if any(r.ok for r in results):
        save_record(record)
    return results


def _run_step(c: Change) -> str:
    if c.kind == "warp-mode":
        return netservices.warp_op("mode", c.target).message
    if c.kind == "warp-conn":
        r = netservices.warp_op("connect" if c.target == "connect" else "disconnect")
        if not r.ok:
            raise AuxyError(r.message)
        return r.message
    if c.kind == "flag":
        return privacy.set_flag(c.target, c.after == "açık")
    if c.kind == "tor":
        return tor.start() if c.target == "start" else tor.stop()
    if c.kind == "tor-proxy":
        return tor.set_system_proxy(c.target == "on")
    raise AuxyError(f"Bilinmeyen adım: {c.kind}")


def revert_plan(state: State) -> Plan:
    """Kayitli 'onceki durum'a donus plani (kayit yoksa bos)."""
    rec = load_record()
    prev = rec.get("previous")
    plan = Plan("geri-al")
    if not prev:
        plan.notes.append("Geri alınacak bir ön ayar kaydı yok.")
        return plan
    sel = list(state.adapters)
    if sel and rec.get("dns_doh") is not None:
        plan.changes.append(Change("dns", "", "DNS sunucusu", _dns_now(sel), "eski haline (otomatik / önceki elle ayar)", True, (False, False)))
    for fk, was in (prev.get("flags") or {}).items():
        cur = state.flags.get(fk)
        if (True if cur is None else cur) != (True if was is None else was):
            plan.changes.append(Change("flag", fk, privacy.FLAGS[fk][2], "açık" if cur in (True, None) else "kapalı",
                                       "açık" if was in (True, None) else "kapalı"))
    for iface, was in (prev.get("macs") or {}).items():
        if iface in state.macs and state.macs[iface] != was:
            plan.changes.append(Change("mac", iface, f"Rastgele MAC ({iface})", "açık" if state.macs[iface] else "kapalı",
                                       "açık" if was else "kapalı", True))
    for fk, was in (prev.get("fw") or {}).items():
        if state.fw.get(fk) == "on" and was == "off":
            plan.notes.append("Güvenlik duvarı açık kaldı (güvenlik için geri kapatılmaz).")
            break
    w = state.warp
    if w.installed:
        if prev.get("warp_mode") and prev["warp_mode"] != w.mode and prev["warp_mode"] in netservices.WARP_MODES:
            plan.changes.append(Change("warp-mode", prev["warp_mode"], "WARP kipi", netservices.WARP_MODES.get(w.mode, w.mode or "?"),
                                       netservices.WARP_MODES[prev["warp_mode"]]))
        was_conn = bool(prev.get("warp_connected"))
        now_conn = w.status in ("Connected", "Connecting")
        if was_conn != now_conn:
            plan.changes.append(Change("warp-conn", "connect" if was_conn else "disconnect", "WARP",
                                       "bağlı" if now_conn else "bağlı değil", "bağlı" if was_conn else "bağlantı kesik"))
    if state.tor.running and not prev.get("tor_running"):
        plan.changes.append(Change("tor", "stop", "Tor", "çalışıyor", "durdu"))
    if state.tor_proxy and not prev.get("tor_proxy"):
        plan.changes.append(Change("tor-proxy", "off", "Windows vekili", "Tor'a ayarlı", "eski haline"))
    return plan


def execute_revert(plan: Plan, state: State, admin_runner: Callable | None = None) -> list[StepResult]:
    results: list[StepResult] = []
    admin = [c for c in plan.changes if c.admin]
    if admin and admin_runner is not None:
        d = next((c for c in admin if c.kind == "dns"), None)
        res = admin_runner(dns="__reset__" if d else "", adapters=[a.index for a in state.adapters] if d else [],
                           doh=False, strict=False,
                           macs_on=[c.target for c in admin if c.kind == "mac" and c.after == "açık"],
                           macs_off=[c.target for c in admin if c.kind == "mac" and c.after == "kapalı"], fw_on=[])
        results += [StepResult(c.label, bool(res.ok), res.message if not res.ok else c.after) for c in admin]
    for c in plan.changes:
        if not c.admin:
            try:
                results.append(StepResult(c.label, True, _run_step(c)))
            except (AuxyError, OSError) as exc:
                results.append(StepResult(c.label, False, str(exc)))
    if all(r.ok for r in results):
        state_path().unlink(missing_ok=True)
    return results


def summarize(results: list[StepResult]) -> tuple[bool, str]:
    bad = [r for r in results if not r.ok]
    if not bad:
        return True, f"{len(results)} adım uygulandı."
    return False, f"{len(results) - len(bad)}/{len(results)} adım tamam. Hatalar: " + "; ".join(f"{r.label}: {r.message}" for r in bad)
