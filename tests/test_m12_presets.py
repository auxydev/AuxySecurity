"""Ön ayarlar: plan mantigi saf (sahte durum), uygulama enjekte edilen sahte yurutuculerle; gercek ayar DEGISMEZ."""

import time

import pytest

from auxy import __main__ as cli
from auxy.core import actions, dns, netservices, presets, privacy, system, tor
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


def adapter(idx=12, name="Wi-Fi", v4=("192.168.1.1",)):
    return dns.Adapter(idx, name, "x", f"{{G{idx}}}", "wifi", tuple(v4), (), False)


def make_state(**kw):
    base = dict(adapters=(adapter(),), warp=netservices.WarpInfo(True, "Disconnected", "", "doh", "MASQUE", True),
                flags={"ad_id": True, "tailored": None}, macs={"Wi-Fi": False},
                tor=tor.TorStatus(True, False, 0, "", "15.0.24"), tor_proxy=False,
                gdpi=netservices.ServiceInfo(False), fw={"fw_domain": "on", "fw_private": "on", "fw_public": "off"}, active="")
    base.update(kw)
    return presets.State(**base)


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("AUXY_HOME", str(tmp_path))


def kinds(plan):
    return [(c.kind, c.target) for c in plan.changes]


# ---------------- plan ----------------
def test_catalog_is_consistent():
    assert set(presets.PRESETS) == set(presets.SPECS) == {"hiz", "guvenilir", "gizli", "tor", "yurt"}
    for key, info in presets.PRESETS.items():
        assert info.name and info.tagline and info.bullets, key


def test_speed_uses_measured_best_dns_and_turns_off_warp_and_tor():
    st = make_state(warp=netservices.WarpInfo(True, "Connected", "", "warp", "MASQUE", True),
                    tor=tor.TorStatus(True, True, 100, "Done", "x"), tor_proxy=True)
    plan = presets.build_plan("hiz", st, ("google", "Google (8.8.8.8) (22 ms)"))
    assert ("dns", "google") in kinds(plan) and ("warp-conn", "disconnect") in kinds(plan)
    assert ("tor", "stop") in kinds(plan) and ("tor-proxy", "off") in kinds(plan)
    dns_change = next(c for c in plan.changes if c.kind == "dns")
    assert dns_change.admin and dns_change.extra == (False, False) and "şifreli" not in dns_change.after   # hiz: DoH yok
    assert plan.needs_admin


def test_speed_without_reliable_measurement_leaves_dns_alone():
    plan = presets.build_plan("hiz", make_state(), ("", "Güvenilir ölçüm yok"))
    assert not any(c.kind == "dns" for c in plan.changes) and any("DNS:" in n for n in plan.notes)


def test_reliable_sets_quad9_doh_nonstrict_and_enables_only_disabled_firewall_profiles():
    plan = presets.build_plan("guvenilir", make_state())
    d = next(c for c in plan.changes if c.kind == "dns")
    assert d.target == "quad9" and d.extra == (True, False)                     # sifreli ama sifresize dusebilir (kopma yok)
    assert [c.target for c in plan.changes if c.kind == "fw"] == ["fw_public"]  # yalniz kapali olan
    assert all(c.admin for c in plan.changes if c.kind in ("dns", "fw"))
    assert not any(c.kind.startswith("warp") for c in plan.changes)              # WARP'a dokunmaz


def test_private_changes_everything_it_promises():
    plan = presets.build_plan("gizli", make_state())
    d = next(c for c in plan.changes if c.kind == "dns")
    assert d.target == "cloudflare" and d.extra == (True, True)                  # sifreli + siki
    ks = kinds(plan)
    assert ("warp-mode", "warp+doh") in ks and ("warp-conn", "connect") in ks
    assert ("flag", "ad_id") in ks and ("mac", "Wi-Fi") in ks
    assert ("flag", "tailored") in ks                                           # kayit yok = Windows'ta acik -> kapatilir
    assert not any(c.kind == "tor" for c in plan.changes)


