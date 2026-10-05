import threading
import time
from datetime import datetime
from pathlib import Path

import pytest

from auxy.agent import helpers as helpers_mod
from auxy.agent import tray
from auxy.core import actions, defender, system, winsec
from auxy.core.actions import ActionResult

REAL_SLEEP = time.sleep


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AUXY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AUXY_INSTANCE", "_m8tray")  # calisan GERCEK ajanla ayni adli olay/mutex paylasilmasin
    import auxy.core.log as log

    monkeypatch.setattr(log, "_configured", False)
    yield
    logger = log.get_logger()
    for h in list(logger.handlers):
        h.close()
        logger.removeHandler(h)


def fake_status(realtime=True, pua=1):
    status = {k: None for k in defender.STATUS_FIELDS}
    status.update(AMServiceEnabled=True, AntivirusEnabled=True, RealTimeProtectionEnabled=realtime,
                  BehaviorMonitorEnabled=True, IsTamperProtected=False,
                  AntivirusSignatureLastUpdated=datetime(2026, 10, 5))
    prefs = dict(MAPSReporting=1, PUAProtection=pua, EnableControlledFolderAccess=0, EnableNetworkProtection=0,
                 DisableRealtimeMonitoring=not realtime, SubmitSamplesConsent=1)
    return defender.DefenderStatus(status=status, prefs=prefs)


@pytest.fixture
def agent(monkeypatch):
    a = tray.Agent()
    a.notes = []
    monkeypatch.setattr(a, "_notify", lambda m: a.notes.append(m))
    monkeypatch.setattr(a.icon, "update_menu", lambda: None)
    monkeypatch.setattr(system, "trim_working_set", lambda: True)
    return a


# ---------------- tray ----------------
def test_refresh_success_sets_health_icon_and_firewall(agent, monkeypatch):
    monkeypatch.setattr(tray.defender, "read_status", lambda: fake_status())
    monkeypatch.setattr(tray.WinSecService, "get_many", lambda self, keys: {k: "on" for k in keys})
    agent.refresh()
    assert agent.health is not None and agent.status is not None
    assert agent.fw == {"fw_domain": "on", "fw_private": "on", "fw_public": "on"}
    assert "AuxySecurity" in agent.icon.title


def test_refresh_survives_firewall_read_error(agent, monkeypatch):
    monkeypatch.setattr(tray.defender, "read_status", lambda: fake_status())
    monkeypatch.setattr(tray.WinSecService, "get_many", lambda self, keys: (_ for _ in ()).throw(OSError("kayit")))
    agent.refresh()
    assert agent.fw == {} and agent.health is not None  # ajan dusmez, durum yine gosterilir


def test_toggle_and_apply_notify_results(agent, monkeypatch):
    agent.status = fake_status(pua=1)
    applied = []
    monkeypatch.setattr(actions, "apply_setting", lambda k, v: applied.append((k, v)) or ActionResult(True, "on → off", True))
    monkeypatch.setattr(agent, "refresh", lambda: applied.append("refresh"))
    agent._toggle("pua")  # acik -> kapat
    assert applied == [("pua", "off"), "refresh"] and "İstenmeyen uygulama koruması: on → off" in agent.notes[0]
    applied.clear()
    agent.status = fake_status(pua=0)
    agent._toggle("pua")  # kapali -> ac
    assert applied[0] == ("pua", "on")
    monkeypatch.setattr(actions, "apply_setting", lambda k, v: ActionResult(False, "Windows engelledi"))
    agent._apply("realtime", "off")
    assert agent.notes[-1] == "Windows engelledi"  # basarisizlikta etiket eklenmez, neden gosterilir


def test_menu_actions_start_threads(agent, monkeypatch):
    started = []
    monkeypatch.setattr(tray.Agent, "_start", staticmethod(lambda fn, *a: started.append((fn.__name__, a))))
    agent._toggle_action("pua")(None, None)
    agent._maps_action("advanced")(None, None)
    agent._fw_action("fw_public")(None, None)
    agent._quick_scan_action(None, None)
    agent._quarantine_last_action(None, None)
    assert [s[0] for s in started] == ["_toggle", "_apply", "_toggle_fw", "_quick_scan", "_quarantine_last"]
    assert started[1][1] == ("maps", "advanced")


def test_maps_checked_and_scan_enabled(agent):
    agent.status = fake_status()
    assert agent._maps_checked("basic")(None) is True and agent._maps_checked("advanced")(None) is False
    assert agent._scan_enabled(None) is True
    agent._scans._proc = object()
    assert agent._scan_enabled(None) is False


