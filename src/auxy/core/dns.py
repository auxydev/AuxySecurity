"""DNS yonetimi: karti-adaptore DNS sunucusu atama, sifreli DNS (DoH), hiz/guvenlik testi.

Neden: yurt/kampus (ornegin KYK-GSB) ve bazi servis saglayici aglari yavas ya da mudahaleci bir DNS verir (yavas
cozumleme, var olmayan alan adlarina sahte yanit, engelleme). Dogru DNS'i secmek icin tahmin yerine ONCE OLC:
`benchmark` her sunucuya gercek sorgu gonderir (hiz, UDP/53 ve HTTPS/443 erisilebilirligi, NXDOMAIN kirletme).

Not (dogrulandi): ODTU'nun DNS sunuculari yalnizca ODTU IP araligindan (144.122.0.0/16) gelen ozyinelemeli sorgulara
yanit verir; disaridan (ornegin yurttan) kullanilamaz. Bu yuzden hazir ayarlara eklenmedi.

Yazma islemleri yonetici ister (`auxy dns ...` yukseltilmis yardimcisi). Okuma ve test yonetici istemez.
"""

from __future__ import annotations

import ipaddress
import json
import random
import socket
import statistics
import struct
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from auxy.core import paths, pshell
from auxy.core.service import AuxyError


@dataclass(frozen=True)
class Preset:
    key: str
    name: str
    v4: tuple[str, ...]
    v6: tuple[str, ...]
    doh: str | None
    note: str


PRESETS: dict[str, Preset] = {p.key: p for p in (
    Preset("cloudflare", "Cloudflare (1.1.1.1)", ("1.1.1.1", "1.0.0.1"), ("2606:4700:4700::1111", "2606:4700:4700::1001"),
           "https://cloudflare-dns.com/dns-query", "Hızlı ve gizlilik odaklı; kayıt tutmaz."),
    Preset("google", "Google (8.8.8.8)", ("8.8.8.8", "8.8.4.4"), ("2001:4860:4860::8888", "2001:4860:4860::8844"),
           "https://dns.google/dns-query", "Çok yaygın ve kararlı."),
    Preset("quad9", "Quad9 (9.9.9.9)", ("9.9.9.9", "149.112.112.112"), ("2620:fe::fe", "2620:fe::9"),
           "https://dns.quad9.net/dns-query", "Zararlı alan adlarını engeller (güvenlik odaklı)."),
    Preset("adguard", "AdGuard DNS", ("94.140.14.14", "94.140.15.15"), ("2a10:50c0::ad1:ff", "2a10:50c0::ad2:ff"),
           "https://dns.adguard-dns.com/dns-query", "Reklam ve izleyicileri engeller."),
    Preset("opendns", "OpenDNS", ("208.67.222.222", "208.67.220.220"), (), "https://doh.opendns.com/dns-query",
           "Cisco; isteğe bağlı içerik filtreleme."),
)}

BENCH_DOMAINS = ("google.com", "youtube.com", "wikipedia.org", "github.com", "cloudflare.com", "microsoft.com")
BACKUP_FILE = "dns_backup.json"


@dataclass(frozen=True)
class Adapter:
    index: int
    name: str
    description: str
    guid: str
    kind: str                      # wifi | ethernet | other
    v4: tuple[str, ...] = ()
    v6: tuple[str, ...] = ()
    static: bool = False           # DNS elle atanmis mi (False: DHCP'den otomatik)


@dataclass(frozen=True)
class BenchResult:
    server: str
    label: str
    ms: float | None               # UDP/53 ortanca gecikme (None: yanit yok)
    failed: int
    total: int
    tcp443_ms: float | None        # HTTPS(443) baglanti suresi: DoH icin erisilebilirlik
    hijacked: bool | None          # var olmayan alan adina sahte yanit (None: olculemedi)


# ---------------------------------------------------------------- dogrulama
def validate_ip(value: str) -> str:
    try:
        ip = ipaddress.ip_address(value.strip())
    except ValueError as exc:
        raise AuxyError(f"Geçersiz IP adresi: {value!r}") from exc
    if ip.is_unspecified or ip.is_multicast or ip.is_loopback:
        raise AuxyError(f"Geçersiz DNS adresi: {value!r}")
    return str(ip)


def resolve_servers(value: str) -> tuple[tuple[str, ...], tuple[str, ...], str | None, str]:
    """Hazir ayar anahtari ya da virgullu IP listesi -> (v4, v6, doh sablonu, gorunen ad)."""
    if value in PRESETS:
        p = PRESETS[value]
        return p.v4, p.v6, p.doh, p.name
    items = [validate_ip(x) for x in value.replace(";", ",").split(",") if x.strip()]
    if not items or len(items) > 4:
        raise AuxyError("1-4 geçerli IP adresi gir (virgülle ayır) ya da hazır bir ayar seç.")
    v4 = tuple(i for i in items if ipaddress.ip_address(i).version == 4)
    v6 = tuple(i for i in items if ipaddress.ip_address(i).version == 6)
    known = _doh_for(items)
    return v4, v6, known, "Özel DNS"


