import json
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from auxy.agent import icon as tray_icon
from auxy.agent import tray
from auxy.core import actions, autostart, system
from auxy.core.service import AuxyError, NotAdminError
from auxy.gui import viewmodel as vm


# ---- actions ----
def test_result_path_only_in_temp_with_prefix(tmp_path):
    ok = Path(tempfile.gettempdir()) / "auxy-result-123.json"
    assert actions.result_path_allowed(str(ok))
    assert not actions.result_path_allowed(str(Path(tempfile.gettempdir()) / "evil.json"))
    assert not actions.result_path_allowed(str(tmp_path / "auxy-result-1.json"))
    assert not actions.result_path_allowed(r"C:\Windows\System32\auxy-result-1.json")
    assert not actions.result_path_allowed(
        str(Path(tempfile.gettempdir()) / ".." / "auxy-result-1.json"))


def test_write_result_rejects_bad_path():
    with pytest.raises(ValueError):
        actions.write_result(r"C:\Windows\auxy-result-x.json", True, "x")


def test_apply_setting_direct_when_admin(monkeypatch):
    class Res:
        changed, old, new = True, "on", "off"

    class Svc:
        def set(self, k, v):
            assert (k, v) == ("pua", "off")
            return Res()

    monkeypatch.setattr(system, "is_admin", lambda: True)
    monkeypatch.setattr(actions, "DefenderService", Svc)
    r = actions.apply_setting("pua", "off")
    assert r.ok and r.changed and r.message == "on → off"


def test_apply_setting_admin_error_is_reported(monkeypatch):
    class Svc:
        def set(self, k, v):
            raise NotAdminError("x")

    monkeypatch.setattr(system, "is_admin", lambda: True)
    monkeypatch.setattr(actions, "DefenderService", Svc)
    r = actions.apply_setting("pua", "off")
    assert not r.ok and r.message == "x"


def test_apply_setting_elevates_and_reads_result(monkeypatch):
    seen = {}

    def fake_elevated(args, timeout_s=120):
        seen["args"] = args
        actions.write_result(args[args.index("--result") + 1], True, "on → off", True)
        return 0

    monkeypatch.setattr(system, "is_admin", lambda: False)
    monkeypatch.setattr(system, "run_elevated_and_wait", fake_elevated)
    r = actions.apply_setting("cfa", "on")
    assert r.ok and r.changed and r.message == "on → off"
    assert seen["args"][:3] == ["set", "cfa", "on"]
    # gecici sonuc dosyasi temizlendi
    assert not Path(seen["args"][-1]).exists()


def test_apply_setting_uac_denied(monkeypatch):
    monkeypatch.setattr(system, "is_admin", lambda: False)
    monkeypatch.setattr(system, "run_elevated_and_wait", lambda *a, **k: None)
    r = actions.apply_setting("cfa", "on")
    assert not r.ok and "izni verilmedi" in r.message


def test_apply_setting_missing_result_file(monkeypatch):
    monkeypatch.setattr(system, "is_admin", lambda: False)
    monkeypatch.setattr(system, "run_elevated_and_wait", lambda *a, **k: 5)
    r = actions.apply_setting("cfa", "on")
    assert not r.ok and "okunamadı" in r.message


def test_result_roundtrip_json(tmp_path):
    p = Path(tempfile.gettempdir()) / "auxy-result-roundtrip.json"
    try:
        actions.write_result(str(p), False, "hata", False)
        assert json.loads(p.read_text(encoding="utf-8"))["ok"] is False
    finally:
        p.unlink(missing_ok=True)


# ---- autostart ----
def test_task_xml_is_valid_and_has_required_properties():
    xml = autostart.build_task_xml("PC\\kullanici", r"C:\x\pythonw.exe", r"C:\proj & co")
    root = ET.fromstring(xml.replace('encoding="UTF-16"', ""))  # parse icin
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    assert root.find(".//t:RunLevel", ns).text == "HighestAvailable"
    assert root.find(".//t:Delay", ns).text == "PT30S"
    assert root.find(".//t:Arguments", ns).text == "-m auxy agent"
    assert root.find(".//t:ExecutionTimeLimit", ns).text == "PT0S"
    assert root.find(".//t:DisallowStartIfOnBatteries", ns).text == "false"
    assert root.find(".//t:WorkingDirectory", ns).text == r"C:\proj & co"  # kacis calisti