def test_tor_preset_adds_tor_and_proxy_or_notes_missing_install():
    plan = presets.build_plan("tor", make_state())
    assert ("tor", "start") in kinds(plan) and ("tor-proxy", "on") in kinds(plan)
    plan = presets.build_plan("tor", make_state(tor=tor.TorStatus(False)))
    assert not any(c.kind == "tor" for c in plan.changes) and any("Tor kurulu değil" in n for n in plan.notes)


def test_dorm_preset_forces_warp_tunnel_and_picks_best():
    plan = presets.build_plan("yurt", make_state(), ("quad9", "Quad9 (31 ms)"))
    assert ("dns", "quad9") in kinds(plan) and ("warp-mode", "warp") in kinds(plan) and ("warp-conn", "connect") in kinds(plan)
    assert next(c for c in plan.changes if c.kind == "dns").extra == (True, False)


def test_already_applied_values_are_skipped():
    st = make_state(adapters=(adapter(v4=("1.1.1.1", "1.0.0.1")),), flags={"ad_id": False, "tailored": False},
                    macs={"Wi-Fi": True}, warp=netservices.WarpInfo(True, "Connected", "", "warp+doh", "MASQUE", True))
    presets.save_record({"active": "gizli", "dns_doh": "cloudflare"})
    plan = presets.build_plan("gizli", make_state(**{**st.__dict__, "active": "gizli"}))
    assert plan.changes == [] and any("zaten" in n for n in plan.notes)


def test_missing_warp_adapter_and_wifi_are_skipped_with_notes():
    st = make_state(warp=netservices.WarpInfo(False), adapters=(), macs={})
    plan = presets.build_plan("gizli", st)
    text = " ".join(plan.notes)
    assert "WARP kurulu değil" in text and "DNS adımı atlandı" in text and "rastgele MAC atlandı" in text
    assert not any(c.kind in ("dns", "mac", "warp-mode", "warp-conn") for c in plan.changes)


def test_warnings_for_warp_dns_override_and_gdpi_redirect():
    st = make_state(warp=netservices.WarpInfo(True, "Connected", "", "warp", "MASQUE", True),
                    gdpi=netservices.ServiceInfo(True, "running", "auto", r"C:\g.exe", "-5 --dns-addr 77.88.8.8"))
    plan = presets.build_plan("guvenilir", st)
    joined = " ".join(plan.warnings)
    assert "WARP bağlıyken" in joined and "GoodbyeDPI" in joined
    assert presets.build_plan("hiz", st, ("google", "g")).warnings[0].startswith("GoodbyeDPI")   # hiz WARP'i kapatir: o uyari yok


def test_unknown_preset_and_describe_text():
    with pytest.raises(AuxyError):
        presets.build_plan("yok", make_state())
    text = presets.describe(presets.build_plan("gizli", make_state()))
    assert "'En gizli bağlantı' şunları değiştirecek" in text and "→" in text and "tek bir UAC" in text and "geri alabilirsin" in text


# ---------------- uygulama ----------------
class Recorder:
    def __init__(self, ok=True):
        self.calls, self.ok = [], ok

    def __call__(self, **kw):
        self.calls.append(kw)
        return ActionResult(self.ok, "tamam" if self.ok else "reddedildi", True)


@pytest.fixture
def steps(monkeypatch):
    log = []
    monkeypatch.setattr(netservices, "warp_op", lambda op, value="", cli=None: log.append(("warp", op, value)) or netservices.NetResult(True, f"{op} ok", True))
    monkeypatch.setattr(privacy, "set_flag", lambda k, on: log.append(("flag", k, on)) or f"{k}:{on}")
    monkeypatch.setattr(tor, "start", lambda bridges=None: log.append(("tor", "start")) or "başladı")
    monkeypatch.setattr(tor, "stop", lambda: log.append(("tor", "stop")) or "durdu")
    monkeypatch.setattr(tor, "set_system_proxy", lambda on, port=9050: log.append(("proxy", on)) or "ok")
    return log