def _doh_for(addresses: list[str]) -> str | None:
    """Tum adresler ayni bilinen saglayiciya aitse onun DoH sablonu."""
    templates = {p.doh for p in PRESETS.values() for a in addresses if a in p.v4 + p.v6}
    covered = all(any(a in p.v4 + p.v6 for p in PRESETS.values()) for a in addresses)
    return next(iter(templates)) if covered and len(templates) == 1 else None


# ---------------------------------------------------------------- okuma
_READ_PS = r"""
$ErrorActionPreference = 'Stop'
$out = @()
foreach ($a in (Get-NetAdapter -Physical | Where-Object { $_.Status -eq 'Up' })) {
  $v4 = @((Get-DnsClientServerAddress -InterfaceIndex $a.ifIndex -AddressFamily IPv4).ServerAddresses)
  $v6 = @((Get-DnsClientServerAddress -InterfaceIndex $a.ifIndex -AddressFamily IPv6).ServerAddresses)
  $g = $a.InterfaceGuid
  $ns = (Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces\$g" -ErrorAction SilentlyContinue).NameServer
  $out += [pscustomobject]@{ index=[int]$a.ifIndex; name=$a.Name; description=$a.InterfaceDescription; guid=$g;
    media=$a.PhysicalMediaType; v4=$v4; v6=$v6; static=[bool]$ns }
}
ConvertTo-Json -InputObject @($out) -Compress -Depth 4
"""


def _kind(media: str, name: str) -> str:
    s = f"{media} {name}".lower()
    if "802.11" in s or "wi-fi" in s or "wifi" in s or "wireless" in s or "wlan" in s:
        return "wifi"
    if "802.3" in s or "ethernet" in s:
        return "ethernet"
    return "other"


def read_adapters(run: Callable = pshell.run) -> list[Adapter]:
    """Bagli fiziksel aglar ve gecerli DNS'leri. Yonetici gerekmez."""
    rc, out, err = run(_READ_PS, timeout=30)
    if rc != 0:
        raise AuxyError(f"Ağ bağdaştırıcıları okunamadı: {(err or out).strip()[-200:]}")
    try:
        items = json.loads(out.strip() or "[]")
    except json.JSONDecodeError as exc:
        raise AuxyError("Ağ bağdaştırıcısı çıktısı çözülemedi.") from exc
    if isinstance(items, dict):
        items = [items]
    return [Adapter(int(i["index"]), str(i["name"]), str(i["description"]), str(i["guid"]),
                    _kind(str(i.get("media") or ""), str(i["name"])), tuple(i.get("v4") or ()),
                    tuple(i.get("v6") or ()), bool(i.get("static"))) for i in items]


def describe_servers(a: Adapter) -> str:
    servers = list(a.v4) + list(a.v6)
    known = next((p.name for p in PRESETS.values() if servers and set(a.v4) <= set(p.v4) and a.v4), None)
    mode = "elle" if a.static else "otomatik (ağdan)"
    return f"{', '.join(servers) or '—'}  •  {mode}" + (f"  •  {known}" if known else "")


# ---------------------------------------------------------------- yazma (yonetici)
_APPLY_PS = r"""
$ErrorActionPreference = 'Stop'
$servers = @()
if ($env:AUXY_V4) { $servers += $env:AUXY_V4.Split(',') }
if ($env:AUXY_V6) { $servers += $env:AUXY_V6.Split(',') }
foreach ($i in $env:AUXY_IDX.Split(',')) {
  Set-DnsClientServerAddress -InterfaceIndex ([int]$i) -ServerAddresses $servers
}
if ($env:AUXY_DOH) {
  $fallback = ($env:AUXY_STRICT -ne '1')
  foreach ($a in $servers) {
    if (Get-DnsClientDohServerAddress -ServerAddress $a -ErrorAction SilentlyContinue) {
      Set-DnsClientDohServerAddress -ServerAddress $a -DohTemplate $env:AUXY_DOH -AllowFallbackToUdp $fallback -AutoUpgrade $true
    } else {
      Add-DnsClientDohServerAddress -ServerAddress $a -DohTemplate $env:AUXY_DOH -AllowFallbackToUdp $fallback -AutoUpgrade $true
    }
  }
}
Clear-DnsClientCache
"""

_RESET_PS = r"""
$ErrorActionPreference = 'Stop'
foreach ($i in $env:AUXY_IDX.Split(',')) { Set-DnsClientServerAddress -InterfaceIndex ([int]$i) -ResetServerAddresses }
Clear-DnsClientCache
"""

