"""DNS, gizlilik ve Tor: gercek DNS/WARP/Tor/ayar degisikligi YOK; her sey enjekte edilen sahte nesnelerle test edilir."""

import hashlib
import io
import json
import struct
import tarfile
import time
from pathlib import Path

import pytest

from auxy import __main__ as cli
from auxy.core import actions, dns, privacy, system, tor
from auxy.core.actions import ActionResult
from auxy.core.service import AuxyError

REAL_SLEEP = time.sleep


def pump(a, cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        a.update()
        if cond():
            return True
        REAL_SLEEP(0.05)
    return False


# ---------------- DNS: dogrulama ----------------
def test_resolve_servers_presets_custom_and_rejects_bad_input():
    v4, v6, doh, name = dns.resolve_servers("cloudflare")
    assert v4 == ("1.1.1.1", "1.0.0.1") and doh == "https://cloudflare-dns.com/dns-query" and "Cloudflare" in name
    v4, v6, doh, name = dns.resolve_servers("8.8.8.8, 8.8.4.4")
    assert v4 == ("8.8.8.8", "8.8.4.4") and doh == "https://dns.google/dns-query" and name == "Özel DNS"
    v4, v6, doh, _ = dns.resolve_servers("2606:4700:4700::1111")
    assert v6 and not v4
    assert dns.resolve_servers("1.1.1.1, 9.9.9.9")[2] is None          # farkli saglayicilar: DoH sablonu belirsiz
    assert dns.resolve_servers("192.168.1.1")[2] is None                # bilinmeyen: DoH yok
    for bad in ("", "abc", "1.1.1.1; calc", "0.0.0.0", "127.0.0.1", "1.1.1.1,2.2.2.2,3.3.3.3,4.4.4.4,5.5.5.5", "$(x)"):
        with pytest.raises(AuxyError):
            dns.resolve_servers(bad)


# ---------------- DNS: paket olusturma/ayristirma ----------------
def make_response(txid, rcode=0, answers=1, qr=True):
    flags = (0x8000 if qr else 0) | 0x0100 | rcode
    return struct.pack("!HHHHHH", txid, flags, 1, answers, 0, 0) + b"\x00" * 8


def test_build_query_and_parse_response():
    pkt = dns.build_query("example.com", txid=0x1234)
    assert pkt[:2] == b"\x12\x34" and pkt[4:6] == b"\x00\x01" and b"\x07example\x03com\x00" in pkt
    assert dns.parse_response(make_response(0x1234), 0x1234) == (0, 1)
    assert dns.parse_response(make_response(7, rcode=3, answers=0)) == (3, 0)
    with pytest.raises(ValueError):
        dns.parse_response(b"\x00\x01")
    with pytest.raises(ValueError):
        dns.parse_response(make_response(1), 2)            # txid uyusmuyor (sahte yanit)
    with pytest.raises(ValueError):
        dns.parse_response(make_response(1, qr=False))     # yanit degil


def test_bench_server_median_failures_and_hijack_detection():
    times = iter([10, 20, 30, 40, 50, 60])

    def good(server, name, timeout):
        if name.startswith("auxy-nx-"):
            return 5.0, 3, 0                               # NXDOMAIN: dogru davranis
        return next(times), 0, 1

    r = dns.bench_server("9.9.9.9", "Q", domains=("a.com", "b.com", "c.com"), rounds=2, query=good,
                         probe443=lambda s: 12.0)
    assert r.ms == 35 and r.failed == 0 and r.total == 6 and r.hijacked is False and r.tcp443_ms == 12.0

    def hijacker(server, name, timeout):
        return 5.0, 0, 1                                   # var olmayan alan adina da cevap: kirletme

    assert dns.bench_server("1.2.3.4", domains=("a.com",), rounds=1, query=hijacker, probe443=lambda s: None).hijacked is True

    def dead(server, name, timeout):
        raise TimeoutError

    r = dns.bench_server("1.2.3.4", domains=("a.com", "b.com"), rounds=1, query=dead, probe443=lambda s: None)
    assert r.ms is None and r.failed == 2 and r.hijacked is None and r.tcp443_ms is None


def test_best_skips_hijacked_failing_and_dead_servers():
    mk = lambda ms, failed=0, hij=False, label="x": dns.BenchResult("1.1.1.1", label, ms, failed, 12, 10.0, hij)  # noqa: E731
    results = [mk(5, hij=True, label="kirletici"), mk(None, 12, label="olu"), mk(8, 9, label="hatali"),
               mk(30, label="iyi"), mk(40, label="yavas")]
    assert dns.best(results).label == "iyi"
    assert dns.best([mk(None, 12)]) is None
    assert dns.preset_for_address("1.1.1.1") == "cloudflare" and dns.preset_for_address("10.0.0.1") is None


def test_benchmark_dedupes_targets_and_sorts_fastest_first(monkeypatch):
    speeds = {"1.1.1.1": 50, "8.8.8.8": 20, "9.9.9.9": None}

    def fake(server, label="", **kw):
        return dns.BenchResult(server, label, speeds.get(server, 70), 0, 12, 1.0, False)

    monkeypatch.setattr(dns, "bench_server", fake)
    res = dns.benchmark(extra=[("8.8.8.8", "Şu anki"), ("10.0.0.1", "Yurt")])
    assert [r.server for r in res][0] == "8.8.8.8" and res[-1].server == "9.9.9.9"   # yanitsiz en sonda
    assert len({r.server for r in res}) == len(res)                                      # tekrar yok


def test_gdpi_dns_redirect_warning():
    assert dns.gdpi_dns_redirect("-5 --dns-addr 77.88.8.8 --dns-port 1253", True)
    assert not dns.gdpi_dns_redirect("-5 --dns-addr 77.88.8.8", False)
    assert not dns.gdpi_dns_redirect("-5 --set-ttl 5", True)


# ---------------- DNS: PowerShell cagrilari (sahte) ----------------
class FakePS:
    def __init__(self, adapters=None):
        self.calls = []
        self.adapters = adapters if adapters is not None else [
            dns.Adapter(12, "Wi-Fi", "x", "{G1}", "wifi", ("192.168.1.1",), (), False),
            dns.Adapter(7, "Ethernet", "y", "{G2}", "ethernet", ("10.0.0.5",), (), True)]

    def __call__(self, command, env=None, timeout=60):
        self.calls.append((command, env or {}))
        return 0, "", ""

    def read(self, run=None):
        return self.adapters


@pytest.fixture
def ps(monkeypatch, tmp_path):
    monkeypatch.setenv("AUXY_HOME", str(tmp_path))
    return FakePS()


def test_apply_passes_values_via_env_never_in_command_text_and_backs_up(ps, tmp_path):
    msg = dns.apply("cloudflare", [12], doh=True, strict=True, run=ps, read=ps.read)
    cmd, env = ps.calls[-1]
    assert "1.1.1.1" not in cmd and env["AUXY_V4"] == "1.1.1.1,1.0.0.1" and env["AUXY_IDX"] == "12"
    assert env["AUXY_DOH"] == "https://cloudflare-dns.com/dns-query" and env["AUXY_STRICT"] == "1"
    assert "şifreli" in msg
    backup = json.loads((tmp_path / dns.BACKUP_FILE).read_text(encoding="utf-8"))
    assert "{G1}" in backup and "{G2}" not in backup and backup["{G1}"]["static"] is False   # yalniz secilen adaptor


def test_apply_validates_and_requires_adapter_and_known_doh(ps):
    with pytest.raises(AuxyError):
        dns.apply("1.1.1.1;calc", [12], run=ps, read=ps.read)
    with pytest.raises(AuxyError, match="bağdaştırıcısı"):
        dns.apply("google", [], run=ps, read=ps.read)
    with pytest.raises(AuxyError, match="DoH"):
        dns.apply("192.168.1.1", [12], doh=True, run=ps, read=ps.read)
    assert ps.calls == []                                   # gecersiz girdi PowerShell'e HIC gitmez


def test_apply_failure_is_reported(ps):
    def failing(command, env=None, timeout=60):
        return 1, "", "Access denied"

    with pytest.raises(AuxyError, match="Access denied"):
        dns.apply("google", [12], run=failing, read=ps.read)


def test_reset_restores_static_original_else_automatic(ps, tmp_path):
    ps.adapters[1] = dns.Adapter(7, "Ethernet", "y", "{G2}", "ethernet", ("10.0.0.5",), (), True)   # elle
    dns.apply("quad9", [12, 7], run=ps, read=ps.read)
    ps.adapters = [dns.Adapter(12, "Wi-Fi", "x", "{G1}", "wifi", ("9.9.9.9",), (), True),
                   dns.Adapter(7, "Ethernet", "y", "{G2}", "ethernet", ("9.9.9.9",), (), True)]
    ps.calls.clear()
    msg = dns.reset([12, 7], run=ps, read=ps.read)
    kinds = [("apply" if "Set-DnsClientServerAddress -InterfaceIndex ([int]$i) -ServerAddresses" in c else "reset", e) for c, e in ps.calls]
    assert any(k == "reset" and e["AUXY_IDX"] == "12" for k, e in kinds)          # Wi-Fi: DHCP'ye
    assert any(k == "apply" and e["AUXY_V4"] == "10.0.0.5" for k, e in kinds)      # Ethernet: eski elle ayar
    assert "otomatik" in msg and "eski elle" in msg
    assert json.loads((tmp_path / dns.BACKUP_FILE).read_text(encoding="utf-8")) == {}   # yedek tuketildi


def test_actions_dns_op_validates_before_uac_and_routes(monkeypatch):
    elevated, direct = [], []
    monkeypatch.setattr(actions, "run_elevated", lambda args, *a, **k: elevated.append(args) or ActionResult(True, "uac"))
    monkeypatch.setattr(actions, "run_dns_op", lambda *a, **k: direct.append(a) or ActionResult(True, "ok"))
    monkeypatch.setattr(system, "is_admin", lambda: False)
    assert not actions.dns_op("apply", "bozuk;ip", [12]).ok and not actions.dns_op("apply", "google", []).ok
    assert not actions.dns_op("apply", "192.168.1.1", [12], doh=True).ok and not actions.dns_op("yok").ok
    assert elevated == []                                    # gecersiz girdi UAC'ye gitmedi
    assert actions.dns_op("apply", "google", [12, 7], doh=True, strict=True).ok
    assert elevated == [["dns", "apply", "google", "--adapters", "12,7", "--doh", "--strict"]]
    monkeypatch.setattr(system, "is_admin", lambda: True)
    actions.dns_op("flush")
    assert direct and direct[-1][0] == "flush"
    assert "dns" in cli.ELEVATED_ALLOWED and "privacy" in cli.ELEVATED_ALLOWED


def test_fetch_trace_parses_cloudflare_format():
    class R:
        def read(self):
            return b"fl=1\nip=203.0.113.9\nloc=TR\nwarp=off\n"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    t = dns.fetch_trace(opener=lambda url, timeout: R())
    assert t["ip"] == "203.0.113.9" and t["loc"] == "TR" and t["warp"] == "off"


# ---------------- gizlilik ----------------
def test_parse_mac_randomization_and_set_validation():
    text = "Wireless LAN settings\n    MAC randomization disabled on interface Wi-Fi\n    MAC randomization enabled on interface Wi-Fi 2\n"
    assert privacy.parse_mac_randomization(text) == {"Wi-Fi": False, "Wi-Fi 2": True}
    seen = []
    msg = privacy.set_mac_randomization(True, "Wi-Fi", run=lambda args: seen.append(args) or (0, ""))
    assert seen == [["wlan", "set", "randomization", "enabled=yes", "interface=Wi-Fi"]] and "açıldı" in msg
    for bad in ("", 'Wi-Fi" & calc', "a\nb"):
        with pytest.raises(AuxyError):
            privacy.set_mac_randomization(True, bad, run=lambda a: (0, ""))
    with pytest.raises(AuxyError):
        privacy.set_mac_randomization(False, "Wi-Fi", run=lambda a: (1, "hata"))


def test_privacy_flags_roundtrip_in_isolated_registry_key(monkeypatch):
    import winreg

    key = r"Software\AuxyTestM11"
    monkeypatch.setitem(privacy.FLAGS, "ad_id", (key, "Enabled", "Reklam kimliği", "x"))
    try:
        assert privacy.get_flag("ad_id") is None
        assert "kapalı" in privacy.set_flag("ad_id", False) and privacy.get_flag("ad_id") is False
        privacy.set_flag("ad_id", True)
        assert privacy.get_flag("ad_id") is True
    finally:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
        except OSError:
            pass
    with pytest.raises(AuxyError):
        privacy.set_flag("yok", True)


def test_privacy_op_routing(monkeypatch):
    elevated = []
    monkeypatch.setattr(actions, "run_elevated", lambda args, *a, **k: elevated.append(args) or ActionResult(True, "uac"))
    monkeypatch.setattr(system, "is_admin", lambda: False)
    monkeypatch.setattr(privacy, "set_flag", lambda k, on: f"{k}:{on}")
    assert actions.privacy_op("ad_id-off").message == "ad_id:False" and elevated == []   # HKCU: UAC yok
    assert actions.privacy_op("tailored-on").message == "tailored:True"
    actions.privacy_op("mac-on", "Wi-Fi")
    assert elevated == [["privacy", "mac-on", "Wi-Fi"]]
    assert not actions.privacy_op("mac-on", 'x"y').ok and not actions.privacy_op("yok").ok


# ---------------- Tor ----------------
@pytest.fixture
def torhome(monkeypatch, tmp_path):
    monkeypatch.setenv("AUXY_HOME", str(tmp_path))
    monkeypatch.setattr(system, "is_admin", lambda: False)
    return tmp_path


def make_bundle(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_parse_sums_and_urls():
    h = "a" * 64
    text = f"{h}  tor-expert-bundle-windows-x86_64-1.2.3.tar.gz\n{'b' * 64}  other.tar.gz\n"
    assert tor.parse_sums(text, "tor-expert-bundle-windows-x86_64-1.2.3.tar.gz") == h
    with pytest.raises(AuxyError):
        tor.parse_sums(text, "yok.tar.gz")
    assert tor.bundle_url("1.2.3") == "https://dist.torproject.org/torbrowser/1.2.3/tor-expert-bundle-windows-x86_64-1.2.3.tar.gz"
    with pytest.raises(AuxyError, match="dist.torproject.org"):
        tor._fetch("https://evil.example/tor.tar.gz")


def test_latest_version_picks_newest_stable_and_falls_back():
    html = b'<a href="14.5.8/">x</a><a href="15.0.24/">x</a><a href="15.0.20/">x</a><a href="16.0a13/">alpha</a>'
    assert tor.latest_version(lambda url: html) == "15.0.24"
    assert tor.latest_version(lambda url: (_ for _ in ()).throw(OSError("ag yok"))) == tor.DEFAULT_VERSION
    assert tor.latest_version(lambda url: b"<html></html>") == tor.DEFAULT_VERSION


def test_install_verifies_sha256_extracts_and_records_version(torhome):
    bundle = make_bundle({"tor/tor.exe": b"MZ", "tor/geoip": b"x"})
    name = "tor-expert-bundle-windows-x86_64-9.9.9.tar.gz"
    sums = f"{hashlib.sha256(bundle).hexdigest()}  {name}\n".encode()

    def fetch(url, timeout=30):
        return sums if url.endswith("sha256sums-signed-build.txt") else bundle

    msgs = []
    out = tor.install("9.9.9", progress=msgs.append, fetch=fetch)
    assert "9.9.9" in out and tor.tor_exe().name == "tor.exe" and tor.installed_version() == "9.9.9"
    assert any("indiriliyor" in m for m in msgs) and not list(tor.home().glob("*.tar.gz"))   # gecici dosya temiz


def test_install_rejects_wrong_hash_and_leaves_nothing(torhome):
    bundle = make_bundle({"tor/tor.exe": b"MZ"})
    name = "tor-expert-bundle-windows-x86_64-9.9.9.tar.gz"

    def fetch(url, timeout=30):
        return f"{'0' * 64}  {name}\n".encode() if url.endswith(".txt") else bundle

    with pytest.raises(AuxyError, match="SHA-256 uyuşmuyor"):
        tor.install("9.9.9", fetch=fetch)
    assert tor.tor_exe() is None and not (tor.home() / "bundle").exists()


def test_install_refused_as_admin_and_missing_tor_exe(torhome, monkeypatch):
    monkeypatch.setattr(system, "is_admin", lambda: True)
    with pytest.raises(AuxyError, match="yönetici"):
        tor.install("9.9.9", fetch=lambda *a, **k: b"")
    with pytest.raises(AuxyError, match="yönetici"):
        tor.start()
    monkeypatch.setattr(system, "is_admin", lambda: False)
    bundle = make_bundle({"tor/readme.txt": b"x"})
    name = "tor-expert-bundle-windows-x86_64-9.9.9.tar.gz"
    fetch = lambda url, timeout=30: (f"{hashlib.sha256(bundle).hexdigest()}  {name}\n".encode() if url.endswith(".txt") else bundle)  # noqa: E731
    with pytest.raises(AuxyError, match="tor.exe bulunamadı"):
        tor.install("9.9.9", fetch=fetch)


def test_safe_extract_blocks_traversal_links_and_devices(tmp_path):
    evil = make_bundle({"../kacak.txt": b"x"})
    arc = tmp_path / "e.tar.gz"
    arc.write_bytes(evil)
    with pytest.raises(AuxyError, match="geçersiz yol"):
        tor.safe_extract(arc, tmp_path / "out")
    assert not (tmp_path / "kacak.txt").exists()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo("link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tar.addfile(info)
    arc.write_bytes(buf.getvalue())
    with pytest.raises(AuxyError, match="izin verilmeyen"):
        tor.safe_extract(arc, tmp_path / "out2")


def test_torrc_direct_and_with_validated_bridges(torhome):
    plain = tor.build_torrc()
    assert "SocksPort 127.0.0.1:9050" in plain and "ControlPort 127.0.0.1:9051" in plain and "UseBridges" not in plain
    assert "CookieAuthentication 1" in plain and "ClientOnly 1" in plain
    pt = torhome / "bundle" / "pluggable_transports"
    pt.mkdir(parents=True)
    (pt / "lyrebird.exe").write_bytes(b"MZ")
    rc = tor.build_torrc(bridges=["Bridge obfs4 192.0.2.1:443 ABCDEF cert=xyz iat-mode=0"], pt_dir=torhome / "bundle")
    assert "UseBridges 1" in rc and "ClientTransportPlugin obfs4 exec" in rc and "lyrebird.exe" in rc
    assert "Bridge obfs4 192.0.2.1:443 ABCDEF cert=xyz iat-mode=0" in rc and "Bridge Bridge" not in rc
    for bad in ("obfs4 1.2.3.4:1\nExecStart evil", "obfs4 $(calc)", "x" * 700, ""):
        with pytest.raises(AuxyError):
            tor.build_torrc(bridges=[bad])


def test_bridge_lines_read_from_pt_config(torhome):
    cfg = tor.bundle_dir() / "pluggable_transports"
    cfg.mkdir(parents=True)
    (cfg / "pt_config.json").write_text(json.dumps({"bridges": {"obfs4": ["obfs4 1.2.3.4:443 AAAA cert=c"], "snowflake": []}}),
                                        encoding="utf-8")
    assert tor.bridge_lines("obfs4") == ["obfs4 1.2.3.4:443 AAAA cert=c"] and tor.bridge_lines("snowflake") == []
    assert tor.bridge_lines("meek") == []


def test_parse_bootstrap_lines():
    lines = ['250-status/bootstrap-phase=NOTICE BOOTSTRAP PROGRESS=85 TAG=ap_conn SUMMARY="Connecting to a relay"', "250 OK"]
    assert tor.parse_bootstrap(lines) == (85, "Connecting to a relay")
    assert tor.parse_bootstrap(["250 OK"]) == (0, "")


def test_status_not_installed_stopped_and_running(torhome, monkeypatch):
    assert tor.status() == tor.TorStatus(False)
    exe = torhome / "tor" / "bundle" / "tor"
    (torhome / "tor" / "bundle").mkdir(parents=True)
    (torhome / "tor" / "bundle" / "tor.exe").write_bytes(b"MZ")
    st = tor.status()
    assert st.installed and not st.running                                   # kontrol cerezi yok: calismiyor
    monkeypatch.setattr(tor, "_control", lambda cmds, **k: ['250-status/bootstrap-phase=NOTICE BOOTSTRAP PROGRESS=100 TAG=done SUMMARY="Done"', "250 OK"])
    st = tor.status()
    assert st.running and st.bootstrap == 100 and st.summary == "Done"
    del exe


def test_system_proxy_set_and_restore_with_backup(torhome, monkeypatch):
    import winreg

    key = r"Software\AuxyTestProxyM11"
    monkeypatch.setattr(tor, "INET_KEY", key)
    monkeypatch.setattr(tor, "_notify_proxy_change", lambda: None)
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "ProxyEnable", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(k, "ProxyServer", 0, winreg.REG_SZ, "kurum:8080")
        assert "Tor'a ayarlandı" in tor.set_system_proxy(True)
        assert tor.get_system_proxy() == (True, "socks=127.0.0.1:9050") and tor.system_proxy_is_tor()
        tor.set_system_proxy(True)                                            # ikinci acis yedegi ezmez
        assert "eski haline" in tor.set_system_proxy(False)
        assert tor.get_system_proxy() == (True, "kurum:8080") and not tor.system_proxy_is_tor()
        assert "zaten" in tor.set_system_proxy(False)
    finally:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
        except OSError:
            pass


def test_socks5_connect_sends_hostname_to_proxy_not_local_dns():
    import socket
    import threading

    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    got = {}

    def serve():
        c, _ = srv.accept()
        got["hello"] = c.recv(3)
        c.sendall(b"\x05\x00")
        got["req"] = c.recv(64)
        c.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
        c.close()

    th = threading.Thread(target=serve, daemon=True)
    th.start()
    s = tor.socks5_connect("check.torproject.org", 443, ("127.0.0.1", srv.getsockname()[1]), timeout=3)
    s.close()
    th.join(3)
    srv.close()
    assert got["hello"] == b"\x05\x01\x00"
    assert got["req"][:4] == b"\x05\x01\x00\x03" and b"check.torproject.org" in got["req"] and got["req"].endswith(b"\x01\xbb")


# ---------------- CLI ----------------
def test_cli_dns_status_bench_and_tor_status(monkeypatch, capsys):
    a = dns.Adapter(12, "Wi-Fi", "x", "{G}", "wifi", ("192.168.1.1",), (), False)
    monkeypatch.setattr(dns, "read_adapters", lambda run=None: [a])
    monkeypatch.setattr(dns, "benchmark", lambda extra=None, **k: [dns.BenchResult("1.1.1.1", "Cloudflare", 20.0, 0, 12, 9.0, False),
                                                                  dns.BenchResult("192.168.1.1", "Şu anki", 90.0, 0, 12, None, True)])
    assert cli.main(["dns", "status"]) == 0 and "Wi-Fi" in capsys.readouterr().out
    assert cli.main(["dns", "bench"]) == 0
    out = capsys.readouterr().out
    assert "sahte yanıt" in out and "443 kapalı" in out and "En iyi: Cloudflare" in out
    monkeypatch.setattr(tor, "status", lambda: tor.TorStatus(False))
    assert cli.main(["tor", "status"]) == 0 and "kurulu değil" in capsys.readouterr().out
    monkeypatch.setattr(privacy, "get_flag", lambda k: False)
    monkeypatch.setattr(privacy, "read_mac_randomization", lambda run=None: {"Wi-Fi": True})
    assert cli.main(["privacy", "status"]) == 0 and "Rastgele MAC (Wi-Fi): açık" in capsys.readouterr().out


# ---------------- sayfa ----------------
@pytest.fixture
def ppage(app, monkeypatch):
    from auxy.gui import privacy_page

    page = app.pages["privacy"]
    calls, answers = [], {"yes": True}
    monkeypatch.setattr(privacy_page.messagebox, "askyesno", lambda *a, **k: answers["yes"])
    monkeypatch.setattr(actions, "dns_op", lambda op, value="", adapters=None, doh=False, strict=False:
                        calls.append(("dns", op, value, tuple(adapters or ()), doh, strict)) or ActionResult(True, f"{op} tamam", True))
    monkeypatch.setattr(actions, "privacy_op", lambda op, value="": calls.append(("privacy", op, value)) or ActionResult(True, "ok", True))
    monkeypatch.setattr(page, "refresh", lambda: None)
    page.calls, page.answers = calls, answers
    page._show_dns(([dns.Adapter(12, "Wi-Fi", "x", "{G}", "wifi", ("10.0.0.1",), (), False),
                     dns.Adapter(7, "Ethernet", "y", "{H}", "ethernet", ("10.0.0.2",), (), True)],
                    __import__("auxy.core.netservices", fromlist=["x"]).ServiceInfo(False)), None)
    return page


def test_page_lists_adapters_and_applies_selected_with_confirmation(app, ppage):
    assert set(ppage.adapter_vars) == {12, 7}
    ppage.adapter_vars[7].set(False)
    ppage.preset_menu.set(dns.PRESETS["quad9"].name)
    ppage.doh_sw.select()
    ppage._doh_changed()
    ppage.strict_sw.select()
    ppage.answers["yes"] = False
    ppage.apply_dns()
    app.update()
    assert ppage.calls == []                                                   # onay yok: uygulanmaz
    ppage.answers["yes"] = True
    ppage.apply_dns()
    assert pump(app, lambda: ppage.calls == [("dns", "apply", "quad9", (12,), True, True)])


def test_page_requires_adapter_and_validates_custom_doh(app, ppage):
    for v in ppage.adapter_vars.values():
        v.set(False)
    ppage.apply_dns()
    assert "En az bir ağ" in ppage.message.cget("text") and ppage.calls == []
    ppage.preset_menu.set("Özel…")
    ppage._preset_changed("Özel…")
    ppage.custom_entry.insert(0, "192.168.1.1")
    ppage.doh_sw.select()
    ppage._sync_doh()                                                          # bilinmeyen DNS: DoH kapanir
    assert ppage.doh_sw.get() == 0 and str(ppage.strict_sw.cget("state")) == "disabled"
    assert ppage.chosen_value() == "192.168.1.1"
    ppage.custom_entry.delete(0, "end")
    ppage.preset_menu.set(dns.PRESETS["cloudflare"].name)
    ppage._preset_changed(dns.PRESETS["cloudflare"].name)


def test_page_shows_gdpi_redirect_warning(ppage):
    from auxy.core import netservices

    gd = netservices.ServiceInfo(True, "running", "auto", r"C:\x\g.exe", "-5 --dns-addr 77.88.8.8 --dns-port 1253")
    ppage._show_dns(([], gd), None)
    assert "GoodbyeDPI" in ppage.dns_warn.cget("text") and "Bağlı fiziksel ağ yok" in ppage.dns_current.cget("text")
    ppage._show_dns(([], netservices.ServiceInfo(True, "stopped", "auto", r"C:\x\g.exe", "-5 --dns-addr 1.1.1.1")), None)
    assert ppage.dns_warn.cget("text") == ""


def test_page_bench_results_and_use_best(app, ppage):
    res = [dns.BenchResult("9.9.9.9", "Quad9 (9.9.9.9)", 25.0, 0, 12, 10.0, False),
           dns.BenchResult("10.0.0.1", "Şu anki (Wi-Fi)", 80.0, 0, 12, None, True)]
    ppage._bench_done(res, None)
    assert "En iyi: Quad9" in ppage.bench_note.cget("text") and str(ppage.use_best_btn.cget("state")) == "normal"
    assert len(ppage.bench_frame.winfo_children()) == 2 * 3
    ppage.use_best()
    assert ppage.preset_menu.get() == dns.PRESETS["quad9"].name
    ppage._bench_done([dns.BenchResult("10.0.0.1", "x", None, 12, 12, None, None)], None)
    assert "Güvenilir sonuç bulunamadı" in ppage.bench_note.cget("text") and str(ppage.use_best_btn.cget("state")) == "disabled"


def test_page_privacy_toggles_route_actions(app, ppage):
    ppage._show_privacy(({"ad_id": False, "tailored": None}, {"Wi-Fi": False}), None)
    assert ppage.privacy_sw["ad_id"].get() == 0 and ppage.privacy_sw["tailored"].get() == 1   # kayit yok: varsayilan acik
    ppage.privacy_sw["ad_id"].select()
    ppage._toggle_flag("ad_id")
    ppage.mac_switches["Wi-Fi"].select()
    ppage._toggle_mac("Wi-Fi")
    assert pump(app, lambda: ("privacy", "ad_id-on", "") in ppage.calls and ("privacy", "mac-on", "Wi-Fi") in ppage.calls)


def test_page_tor_states(ppage):
    ppage._show_tor(tor.TorStatus(False), None)
    assert "Kurulu değil" in ppage.tor_state.cget("text") and ppage.tor_install_btn.winfo_manager() == "pack"
    assert str(ppage.tor_start_btn.cget("state")) == "disabled"
    ppage._show_tor(tor.TorStatus(True, False, 0, "", "15.0.24"), None)
    assert "Durdu" in ppage.tor_state.cget("text") and str(ppage.tor_start_btn.cget("state")) == "normal"
    assert not ppage.tor_install_btn.winfo_manager() and str(ppage.verify_btn.cget("state")) == "disabled"
    ppage._show_tor(tor.TorStatus(True, True, 100, "Done", "15.0.24"), None, polling=True)
    assert "Bağlı" in ppage.tor_state.cget("text") and str(ppage.verify_btn.cget("state")) == "normal"
    assert str(ppage.proxy_sw.cget("state")) == "normal"
    ppage._show_tor(tor.TorStatus(True, True, 40, "Loading", "15.0.24"), None, polling=True)
    assert "%40" in ppage.tor_state.cget("text") and str(ppage.newnym_btn.cget("state")) == "disabled"


def test_page_tor_install_needs_confirmation_and_start_needs_bridge(app, ppage, monkeypatch):
    installed = []
    monkeypatch.setattr(tor, "install", lambda *a, **k: installed.append(1) or "kuruldu")
    ppage.answers["yes"] = False
    ppage.tor_install()
    app.update()
    assert installed == []
    ppage.answers["yes"] = True
    ppage.tor_install()
    assert pump(app, lambda: installed == [1])
    monkeypatch.setattr(tor, "bridge_lines", lambda kind: [])
    ppage.bridge_menu.set("obfs4 köprüsü")
    ppage.tor_start()
    assert "köprü bulunamadı" in ppage.message.cget("text")
    ppage.bridge_menu.set("Doğrudan bağlan")


def test_nav_has_privacy_page(app):
    from auxy.gui import app as gui

    keys = [k for k, _ in gui.NAV]
    assert keys.index("privacy") == keys.index("network") + 1 and dict(gui.NAV)["privacy"] == "DNS ve gizlilik"
    assert "privacy" in app.pages