def test_quick_scan_notifies_start_result_and_busy(agent, monkeypatch):
    from auxy.core import scan

    monkeypatch.setattr(agent, "refresh", lambda: None)
    agent._scans = type("M", (), {"running": False, "run": lambda s, k: scan.ScanResult(
        k, "", "2026-10-05T10:00:00", 5.0, scan.COMPLETED, 0, ["Virus:X"])})()
    agent._quick_scan()
    assert agent.notes[0] == "Hızlı tarama başladı." and "1 tehdit bulundu" in agent.notes[1]
    agent._scans = type("M", (), {"running": False, "run": lambda s, k: (_ for _ in ()).throw(scan.ScanBusyError("mesgul"))})()
    agent._quick_scan()
    assert agent.notes[-1] == "mesgul"


def test_quarantine_last_adds_to_vault_or_reports(agent, tmp_path, monkeypatch):
    f = tmp_path / "kotu.exe"
    f.write_bytes(b"MZ" + b"k" * 40)
    agent._helpers.last_threat = helpers_mod.LastThreat("Trojan:X", str(f), datetime.now())
    agent._quarantine_last()
    assert agent.notes[-1].startswith("Kasaya alındı: kotu.exe") and not f.exists()
    assert agent._helpers.last_threat.handled is True
    agent.notes.clear()
    agent._quarantine_last()  # artik quarantinable degil: sessizce cikar
    assert agent.notes == []
    g = tmp_path / "x.exe"
    g.write_bytes(b"MZ")
    agent._helpers.last_threat = helpers_mod.LastThreat("T", str(g), datetime.now())
    from auxy.core import vault

    monkeypatch.setattr(vault.Vault, "default", classmethod(lambda cls: (_ for _ in ()).throw(vault.VaultError("anahtar yok"))))
    agent._quarantine_last()
    assert agent.notes[-1] == "anahtar yok" and g.exists()


def test_open_gui_spawns_detached_windowless(agent, monkeypatch):
    calls = []
    monkeypatch.setattr(tray.subprocess, "Popen", lambda cmd, **k: calls.append((cmd, k)))
    agent.open_gui()
    cmd, kw = calls[0]
    assert cmd[1:] == ["-m", "auxy", "gui"] and kw["close_fds"] is True
    assert kw["creationflags"] & tray.subprocess.DETACHED_PROCESS


def test_loop_refreshes_then_stops_on_event(agent, monkeypatch):
    n = []
    monkeypatch.setattr(agent, "refresh", lambda: n.append(1))
    monkeypatch.setattr(tray, "REFRESH_S", 0.05)
    t = threading.Thread(target=agent._loop, daemon=True)
    t.start()
    REAL_SLEEP(0.3)
    agent._stop.set()
    agent._wake.set()
    t.join(3)
    assert not t.is_alive() and len(n) >= 3  # ilk + periyodik yenilemeler; sonra temiz durdu


def test_quit_stops_everything(agent, monkeypatch):
    stopped = []
    monkeypatch.setattr(agent.icon, "stop", lambda: stopped.append("icon"))
    monkeypatch.setattr(agent._helpers, "stop_all", lambda: stopped.append("helpers"))
    agent.quit()
    assert agent._stop.is_set() and stopped == ["helpers", "icon"]


def test_notify_wrapper_swallows_icon_errors():
    a = tray.Agent()
    a.icon.notify = lambda m, t: (_ for _ in ()).throw(RuntimeError("simge hazir degil"))
    a._notify("test")  # istisna disari sizmaz


def test_config_loop_applies_config_on_signal(agent, monkeypatch):
    applied = []
    monkeypatch.setattr(agent._helpers, "apply", lambda cfg: applied.append(cfg))
    monkeypatch.setattr(agent, "_wake", threading.Event())
    t = threading.Thread(target=agent._config_loop, daemon=True)
    t.start()
    REAL_SLEEP(0.2)
    system.signal_config_changed()
    deadline = time.time() + 3
    while not applied and time.time() < deadline:
        REAL_SLEEP(0.05)
    agent._stop.set()
    agent._config_waiter.wake()
    t.join(3)
    assert applied and not t.is_alive()