_FLUSH_PS = "Clear-DnsClientCache"


def _backup_path() -> Path:
    return paths.home() / BACKUP_FILE


def _load_backup() -> dict:
    try:
        return json.loads(_backup_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_backup(data: dict) -> None:
    _backup_path().parent.mkdir(parents=True, exist_ok=True)
    _backup_path().write_text(json.dumps(data, indent=1), encoding="utf-8")


def _indexes(adapters: list[int]) -> str:
    if not adapters:
        raise AuxyError("En az bir ağ bağdaştırıcısı seç.")
    return ",".join(str(int(i)) for i in adapters)


def apply(value: str, adapter_indexes: list[int], doh: bool = False, strict: bool = False,
          run: Callable = pshell.run, read: Callable = read_adapters) -> str:
    """DNS'i atar (yonetici). Ilk degisiklikte onceki ayar yedeklenir. Mesaj dondurur."""
    v4, v6, template, name = resolve_servers(value)
    if doh and not template:
        raise AuxyError("Bu DNS için şifreli (DoH) adres bilinmiyor: hazır bir ayar seç ya da DoH'u kapat.")
    idx = _indexes(adapter_indexes)
    backup = _load_backup()
    for a in read(run):
        if a.index in adapter_indexes and a.guid not in backup:
            backup[a.guid] = {"name": a.name, "index": a.index, "v4": list(a.v4) if a.static else [],
                              "v6": list(a.v6) if a.static else [], "static": a.static}
    _save_backup(backup)
    env = {"AUXY_IDX": idx, "AUXY_V4": ",".join(v4), "AUXY_V6": ",".join(v6),
           "AUXY_DOH": template if doh and template else "", "AUXY_STRICT": "1" if strict else "0"}
    rc, out, err = run(_APPLY_PS, env=env, timeout=60)
    if rc != 0:
        raise AuxyError(f"DNS uygulanamadı: {(err or out).strip()[-240:]}")
    return f"DNS {name} olarak ayarlandı" + (" (şifreli)" if doh else "") + "."


def reset(adapter_indexes: list[int], run: Callable = pshell.run, read: Callable = read_adapters) -> str:
    """Yedekteki eski ayara (ya da yoksa otomatige/DHCP) dondurur (yonetici)."""
    _indexes(adapter_indexes)  # bos secimi reddet
    backup = _load_backup()
    restored, auto = [], []
    for a in read(run):
        if a.index not in adapter_indexes:
            continue
        old = backup.get(a.guid)
        if old and old.get("static") and (old.get("v4") or old.get("v6")):
            env = {"AUXY_IDX": str(a.index), "AUXY_V4": ",".join(old.get("v4", [])),
                   "AUXY_V6": ",".join(old.get("v6", [])), "AUXY_DOH": "", "AUXY_STRICT": "0"}
            rc, out, err = run(_APPLY_PS, env=env, timeout=60)
            if rc != 0:
                raise AuxyError(f"Eski DNS geri yüklenemedi: {(err or out).strip()[-240:]}")
            restored.append(a.name)
        else:
            rc, out, err = run(_RESET_PS, env={"AUXY_IDX": str(a.index)}, timeout=60)
            if rc != 0:
                raise AuxyError(f"DNS sıfırlanamadı: {(err or out).strip()[-240:]}")
            auto.append(a.name)
        backup.pop(a.guid, None)
    _save_backup(backup)
    parts = []
    if auto:
        parts.append("otomatik (ağdan): " + ", ".join(auto))
    if restored:
        parts.append("eski elle ayar: " + ", ".join(restored))
    return "DNS eski haline döndü — " + "; ".join(parts) if parts else "Geri alınacak bağdaştırıcı bulunamadı."


def flush_cache(run: Callable = pshell.run) -> str:
    rc, out, err = run(_FLUSH_PS, timeout=30)
    if rc != 0:
        raise AuxyError(f"DNS önbelleği temizlenemedi: {(err or out).strip()[-200:]}")
    return "DNS önbelleği temizlendi."


# ---------------------------------------------------------------- olcum
def build_query(name: str, txid: int | None = None, qtype: int = 1) -> bytes:
    txid = random.randrange(0, 65536) if txid is None else txid
    header = struct.pack("!HHHHHH", txid, 0x0100, 1, 0, 0, 0)  # RD=1
    qname = b"".join(bytes([len(p)]) + p.encode("ascii") for p in name.strip(".").split(".")) + b"\x00"
    return header + qname + struct.pack("!HH", qtype, 1)


def parse_response(data: bytes, txid: int | None = None) -> tuple[int, int]:
    """(rcode, cevap sayisi). Kisa/bozuk ya da farkli txid'li paket ValueError."""
    if len(data) < 12:
        raise ValueError("kısa DNS yanıtı")
    rid, flags, _qd, an, _ns, _ar = struct.unpack("!HHHHHH", data[:12])
    if txid is not None and rid != txid:
        raise ValueError("DNS yanıt kimliği uyuşmuyor")
    if not flags & 0x8000:
        raise ValueError("yanıt değil")
    return flags & 0x000F, an


def query_udp(server: str, name: str, timeout: float = 1.5) -> tuple[float, int, int]:
    """(ms, rcode, cevap sayisi). Zaman asimi: TimeoutError / OSError."""
    family = socket.AF_INET6 if ":" in server else socket.AF_INET
    txid = random.randrange(0, 65536)
    packet = build_query(name, txid)
    with socket.socket(family, socket.SOCK_DGRAM) as s:
        s.settimeout(timeout)
        t0 = time.perf_counter()
        s.sendto(packet, (server, 53))
        data, _ = s.recvfrom(2048)
        ms = (time.perf_counter() - t0) * 1000
    rcode, answers = parse_response(data, txid)
    return ms, rcode, answers


def tcp443_ms(server: str, timeout: float = 2.0) -> float | None:
    try:
        t0 = time.perf_counter()
        with socket.create_connection((server, 443), timeout=timeout):
            return (time.perf_counter() - t0) * 1000
    except OSError:
        return None


def bench_server(server: str, label: str = "", domains: tuple[str, ...] = BENCH_DOMAINS, rounds: int = 2,
                 timeout: float = 1.5, query: Callable = query_udp, probe443: Callable = tcp443_ms) -> BenchResult:
    times: list[float] = []
    failed = 0
    for _ in range(rounds):
        for d in domains:
            try:
                ms, rcode, answers = query(server, d, timeout)
                if rcode == 0 and answers > 0:
                    times.append(ms)
                else:
                    failed += 1
            except (OSError, ValueError, TimeoutError):
                failed += 1
    hijacked: bool | None = None
    try:  # var olmayan alan adi NXDOMAIN (rcode 3) donmeli; cevap donuyorsa yonlendirme/kirletme var
        _ms, rcode, answers = query(server, f"auxy-nx-{random.randrange(16**8):08x}.com", timeout)
        hijacked = rcode == 0 and answers > 0
    except (OSError, ValueError, TimeoutError):
        pass
    return BenchResult(server, label or server, round(statistics.median(times), 1) if times else None, failed,
                       rounds * len(domains), probe443(server), hijacked)


def benchmark(extra: list[tuple[str, str]] | None = None, workers: int = 6, **kw) -> list[BenchResult]:
    """Hazir ayarlarin ilk adresleri + (varsa) `extra` [(adres, etiket)] icin test; hizliya gore siralar."""
    targets = [(p.v4[0], p.name) for p in PRESETS.values()] + list(extra or [])
    seen, unique = set(), []
    for addr, label in targets:
        if addr not in seen:
            seen.add(addr)
            unique.append((addr, label))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda t: bench_server(t[0], t[1], **kw), unique))
    return sorted(results, key=lambda r: (r.ms is None, r.ms if r.ms is not None else 0))


