import json
import tempfile
import time
from pathlib import Path

import pytest

from auxy import __main__ as cli
from auxy.core import actions, autostart, system
from auxy.core.service import AuxyError

REAL_SLEEP = time.sleep


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AUXY_HOME", str(tmp_path / "home"))
    import auxy.core.log as log

    monkeypatch.setattr(log, "_configured", False)
    yield
    logger = log.get_logger()
    for h in list(logger.handlers):
        h.close()
        logger.removeHandler(h)


def pump(a, cond, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        a.update()
        if cond():
            return True
        REAL_SLEEP(0.05)
    return False


# ---------------- baslangic gorevi ----------------
def test_project_dir_is_repo_root_not_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # yukseltilmis yardimcida cwd System32 gibi bir yer olurdu
    d = Path(autostart.project_dir())
    assert d.is_dir() and (d / "src" / "auxy").is_dir() and d != tmp_path


def test_install_writes_workdir_from_project_not_cwd(monkeypatch, tmp_path):
    captured = {}

    def fake_schtasks(*args):
        xml_path = args[args.index("/XML") + 1]
        captured["xml"] = Path(xml_path).read_text(encoding="utf-16")

        class R:
            returncode, stdout, stderr = 0, "", ""

        return R()

    monkeypatch.setattr(system, "is_admin", lambda: True)
    monkeypatch.setattr(autostart, "_schtasks", fake_schtasks)
    monkeypatch.chdir(tmp_path)
    autostart.install()
    assert f"<WorkingDirectory>{autostart.project_dir()}</WorkingDirectory>" in captured["xml"]
    assert str(tmp_path) not in captured["xml"]


def test_autostart_op_paths(monkeypatch):
    assert not actions.autostart_op("hack").ok
    calls = []
    monkeypatch.setattr(system, "is_admin", lambda: True)
    monkeypatch.setattr(autostart, "install", lambda: calls.append("i"))
    monkeypatch.setattr(autostart, "remove", lambda: calls.append("r"))
    assert actions.autostart_op("install").ok and actions.autostart_op("remove").ok
    assert calls == ["i", "r"]

    def boom():
        raise AuxyError("schtasks basarisiz")

    monkeypatch.setattr(autostart, "install", boom)
    r = actions.autostart_op("install")
    assert not r.ok and "schtasks" in r.message


def test_autostart_op_elevates_when_not_admin(monkeypatch):
    seen = []

    def fake(args, timeout_s=120):
        seen.append(args)
        actions.write_result(args[args.index("--result") + 1], True, "kuruldu", True)
        return 0

    monkeypatch.setattr(system, "is_admin", lambda: False)
    monkeypatch.setattr(system, "run_elevated_and_wait", fake)
    r = actions.autostart_op("install")
    assert r.ok and seen[0][:2] == ["autostart", "install"]


def test_cli_autostart_helper_mode(monkeypatch):
    out = Path(tempfile.gettempdir()) / "auxy-result-cli-autostart.json"
    try:
        # yardimci modunda yonetici alinamadiysa: sonsuz UAC dongusu yok, rc=3
        monkeypatch.setattr(system, "is_admin", lambda: False)
        assert cli.main(["autostart", "install", "--result", str(out)]) == 3
        assert json.loads(out.read_text(encoding="utf-8"))["ok"] is False
        # yonetici: eylemi yapar ve sonucu yazar
        monkeypatch.setattr(system, "is_admin", lambda: True)
        monkeypatch.setattr(actions, "autostart_op", lambda op: actions.ActionResult(True, "kuruldu", True))
        assert cli.main(["autostart", "install", "--result", str(out)]) == 0
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["ok"] is True and data["message"] == "kuruldu"
    finally:
        out.unlink(missing_ok=True)


def test_settings_switch_calls_autostart_and_reflects_real_state(app, monkeypatch):
    page = app.pages["settings"]
    calls = []
    state = {"installed": False}

    def fake_op(op):
        calls.append(op)
        state["installed"] = op == "install"
        return actions.ActionResult(True, "tamam", True)

    monkeypatch.setattr(actions, "autostart_op", fake_op)
    monkeypatch.setattr(autostart, "is_installed", lambda: state["installed"])
    from auxy.gui import settings_page

    monkeypatch.setattr(settings_page.messagebox, "askyesno", lambda *a, **k: True)  # konum riski onayi: evet
    page.autostart_sw.select()
    page._toggle_autostart()
    assert pump(app, lambda: calls == ["install"] and page.message.cget("text") == "tamam")
    assert page.autostart_sw.get() == 1
    page.autostart_sw.deselect()
    page._toggle_autostart()
    assert pump(app, lambda: calls == ["install", "remove"])
    assert pump(app, lambda: page.autostart_sw.get() == 0)


def test_settings_switch_reverts_when_uac_denied(app, monkeypatch):
    page = app.pages["settings"]
    monkeypatch.setattr(actions, "autostart_op", lambda op: actions.ActionResult(False, "Yönetici izni verilmedi."))
    monkeypatch.setattr(autostart, "is_installed", lambda: False)  # gercek durum: kurulu degil
    from auxy.gui import settings_page

    monkeypatch.setattr(settings_page.messagebox, "askyesno", lambda *a, **k: True)
    page.autostart_sw.select()
    page._toggle_autostart()
    assert pump(app, lambda: "izni verilmedi" in page.message.cget("text"))
    assert pump(app, lambda: page.autostart_sw.get() == 0)  # anahtar gercek duruma doner


# ---------------- tray: guvenlik duvari ----------------
def make_agent(monkeypatch):
    from auxy.agent import tray

    agent = tray.Agent()
    monkeypatch.setattr(agent, "refresh", lambda: None)
    agent.notes = []
    monkeypatch.setattr(agent, "_notify", lambda m: agent.notes.append(m))
    return agent


def test_tray_firewall_submenu_reflects_state(monkeypatch):
    agent = make_agent(monkeypatch)
    names = [i.text for i in agent.icon.menu.items if i.text]
    fw_item = next(i for i in agent.icon.menu.items if i.text == "Güvenlik duvarı")
    assert fw_item.enabled is False  # durum henuz okunmadi
    agent.fw = {"fw_domain": "on", "fw_private": "off", "fw_public": "on"}
    fw_item = next(i for i in agent.icon.menu.items if i.text == "Güvenlik duvarı")
    assert fw_item.enabled is True
    states = {i.text: i.checked for i in fw_item.submenu.items}
    assert states == {"Etki alanı ağı": True, "Özel ağ": False, "Genel ağ": True}
    assert "Güvenlik duvarı" in names


def test_tray_firewall_off_requires_confirmation(monkeypatch):
    agent = make_agent(monkeypatch)
    applied = []
    monkeypatch.setattr(actions, "apply_winsec", lambda k, v: applied.append((k, v)) or actions.ActionResult(True, f"→ {v}"))
    agent.fw = {"fw_public": "on"}
    monkeypatch.setattr(system, "confirm_dialog", lambda text, title="": False)
    agent._toggle_fw("fw_public")  # reddedildi
    assert applied == []
    monkeypatch.setattr(system, "confirm_dialog", lambda text, title="": True)
    agent._toggle_fw("fw_public")
    assert applied == [("fw_public", "off")]


def test_tray_firewall_on_needs_no_confirmation(monkeypatch):
    agent = make_agent(monkeypatch)
    applied = []
    monkeypatch.setattr(actions, "apply_winsec", lambda k, v: applied.append((k, v)) or actions.ActionResult(True, "ok"))

    def no_dialog(*a, **k):
        raise AssertionError("acarken onay sorulmamali")

    monkeypatch.setattr(system, "confirm_dialog", no_dialog)
    agent.fw = {"fw_private": "off"}
    agent._toggle_fw("fw_private")
    assert applied == [("fw_private", "on")]


def test_get_many_reads_only_requested_keys():
    from auxy.core import winsec

    class Env(winsec.WinEnv):
        calls = []

        def firewall_enabled(self, profile):
            Env.calls.append(profile)
            return True

        def get_reg(self, *a, **k):
            raise AssertionError("istenmeyen anahtar okundu")

    got = winsec.WinSecService(Env()).get_many(["fw_public"])
    assert got == {"fw_public": "on"} and Env.calls == ["public"]


def test_autostart_risk_dialog_shown_in_user_writable_location_and_no_means_no(app, monkeypatch):
    """Yuksek yetkili gorev kullanici-yazilabilir konumdan kurulurken uyari sorulur; HAYIR -> hicbir sey kurulmaz."""
    from auxy.core import hardening
    from auxy.gui import settings_page

    page = app.pages["settings"]
    asked, ops = [], []
    monkeypatch.setattr(hardening, "install_location_risk",
                        lambda *a, **k: hardening.LocationRisk(hardening.WARN, "risk", (r"C:\Users\x\proje",)))
    monkeypatch.setattr(settings_page.messagebox, "askyesno", lambda title, msg, **k: asked.append(msg) or False)
    monkeypatch.setattr(actions, "autostart_op", lambda op: ops.append(op) or actions.ActionResult(True, "x", True))
    monkeypatch.setattr(autostart, "is_installed", lambda: False)
    page.autostart_sw.select()
    page._toggle_autostart()
    app.update()
    assert asked and r"C:\Users\x\proje" in asked[0] and "YÜKSEK YETKİYLE" in asked[0]
    assert ops == [] and page.autostart_sw.get() == 0  # reddedildi: kurulmadi, anahtar eski halinde


def test_autostart_no_dialog_when_location_is_safe(app, monkeypatch):
    from auxy.core import hardening

    page = app.pages["settings"]
    ops = []
    monkeypatch.setattr(hardening, "install_location_risk", lambda *a, **k: hardening.LocationRisk(hardening.OK, "guvenli"))
    monkeypatch.setattr(actions, "autostart_op", lambda op: ops.append(op) or actions.ActionResult(True, "tamam", True))
    monkeypatch.setattr(autostart, "is_installed", lambda: True)
    page.autostart_sw.select()
    page._toggle_autostart()  # diyalog acilirsa conftest'teki koruma testi HATAYA dusurur
    assert pump(app, lambda: ops == ["install"])