def test_execute_batches_all_admin_steps_into_one_call_and_runs_the_rest(steps):
    st = make_state()
    plan = presets.build_plan("gizli", st)
    admin = Recorder()
    results = presets.execute(plan, st, admin)
    assert len(admin.calls) == 1                                               # TEK UAC
    call = admin.calls[0]
    assert call["dns"] == "cloudflare" and call["adapters"] == [12] and call["doh"] and call["strict"]
    assert call["macs_on"] == ["Wi-Fi"] and call["macs_off"] == [] and call["fw_on"] == []
    assert ("warp", "mode", "warp+doh") in steps and ("warp", "connect", "") in steps
    assert ("flag", "ad_id", False) in steps and ("flag", "tailored", False) in steps
    assert all(r.ok for r in results) and presets.summarize(results)[0]
    rec = presets.load_record()
    assert rec["active"] == "gizli" and rec["dns_doh"] == "cloudflare" and rec["previous"]["macs"] == {"Wi-Fi": False}


def test_execute_continues_after_a_failed_step_and_reports_it(steps, monkeypatch):
    monkeypatch.setattr(privacy, "set_flag", lambda k, on: (_ for _ in ()).throw(AuxyError("kayıt defteri hatası")))
    st = make_state()
    results = presets.execute(presets.build_plan("gizli", st), st, Recorder())
    ok, msg = presets.summarize(results)
    assert not ok and "kayıt defteri hatası" in msg and any(r.ok for r in results)
    assert ("warp", "connect", "") in steps                                      # sonraki adimlar yine calisti


def test_denied_uac_marks_admin_steps_failed_but_runs_non_admin_steps(steps):
    st = make_state()
    results = presets.execute(presets.build_plan("gizli", st), st, Recorder(ok=False))
    failed = [r.label for r in results if not r.ok]
    assert "DNS sunucusu" in failed and "Rastgele MAC (Wi-Fi)" in failed
    assert ("flag", "ad_id", False) in steps


def test_nothing_to_do_returns_friendly_result(steps):
    st = make_state(adapters=(), warp=netservices.WarpInfo(False), macs={}, flags={"ad_id": False, "tailored": False})
    plan = presets.build_plan("gizli", st)
    assert plan.changes == []
    assert presets.execute(plan, st, Recorder())[0].message == "Değişecek bir şey yoktu."
    assert presets.load_record() == {}                                           # kayit yazilmaz


def test_revert_restores_previous_state_once_and_clears_record(steps):
    before = make_state(warp=netservices.WarpInfo(True, "Disconnected", "", "doh", "MASQUE", True))
    presets.execute(presets.build_plan("tor", before), before, Recorder())
    steps.clear()
    after = make_state(adapters=(adapter(v4=("1.1.1.1", "1.0.0.1")),), flags={"ad_id": False, "tailored": False},
                       macs={"Wi-Fi": True}, tor=tor.TorStatus(True, True, 100, "Done", "x"), tor_proxy=True,
                       warp=netservices.WarpInfo(True, "Connected", "", "warp+doh", "MASQUE", True))
    rp = presets.revert_plan(after)
    ks = kinds(rp)
    assert ("dns", "") in ks and ("flag", "ad_id") in ks and ("mac", "Wi-Fi") in ks
    assert ("warp-mode", "doh") in ks and ("warp-conn", "disconnect") in ks and ("tor", "stop") in ks and ("tor-proxy", "off") in ks
    admin = Recorder()
    results = presets.execute_revert(rp, after, admin)
    assert admin.calls[0]["dns"] == "__reset__" and admin.calls[0]["macs_off"] == ["Wi-Fi"]
    assert ("flag", "ad_id", True) in steps and ("tor", "stop") in steps and ("proxy", False) in steps
    assert all(r.ok for r in results) and presets.load_record() == {}


def test_chained_presets_keep_the_original_previous_state(steps):
    original = make_state()
    presets.execute(presets.build_plan("gizli", original), original, Recorder())
    second = make_state(flags={"ad_id": False, "tailored": False}, macs={"Wi-Fi": True})
    presets.execute(presets.build_plan("guvenilir", second), second, Recorder())
    rec = presets.load_record()
    assert rec["active"] == "guvenilir" and rec["previous"]["flags"]["ad_id"] is True   # ilk (asil) durum korundu


