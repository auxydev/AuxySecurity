"""Aga bagli DNS kurali: secilen DNS yalnizca GUVENILEN aglarda (ev Wi-Fi'i gibi) uygulanir.

Diger her agda (kampus, yurt, kafe, otel) DNS otomatige (DHCP) doner. Neden: bu aglar giris sayfasini (captive
portal) yalnizca kendi DNS sunuculariyla acar; elle atanmis 1.1.1.1 "bagli ama internet yok / giris sayfasi gelmiyor"
sorununa yol acar ve giris yapilmadan disari DNS sorgusu da cikamaz.

- Kural `dns_scope.json` dosyasinda tutulur (kullanici verisi; yonetici gerekmez).
- `plan()` saf islevdir: bagdastiricilar + kural -> yapilacak adimlar. Test edilebilir, sistemde hicbir sey degistirmez.
- `enforce()` plani uygular (yonetici gerekir). Tray ajani ag degisince bunu kendiliginden cagirir.
- Guvenilmeyen agda yalnizca BIZIM atadigimiz DNS geri alinir; kullanicinin baska bir arac/elle yaptigi ayara dokunulmaz.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from auxy.core import dns, paths
from auxy.core.service import AuxyError

SCOPE_FILE = "dns_scope.json"
MAX_NETWORKS = 50


@dataclass
class Rule:
    enabled: bool = False
    value: str = ""                 # dns.resolve_servers'in kabul ettigi deger (on ayar anahtari ya da IP listesi)
    doh: bool = False
    strict: bool = False
    networks: list[str] = field(default_factory=list)   # guvenilen ag adlari (Get-NetConnectionProfile Name)

    def sanitized(self) -> Rule:
        seen: dict[str, str] = {}
        for n in self.networks if isinstance(self.networks, list) else []:
            if isinstance(n, str) and n.strip():
                seen.setdefault(n.strip().casefold(), n.strip())
        doh = bool(self.doh)
        return Rule(bool(self.enabled), str(self.value or "").strip(), doh, bool(self.strict) and doh,
                    list(seen.values())[:MAX_NETWORKS])

    def trusts(self, network: str) -> bool:
        key = (network or "").strip().casefold()
        return bool(key) and key in {n.casefold() for n in self.networks}


def scope_file() -> Path:
    return paths.home() / SCOPE_FILE


def load() -> Rule:
    try:
        raw = json.loads(scope_file().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Rule()
    if not isinstance(raw, dict):
        return Rule()
    base = Rule()
    return Rule(**{k: raw.get(k, getattr(base, k)) for k in asdict(base)}).sanitized()


def save(rule: Rule) -> None:
    target = scope_file()
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(rule.sanitized()), indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, target)


def validate(rule: Rule) -> Rule:
    """Etkin kural icin DNS degeri ve DoH sablonu gecerli mi? Gecersizse AuxyError."""
    rule = rule.sanitized()
    if rule.enabled:
        if not rule.value:
            raise AuxyError("Ağa bağlı kural için bir DNS seç.")
        template = dns.resolve_servers(rule.value)[2]
        if rule.doh and not template:
            raise AuxyError("Bu DNS için şifreli (DoH) adres bilinmiyor: hazır bir ayar seç ya da DoH'u kapat.")
        if not rule.networks:
            raise AuxyError("En az bir güvenilen ağ ekle (ör. evdeki Wi-Fi). Diğer ağlarda DNS otomatik kalır.")
    return rule


@dataclass(frozen=True)
class Step:
    op: str                 # apply | reset
    adapter: dns.Adapter

    def describe(self, rule: Rule) -> str:
        net = self.adapter.network or self.adapter.name
        if self.op == "apply":
            return f"Güvenilen ağ ({net}): DNS {dns.resolve_servers(rule.value)[3]} olarak ayarlandı."
        return f"Güvenilmeyen ağ ({net}): DNS otomatiğe (ağın kendi DNS'i) döndürüldü."


def plan(rule: Rule, adapters: list[dns.Adapter], ours: Callable[[str], bool] = dns.changed_by_us) -> list[Step]:
    """Kurala gore hangi bagdastiricida ne yapilacagi. Zaten dogru durumdaysa adim uretmez (gereksiz UAC/yazma yok)."""
    if not rule.enabled or not rule.value or not rule.networks:
        return []
    v4, v6, _template, _name = dns.resolve_servers(rule.value)
    wanted = set(v4) | set(v6)
    steps: list[Step] = []
    for a in adapters:
        if not a.network:  # ag henuz taninmadi (baglaniyor): bir sonraki degisiklik olayinda bakilir
            continue
        current_v4, current_v6 = set(a.v4), set(a.v6)
        if rule.trusts(a.network):
            in_place = a.static and set(v4) <= current_v4 and set(v6) <= current_v6
            if not in_place:
                steps.append(Step("apply", a))
        elif a.static and (ours(a.guid) or (current_v4 | current_v6) & wanted):
            steps.append(Step("reset", a))
    return steps


def enforce(rule: Rule | None = None, read: Callable = dns.read_adapters, apply: Callable = dns.apply,
            reset: Callable = dns.reset) -> list[str]:
    """Kurali su anki aglara uygular (yonetici). Yapilan her degisiklik icin bir mesaj dondurur."""
    rule = (rule or load()).sanitized()
    if not rule.enabled:
        return []
    done: list[str] = []
    for step in plan(rule, read()):
        if step.op == "apply":
            apply(rule.value, [step.adapter.index], rule.doh, rule.strict)
        else:
            reset([step.adapter.index])
        done.append(step.describe(rule))
    return done