def best(results: list[BenchResult]) -> BenchResult | None:
    """En hizli, kirletmeyen ve guvenilir (hata orani dusuk) sunucu."""
    ok = [r for r in results if r.ms is not None and r.hijacked is not True and r.failed <= r.total // 3]
    return ok[0] if ok else None


def preset_for_address(address: str) -> str | None:
    return next((k for k, p in PRESETS.items() if address in p.v4), None)


def gdpi_dns_redirect(arguments: str, running: bool) -> bool:
    """GoodbyeDPI '--dns-addr' ile UDP/53 sorgularini kendi sunucusuna yonlendirir: sistem DNS'i degismis olsa bile etkisiz."""
    return running and "--dns-addr" in arguments.split()


# ---------------------------------------------------------------- ag bilgisi (kullanici isteyince, internete cikar)
def fetch_trace(timeout: float = 6.0, opener: Callable | None = None) -> dict[str, str]:
    """Cloudflare iz kaydi: genel IP, ulke, WARP durumu. Ucuncu tarafa istek yapar: yalnizca kullanici isteyince."""
    import urllib.request

    open_ = opener or (lambda url, t: urllib.request.urlopen(url, timeout=t))  # noqa: S310
    with open_("https://1.1.1.1/cdn-cgi/trace", timeout) as resp:
        text = resp.read().decode("utf-8", "replace")
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


__all__ = ["PRESETS", "Adapter", "BenchResult", "apply", "reset", "flush_cache", "read_adapters", "benchmark", "best"]