def test_revert_without_record_is_a_noop():
    plan = presets.revert_plan(make_state())
    assert plan.changes == [] and "kaydı yok" in plan.notes[0]


def test_resolve_best_maps_to_preset_or_keeps_current():
    st = make_state()
    bench = lambda extra: [dns.BenchResult("9.9.9.9", "Quad9 (9.9.9.9)", 21.0, 0, 12, 9.0, False)]  # noqa: E731
    key, why = presets.resolve_best(st, bench)
    assert key == "quad9" and "21 ms" in why
    bench = lambda extra: [dns.BenchResult("192.168.1.1", "Şu anki (Wi-Fi)", 12.0, 0, 12, None, False)]  # noqa: E731
    key, why = presets.resolve_best(st, bench)
    assert key == "" and "değiştirilmedi" in why
    assert presets.resolve_best(st, lambda extra: [])[0] == ""


# ---------------- yonetici yardimcisi ----------------
def test_preset_admin_validates_before_uac_and_builds_one_command(monkeypatch):
    elevated = []
    monkeypatch.setattr(actions, "run_elevated", lambda args, *a, **k: elevated.append(args) or ActionResult(True, "uac"))
    monkeypatch.setattr(system, "is_admin", lambda: False)
    for kw in (dict(dns="1.1.1.1;calc", adapters=[1]), dict(dns="google", adapters=[]), dict(macs_on=['W"i']), dict(fw_on=["x"])):
        assert not actions.preset_admin(**kw).ok
    assert elevated == []
    assert actions.preset_admin(dns="quad9", adapters=[12, 7], doh=True, strict=True, macs_on=["Wi-Fi"], macs_off=["W2"],
                                fw_on=["fw_public"]).ok
    assert elevated == [["presetadmin", "--dns", "quad9", "--adapters", "12,7", "--doh", "--strict", "--mac-on", "Wi-Fi",
                         "--mac-off", "W2", "--fw-on", "fw_public"]]
    assert "presetadmin" in cli.ELEVATED_ALLOWED


def test_run_preset_admin_runs_every_part_and_aggregates_errors(monkeypatch):
    from auxy.core import winsec

    calls = []
    monkeypatch.setattr(dns, "apply", lambda v, a, d, s, **k: calls.append(("dns", v, a, d, s)) or "DNS tamam")
    monkeypatch.setattr(dns, "reset", lambda a, **k: calls.append(("reset", a)) or "sıfırlandı")
    monkeypatch.setattr(privacy, "set_mac_randomization", lambda on, n, **k: calls.append(("mac", n, on)) or f"mac {n}")

    class W:
        def set(self, key, value):
            calls.append(("fw", key, value))
            if key == "fw_domain":
                raise AuxyError("reddedildi")

    monkeypatch.setattr(winsec, "WinSecService", W)
    res = actions.run_preset_admin("cloudflare", [12], True, True, ["Wi-Fi"], ["W2"], ["fw_public", "fw_domain"])
    assert not res.ok and "reddedildi" in res.message                           # bir hata digerlerini durdurmaz
    assert ("dns", "cloudflare", [12], True, True) in calls and ("mac", "Wi-Fi", True) in calls and ("mac", "W2", False) in calls
    assert ("fw", "fw_public", "on") in calls
    assert actions.run_preset_admin("__reset__", [12]).ok and ("reset", [12]) in calls


# ---------------- CLI ----------------
def test_cli_preset_list_plan_and_apply_needs_yes(monkeypatch, capsys):
    monkeypatch.setattr(presets, "capture_state", lambda: make_state())
    monkeypatch.setattr(presets, "resolve_best", lambda st: ("google", "Google"))
    assert cli.main(["preset", "list"]) == 0 and "En iyi hız" in capsys.readouterr().out
    assert cli.main(["preset", "plan", "gizli"]) == 0 and "şunları değiştirecek" in capsys.readouterr().out
    called = []
    monkeypatch.setattr(presets, "execute", lambda *a, **k: called.append(1) or [presets.StepResult("x", True, "ok")])
    assert cli.main(["preset", "apply", "hiz"]) == 0 and called == []              # --yes yok: uygulanmaz
    assert "--yes" in capsys.readouterr().out
    assert cli.main(["preset", "apply", "hiz", "--yes"]) == 0 and called == [1]
    assert cli.main(["preset", "apply", "yok"]) == 2