def test_install_requires_admin(monkeypatch):
    monkeypatch.setattr(system, "is_admin", lambda: False)
    with pytest.raises(AuxyError):
        autostart.install()
    with pytest.raises(AuxyError):
        autostart.remove()


# ---- tray ----
def _near(px, rgb, tol=12):
    return all(abs(a - b) <= tol for a, b in zip(px[:3], rgb, strict=True))


def test_icon_sizes_and_shield_colors():
    for level in (vm.OK, vm.WARN, vm.CRIT, None):
        assert tray_icon.make_icon(level).size == (64, 64)
    assert _near(tray_icon.make_icon(vm.OK).getpixel((9, 28)), tray_icon.GREEN)   # saglikli: yesil kalkan
    assert _near(tray_icon.make_icon(None).getpixel((9, 28)), tray_icon.GRAY)     # bilinmiyor: gri


def test_icon_badge_color_depends_on_severity():
    # rozet sag ustte (merkez ~ (46, 18)); kritik -> kirmizi, kritik olmayan -> turuncu, sorun yok -> rozet yok
    crit = tray_icon.make_icon(vm.CRIT, 1).getpixel((46, 8))
    warn = tray_icon.make_icon(vm.WARN, 1).getpixel((46, 8))
    assert _near(crit, tray_icon.RED) and _near(warn, tray_icon.ORANGE)
    assert not _near(tray_icon.make_icon(vm.OK, 0).getpixel((46, 8)), tray_icon.RED)
    assert tray_icon.make_icon(vm.CRIT, 1).tobytes() != tray_icon.make_icon(vm.CRIT, 2).tobytes()  # sayi cizilir


def test_health_badge_counts_and_tooltip():
    from auxy.core import defender

    def status(**s):
        base = dict(AMServiceEnabled=True, AntivirusEnabled=True, RealTimeProtectionEnabled=True,
                    BehaviorMonitorEnabled=True, IsTamperProtected=True)
        return defender.DefenderStatus(status={**base, **s}, prefs={"MAPSReporting": 2})

    one_crit = vm.evaluate(status(RealTimeProtectionEnabled=False, IsTamperProtected=False))
    assert one_crit.level == vm.CRIT and one_crit.badge == 1  # kritik varsa yalnizca kritik sayilir
    assert "1 kritik sorun" in tray.tooltip(one_crit)
    two_warn = vm.evaluate(status(BehaviorMonitorEnabled=False, IsTamperProtected=False))
    assert two_warn.level == vm.WARN and two_warn.badge == 2 and "2 uyarı" in tray.tooltip(two_warn)
    assert vm.evaluate(status()).badge == 0


def test_menu_builds_with_and_without_status():
    """pystray eylem imzalarini dogrular; menu uretimi hata vermemeli (gercek bug yakalandi)."""
    from auxy.core import defender

    agent = tray.Agent()
    names = lambda: [i.text for i in agent.icon.menu.items if i.text]  # noqa: E731
    assert "Durum okunamadı" in names()  # status yok
    status = {k: None for k in defender.STATUS_FIELDS}
    prefs = dict(DisableRealtimeMonitoring=False, MAPSReporting=1, PUAProtection=1,
                 EnableControlledFolderAccess=0, EnableNetworkProtection=2)
    agent.status = defender.DefenderStatus(status=status, prefs=prefs)
    items = {i.text: i for i in agent.icon.menu.items if i.text}
    assert items["Hızlı tara"].enabled is True
    assert items["İstenmeyen uygulama koruması"].checked is True
    assert items["Denetimli klasör erişimi"].checked is False
    assert items["Ağ koruması"].checked is True  # denetim modu = acik sayilir
    assert items["Gerçek zamanlı koruma"].checked is True  # artik uygulama icinden degisir
    maps = {i.text: i.checked for i in items["Bulut koruma (MAPS)"].submenu.items}
    assert maps == {"Kapalı": False, "Temel": True, "Gelişmiş": False}
    assert not any("Windows Security" in t for t in items)  # yonlendirme yok


def test_tooltip():
    assert tray.tooltip(None) == "AuxySecurity – Durum okunamadı"
    assert tray.tooltip(vm.Health(vm.OK, "Cihazın korunuyor")).endswith("Cihazın korunuyor")
    assert len(tray.tooltip(vm.Health(vm.OK, "x" * 500))) <= 127

