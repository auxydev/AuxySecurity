"""Aga bagli DNS kurali: gercek ag/DNS degisikligi YOK; bagdastiricilar ve PowerShell sahte nesnelerle verilir."""

import json

import pytest

from auxy.core import dns, dnsscope
from auxy.core.service import AuxyError


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("AUXY_HOME", str(tmp_path))
    return tmp_path


def adapter(index=23, network="EvWifi", v4=(), v6=(), static=False, guid="{G}"):
    return dns.Adapter(index, "Wi-Fi", "Intel Wi-Fi", guid, "wifi", tuple(v4), tuple(v6), static, network)


RULE = dnsscope.Rule(True, "cloudflare", False, False, ["EvWifi"])
CF4, CF6 = ("1.1.1.1", "1.0.0.1"), ("2606:4700:4700::1111", "2606:4700:4700::1001")
never_ours = lambda guid: False


# ---------------- plan ----------------
def test_trusted_network_gets_dns_untrusted_returns_to_dhcp():
    steps = dnsscope.plan(RULE, [adapter(network="EvWifi")], never_ours)
    assert [s.op for s in steps] == ["apply"]
    # kampus agi: elle atanmis Cloudflare -> otomatige don (giris sayfasi icin)
    steps = dnsscope.plan(RULE, [adapter(network="ASUNET_Ogrenci", v4=CF4, static=True)], never_ours)
    assert [s.op for s in steps] == ["reset"]
    assert "ASUNET_Ogrenci" in steps[0].describe(RULE)


def test_no_step_when_already_correct():
    assert dnsscope.plan(RULE, [adapter(network="EvWifi", v4=CF4, v6=CF6, static=True)], never_ours) == []
    assert dnsscope.plan(RULE, [adapter(network="ASUNET_Ogrenci", v4=("10.0.0.1",))], never_ours) == []


def test_untrusted_network_leaves_foreign_manual_dns_alone_unless_we_set_it():
    other = adapter(network="Kafe", v4=("9.9.9.9",), static=True)
    assert dnsscope.plan(RULE, [other], never_ours) == []
    assert [s.op for s in dnsscope.plan(RULE, [other], lambda g: True)] == ["reset"]


def test_network_names_case_insensitive_and_unknown_network_skipped():
    assert [s.op for s in dnsscope.plan(RULE, [adapter(network="evwifi")], never_ours)] == ["apply"]
    assert dnsscope.plan(RULE, [adapter(network="", v4=CF4, static=True)], never_ours) == []  # baglaniyor


def test_disabled_or_empty_rule_does_nothing():
    a = adapter(network="ASUNET_Ogrenci", v4=CF4, static=True)
    assert dnsscope.plan(dnsscope.Rule(False, "cloudflare", networks=["EvWifi"]), [a], never_ours) == []
    assert dnsscope.plan(dnsscope.Rule(True, "cloudflare", networks=[]), [a], never_ours) == []


# ---------------- enforce ----------------
def test_enforce_calls_apply_and_reset_per_adapter(monkeypatch):
    monkeypatch.setattr(dns, "changed_by_us", lambda guid: False)
    calls = []
    adapters = [adapter(23, "EvWifi"), adapter(7, "ASUNET_Ogrenci", v4=CF4, static=True, guid="{E}")]
    msgs = dnsscope.enforce(dnsscope.Rule(True, "cloudflare", True, True, ["EvWifi"]), read=lambda: adapters,
                            apply=lambda *a: calls.append(("apply", *a)), reset=lambda *a: calls.append(("reset", *a)))
    assert calls == [("apply", "cloudflare", [23], True, True), ("reset", [7])]
    assert len(msgs) == 2


def test_enforce_reads_saved_rule_and_skips_when_disabled():
    dnsscope.save(dnsscope.Rule(False, "cloudflare", networks=["EvWifi"]))
    assert dnsscope.enforce(read=lambda: pytest.fail("kural kapaliyken ag okunmamali")) == []


# ---------------- kayit / dogrulama ----------------
def test_save_load_roundtrip_dedupes_and_sanitizes(home):
    dnsscope.save(dnsscope.Rule(True, " quad9 ", False, True, ["Ev", "ev", " ", "Is"]))
    rule = dnsscope.load()
    assert rule == dnsscope.Rule(True, "quad9", False, False, ["Ev", "Is"])  # strict DoH olmadan anlamsiz
    (home / dnsscope.SCOPE_FILE).write_text("{bozuk", encoding="utf-8")
    assert dnsscope.load() == dnsscope.Rule()
    (home / dnsscope.SCOPE_FILE).write_text(json.dumps({"enabled": True, "networks": "x"}), encoding="utf-8")
    assert dnsscope.load().networks == []


def test_validate_requires_value_networks_and_doh_template():
    with pytest.raises(AuxyError):
        dnsscope.validate(dnsscope.Rule(True, "", networks=["Ev"]))
    with pytest.raises(AuxyError):
        dnsscope.validate(dnsscope.Rule(True, "cloudflare", networks=[]))
    with pytest.raises(AuxyError):
        dnsscope.validate(dnsscope.Rule(True, "192.168.1.1", doh=True, networks=["Ev"]))
    assert dnsscope.validate(dnsscope.Rule(False)).enabled is False


# ---------------- dns.py degisiklikleri ----------------
def test_read_adapters_parses_network_name():
    out = json.dumps([{"index": 23, "name": "Wi-Fi", "description": "Intel", "guid": "{G}", "media": "Native 802.11",
                       "v4": ["1.1.1.1"], "v6": [], "static": True, "network": "ASUNET_Ogrenci"}])
    (a,) = dns.read_adapters(run=lambda *a, **k: (0, out, ""))
    assert a.network == "ASUNET_Ogrenci" and a.kind == "wifi" and a.static
    (b,) = dns.read_adapters(run=lambda *a, **k: (0, out.replace(', "network": "ASUNET_Ogrenci"', ""), ""))
    assert b.network == ""


def test_reset_script_forces_dhcp_with_netsh():
    # -ResetServerAddresses gercek makinede etkisiz kaldi; netsh source=dhcp kalici cozum
    assert "netsh interface ipv4 set dnsservers name=$n source=dhcp" in dns._RESET_PS
    assert "netsh interface ipv6 set dnsservers name=$n source=dhcp" in dns._RESET_PS


def test_changed_by_us_uses_backup(home):
    assert dns.changed_by_us("{G}") is False
    (home / dns.BACKUP_FILE).write_text(json.dumps({"{G}": {"static": False}}), encoding="utf-8")
    assert dns.changed_by_us("{G}") is True