# ---------------- sayfa ----------------
@pytest.fixture
def prpage(app, monkeypatch):
    from auxy.gui import presets_page

    page = app.pages["presets"]
    log, answers = [], {"yes": True}
    monkeypatch.setattr(presets_page.messagebox, "askyesno", lambda title, text, **k: log.append(("ask", title, text)) or answers["yes"])
    monkeypatch.setattr(presets, "capture_state", lambda: make_state())
    monkeypatch.setattr(presets, "resolve_best", lambda st: ("quad9", "Quad9"))
    monkeypatch.setattr(presets, "execute", lambda plan, st, runner: log.append(("exec", plan.preset)) or [presets.StepResult("x", True, "ok")])
    page.log, page.answers = log, answers
    page.refresh()
    return page


def test_page_has_a_card_per_preset_and_marks_the_active_one(prpage):
    assert set(prpage.buttons) == set(presets.PRESETS)
    assert "yok" in prpage.active_lbl.cget("text") and str(prpage.revert_btn.cget("state")) == "disabled"
    presets.save_record({"active": "gizli", "previous": {}})
    prpage.refresh()
    assert "En gizli bağlantı" in prpage.active_lbl.cget("text") and "Etkin" in prpage.buttons["gizli"].cget("text")
    assert str(prpage.revert_btn.cget("state")) == "normal"


def test_page_shows_plan_asks_confirmation_then_executes(app, prpage):
    prpage.answers["yes"] = False
    prpage.start("gizli")
    assert pump(app, lambda: any(x[0] == "ask" for x in prpage.log))
    assert pump(app, lambda: "İptal edildi" in prpage.message.cget("text"))
    assert not any(x[0] == "exec" for x in prpage.log) and not prpage.busy        # reddedildi: hicbir sey degismedi
    assert "Cloudflare" in next(x for x in prpage.log if x[0] == "ask")[2]       # plan metni kullaniciya gosterildi
    prpage.log.clear()
    prpage.answers["yes"] = True
    prpage.start("gizli")
    assert pump(app, lambda: ("exec", "gizli") in prpage.log)
    assert pump(app, lambda: "adım uygulandı" in prpage.message.cget("text"))


def test_page_blocks_double_start_and_reports_nothing_to_change(app, prpage, monkeypatch):
    prpage.busy = True
    prpage.start("hiz")
    app.update()
    assert prpage.log == []
    prpage.busy = False
    monkeypatch.setattr(presets, "capture_state", lambda: make_state(adapters=(), warp=netservices.WarpInfo(False), macs={},
                                                                     flags={"ad_id": False, "tailored": False}))
    prpage.start("gizli")
    assert pump(app, lambda: "Değişecek bir şey yok" in prpage.message.cget("text"))
    assert not any(x[0] == "ask" for x in prpage.log)


def test_page_revert_flow(app, prpage, monkeypatch):
    presets.save_record({"active": "gizli", "dns_doh": "cloudflare",
                         "previous": {"flags": {"ad_id": True}, "macs": {"Wi-Fi": False}, "warp_mode": "doh", "warp_connected": False,
                                      "tor_running": False, "tor_proxy": False, "fw": {}}})
    monkeypatch.setattr(presets, "capture_state", lambda: make_state(flags={"ad_id": False, "tailored": False}, macs={"Wi-Fi": True}))
    done = []
    monkeypatch.setattr(presets, "execute_revert", lambda plan, st, runner: done.append(plan) or [presets.StepResult("x", True, "ok")])
    prpage.revert()
    assert pump(app, lambda: bool(done))
    assert any("önceki haline döndürülecek" in x[2] for x in prpage.log if x[0] == "ask")


def test_nav_has_presets_page_second(app):
    from auxy.gui import app as gui

    assert [k for k, _ in gui.NAV][:2] == ["dashboard", "presets"] and dict(gui.NAV)["presets"] == "Ön ayarlar"