# ---------------- guvenlik sayfasi ----------------
def pump(a, cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        a.update()
        if cond():
            return True
        REAL_SLEEP(0.05)
    return False


@pytest.fixture
def sp(app, monkeypatch):
    from auxy.gui import security_page

    page = app.pages["security"]
    applied = []
    monkeypatch.setattr(actions, "apply_winsec", lambda k, v: applied.append((k, v)) or ActionResult(True, f"{k} → {v}", True))
    page.applied = applied
    page.confirm_calls = []

    def ask(title, msg, **k):
        page.confirm_calls.append((title, msg))
        return page.answer

    page.answer = True
    monkeypatch.setattr(security_page.messagebox, "askyesno", ask)
    monkeypatch.setattr(page, "refresh", lambda: None)  # gercek durum okumasina gerek yok
    return page


@pytest.fixture
def netp(app, monkeypatch):
    """Ag guvenligi sayfasi (guvenlik duvari anahtarlari artik burada)."""
    from auxy.gui import network_page

    page = app.pages["network"]
    applied = []
    monkeypatch.setattr(actions, "apply_winsec", lambda k, v: applied.append((k, v)) or ActionResult(True, f"{k} → {v}", True))
    page.applied, page.confirm_calls, page.answer = applied, [], True

    def ask(title, msg, **k):
        page.confirm_calls.append((title, msg))
        return page.answer

    monkeypatch.setattr(network_page.messagebox, "askyesno", ask)
    monkeypatch.setattr(page, "refresh", lambda: None)
    return page


def test_toggle_off_needs_confirm_and_reverts_switch_on_no(app, netp):
    sp = netp
    sp.sw["fw_public"].deselect()
    sp.answer = False
    sp._toggle("fw_public")
    assert sp.applied == [] and sp.sw["fw_public"].get() == 1  # reddedildi: anahtar eski haline
    assert "çok risklidir" in sp.confirm_calls[0][1]
    sp.answer = True
    sp.sw["fw_public"].deselect()
    sp._toggle("fw_public")
    assert pump(app, lambda: sp.applied == [("fw_public", "off")])


def test_toggle_on_needs_no_confirmation(app, netp):
    sp = netp
    sp.sw["fw_private"].select()
    sp._toggle("fw_private")
    assert pump(app, lambda: sp.applied == [("fw_private", "on")]) and sp.confirm_calls == []


def test_firewall_values_render_on_network_page(app, netp):
    netp._show_firewall({"fw_domain": "on", "fw_private": "off", "fw_public": "on", "fw_in_domain": "default",
                         "fw_in_private": "block", "fw_in_public": "allow"}, None)
    assert netp.sw["fw_private"].get() == 0 and netp.sw["fw_public"].get() == 1
    assert netp.inbound_menus["fw_in_public"].get() == "İzin ver" and netp.inbound_menus["fw_in_private"].get() == "Engelle"


def test_hvci_toggle_warns_about_reboot_and_no_restores_switch(app, sp):
    sp.sw["hvci"].select()  # acmak istiyor
    sp.answer = False
    sp._toggle("hvci")
    assert sp.applied == [] and "yeniden başlatılınca" in sp.confirm_calls[-1][1]
    assert sp.sw["hvci"].get() == 0  # vazgecildi: anahtar eski (kapali) haline
    sp.answer = True
    sp.sw["hvci"].select()
    sp._toggle("hvci")
    assert pump(app, lambda: ("hvci", "on") in sp.applied)


def test_smartscreen_menu_off_needs_confirm(app, sp):
    sp._set_smartscreen("Kapalı")
    assert sp.applied == [] or ("smartscreen_apps", "off") in sp.applied
    sp.applied.clear()
    sp.answer = False
    sp._set_smartscreen("Kapalı")
    assert not pump(app, lambda: sp.applied, timeout=0.5)  # reddedildi
    sp.answer = True
    sp._set_smartscreen("Engelle")  # guclendirme: onay istemez
    assert pump(app, lambda: ("smartscreen_apps", "block") in sp.applied)


def test_tpm_button_renders_result_and_errors(app, sp, monkeypatch):
    monkeypatch.setattr(actions, "read_tpm", lambda: ActionResult(True, "ok", data={
        "TpmPresent": True, "TpmReady": True, "TpmEnabled": False, "ManufacturerVersion": "600.18"}))
    sp.read_tpm()
    assert pump(app, lambda: "Sürüm: 600.18" in sp.tpm_lbl.cget("text"))
    assert "Var: Evet" in sp.tpm_lbl.cget("text") and "Etkin: Hayır" in sp.tpm_lbl.cget("text")
    monkeypatch.setattr(actions, "read_tpm", lambda: ActionResult(False, "Yönetici izni verilmedi."))
    sp.read_tpm()
    assert pump(app, lambda: "izni verilmedi" in sp.tpm_lbl.cget("text"))


EXCL = {"path": [r"C:\proje"], "extension": ["log"], "process": ["derleyici.exe"]}


def test_exclusions_list_add_remove_flow(app, sp, monkeypatch):
    from auxy.gui import security_page

    calls = []

    def fake_op(op, kind, value=""):
        calls.append((op, kind, value))
        return ActionResult(True, "tamam", op != "list", EXCL if op == "list" else None)

    monkeypatch.setattr(actions, "exclusion_op", fake_op)
    sp.load_exclusions()
    assert pump(app, lambda: len(sp.excl_frame.winfo_children()) >= 6)  # 3 oge x (etiket + Kaldir)
    import customtkinter as ctk

    texts = [w.cget("text") for w in sp.excl_frame.winfo_children() if isinstance(w, ctk.CTkLabel)]
    assert any("C:\\proje" in t for t in texts) and any("derleyici.exe" in t for t in texts)
    # kaldir
    sp.remove_exclusion("extension", "log")
    assert pump(app, lambda: ("remove", "extension", "log") in calls)
    # klasor ekle: onay HAYIR -> hicbir sey; EVET -> ekler
    monkeypatch.setattr(security_page.filedialog, "askdirectory", lambda **k: r"C:\yeni klasor")
    sp.answer = False
    sp.add_folder()
    app.update()
    assert not any(c[0] == "add" for c in calls)
    sp.answer = True
    sp.add_folder()
    assert pump(app, lambda: ("add", "path", str(Path(r"C:\yeni klasor"))) in calls)
    # uzanti / islem: giris kutusu
    class Dlg:
        def __init__(self, text=None, title=None):
            self.text = text

        def get_input(self):
            return "tmp" if "uzantı" in self.text else "araci.exe"

    monkeypatch.setattr(security_page.ctk, "CTkInputDialog", Dlg)
    sp.add_text("extension")
    sp.add_text("process")
    assert pump(app, lambda: ("add", "extension", "tmp") in calls and ("add", "process", "araci.exe") in calls)


def test_exclusions_error_and_empty_states(app, sp, monkeypatch):
    monkeypatch.setattr(actions, "exclusion_op", lambda op, kind, value="": ActionResult(False, "Yönetici izni verilmedi."))
    sp.load_exclusions()
    assert pump(app, lambda: any("izni verilmedi" in w.cget("text") for w in sp.excl_frame.winfo_children()))
    monkeypatch.setattr(actions, "exclusion_op", lambda op, kind, value="": ActionResult(True, "0", data={"path": [], "extension": [], "process": []}))
    sp.load_exclusions()
    assert pump(app, lambda: any("Dışlama yok" in w.cget("text") for w in sp.excl_frame.winfo_children()))


def test_main_view_renders_values_devices_and_hvci_pending_note(app, sp):
    products = [winsec.SecurityProduct("Antivirüs", "Windows Defender", True, True),
                winsec.SecurityProduct("Güvenlik duvarı", "Eski FW", False, False)]
    device = winsec.DeviceSecurity(secure_boot=True, vbs_running=True, hvci_running=False)
    values = {k: "on" for k in winsec.WINSEC_SETTINGS}
    values.update(smartscreen_apps="block", fw_in_public="allow", fw_in_domain="default", hvci="on")
    sp._show_main((values, products, device), None)
    assert "KAPALI" in sp.products_lbl.cget("text") and "güncel DEĞİL" in sp.products_lbl.cget("text")
    assert sp.ss_menu.get() == "Engelle"
    assert "Secure Boot: Açık" in sp.device_lbl.cget("text") and "Çalışmıyor" in sp.device_lbl.cget("text")
    assert "yeniden başlat" in sp.hvci_note.cget("text")  # yapilandirildi ama calismiyor -> yeniden baslatma notu
    sp._show_main(None, RuntimeError("wmi"))
    assert "Okunamadı" in sp.message.cget("text")


def test_exploit_view_and_error(app, sp):
    sp._show_exploit({"DEP": "NOTSET", "CFG": "ON", "BottomUp": "OFF"}, None)
    text = sp.exploit_lbl.cget("text")
    assert "Varsayılan (Windows)" in text and "Açık" in text and "Kapalı" in text
    sp._show_exploit(None, RuntimeError("ps yok"))
    assert "Okunamadı" in sp.exploit_lbl.cget("text")
