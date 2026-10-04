import json
import threading
import time
import winreg
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from auxy import __main__ as cli
from auxy.agent import helpers as helpers_mod
from auxy.agent import watchers
from auxy.core import config as cfgmod
from auxy.core import contextmenu, scan, system
from auxy.core.service import AuxyError

REAL_SLEEP = time.sleep


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("AUXY_HOME", str(tmp_path / "home"))
    import auxy.core.log as log

    monkeypatch.setattr(log, "_configured", False)
    yield tmp_path
    logger = log.get_logger()
    for h in list(logger.handlers):
        h.close()
        logger.removeHandler(h)


# ---------------- config ----------------
def test_config_defaults_are_conservative():
    c = cfgmod.Config()
    assert not c.watch_enabled and not c.usb_scan and not c.scheduled.enabled
    assert c.event_notifications  # yalnizca ucuz olan acik


def test_config_roundtrip_and_default_folder():
    c = cfgmod.Config(watch_enabled=True, watch_folders=[r"C:\a"], usb_scan=True,
                      scheduled=cfgmod.ScheduledScan(True, 2, 21, "full"))
    cfgmod.save(c)
    assert cfgmod.load() == c
    assert cfgmod.Config().effective_watch_folders()[0].lower().endswith("downloads")


def test_config_sanitizes_garbage_and_corruption():
    cfgmod.config_file().parent.mkdir(parents=True, exist_ok=True)
    cfgmod.config_file().write_text(json.dumps(
        {"watch_enabled": "evet", "scheduled": {"weekday": 99, "hour": -1, "kind": "x", "enabled": 1},
         "watch_folders": [1, "C:\\ok", None]}), encoding="utf-8")
    c = cfgmod.load()
    assert c.scheduled.weekday == 6 and c.scheduled.hour == 3 and c.scheduled.kind == "quick"
    assert c.watch_folders == ["C:\\ok"] and c.watch_enabled is True
    cfgmod.config_file().write_text("{bozuk", encoding="utf-8")
    assert cfgmod.load() == cfgmod.Config()
    cfgmod.config_file().write_text("[1,2]", encoding="utf-8")
    assert cfgmod.load() == cfgmod.Config()


# ---------------- yardimcilar ----------------
@pytest.mark.parametrize("name,expected", [
    ("a.exe", True), ("b.zip", True), ("c.crdownload", False), ("d.PART", False), ("e.tmp", False),
    ("~$belge.docx", False), ("f.opdownload", False),
])
def test_should_scan(name, expected):
    assert watchers.should_scan(rf"C:\x\{name}") is expected


def test_plan_batch_small_and_large():
    assert watchers.plan_batch(["a", "b", "a"]) == ["a", "b"]
    many = [rf"C:\k{i % 7}\f{i}.txt" for i in range(40)]
    out = watchers.plan_batch(many)
    assert len(out) <= watchers.MAX_DIRS_PER_BATCH and all(o.startswith("C:\\k") for o in out)


def test_wait_until_stable_growing_then_stable_and_vanished():
    sizes = iter([10, 20, 30, 30])
    assert watchers.wait_until_stable("x", size_of=lambda p: next(sizes), sleep=lambda s: None)
    def gone(p):
        raise FileNotFoundError
    assert watchers.wait_until_stable("x", size_of=gone, sleep=lambda s: None) is False
    counter = iter(range(1000))
    assert watchers.wait_until_stable("x", timeout=2, poll=1, size_of=lambda p: next(counter),
                                      sleep=lambda s: None) is False  # hep buyuyor


# ---------------- olay XML ----------------
SAMPLE = """<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
<System><EventID>1116</EventID></System>
<EventData><Data Name="Threat Name">Virus:DOS/EICAR_Test_File</Data>
<Data Name="Severity Name">Ciddi</Data><Data Name="Path">file:_C:\\Users\\k\\eicar.txt</Data>
<Data Name="Action Name">Karantina</Data></EventData></Event>"""


def test_parse_event_xml():
    ev = watchers.parse_event_xml(SAMPLE)
    assert ev == watchers.DefenderEvent(1116, "Virus:DOS/EICAR_Test_File", "Ciddi",
                                        r"C:\Users\k\eicar.txt", "Karantina")
    assert watchers.parse_event_xml("<bozuk") is None
    assert watchers.parse_event_xml("<Event xmlns='http://schemas.microsoft.com/win/2004/08/events/event'/>") is None


# ---------------- zamanlama ----------------
def test_next_run():
    wed_noon = datetime(2026, 10, 7, 12, 0)  # Carsamba
    assert wed_noon.weekday() == 2
    assert watchers.next_run(wed_noon, 2, 15) == datetime(2026, 10, 7, 15, 0)   # bugun, ileri saat
    assert watchers.next_run(wed_noon, 2, 9) == datetime(2026, 10, 14, 9, 0)    # bugun gecti -> haftaya
    assert watchers.next_run(wed_noon, 2, 12) == datetime(2026, 10, 14, 12, 0)  # tam o an -> haftaya
    assert watchers.next_run(wed_noon, 0, 3) == datetime(2026, 10, 12, 3, 0)    # Pazartesi
    assert watchers.next_run(wed_noon, 6, 3) == datetime(2026, 10, 11, 3, 0)    # Pazar


class FakeMgr:
    def __init__(self, threats_=None, busy=0):
        self.calls, self.threats, self.busy = [], threats_ or [], busy

    def run(self, kind, path=None, quiet=False):
        if self.busy:
            self.busy -= 1
            raise scan.ScanBusyError("mesgul")
        self.calls.append((kind, path, quiet))
        return scan.ScanResult(kind, path or "", "2026-10-04T10:00:00", 1.0, scan.COMPLETED, 0, self.threats)


def sched(now, idle, ac, mgr, kind="quick"):
    notes = []
    s = watchers.ScheduledScanner(cfgmod.ScheduledScan(True, 2, 3, kind), mgr, notes.append,
                                  now=now, idle=idle, ac=ac)
    return s, notes


def test_scheduled_runs_when_idle_and_ac():
    due = datetime(2026, 10, 7, 3, 0)
    mgr = FakeMgr()
    s, notes = sched(lambda: due, lambda: 900, lambda: True, mgr, kind="full")
    assert s._attempt(due) is True
    assert mgr.calls == [(scan.FULL, None, False)] and "Zamanlanmış tarama" in notes[0]


def test_scheduled_waits_when_busy_then_runs(monkeypatch):
    monkeypatch.setattr(watchers, "RETRY_S", 0.01)
    due = datetime(2026, 10, 7, 3, 0)
    idles = iter([10, 20, 400])
    mgr = FakeMgr()
    s, _ = sched(lambda: due, lambda: next(idles), lambda: True, mgr)
    assert s._attempt(due) and len(mgr.calls) == 1


def test_scheduled_not_on_battery_and_gives_up_after_6h(monkeypatch):
    monkeypatch.setattr(watchers, "RETRY_S", 0.01)
    due = datetime(2026, 10, 7, 3, 0)
    clock = {"t": due}
    def now():
        clock["t"] += timedelta(hours=2)  # her kontrolde 2 saat ilerler
        return clock["t"]
    mgr = FakeMgr()
    s, _ = sched(now, lambda: 9999, lambda: False, mgr)  # hep pilde
    assert s._attempt(due) is True
    assert mgr.calls == []  # 6 saat sonra vazgecti, hic taramadi


# ---------------- klasor izleme (gercek watchdog) ----------------
def wait_for(cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        REAL_SLEEP(0.05)
    return False


@pytest.fixture
def fast_sleep(monkeypatch):
    monkeypatch.setattr(watchers.time, "sleep", lambda s: REAL_SLEEP(min(s, 0.05)))


def test_folder_watcher_scans_new_file_and_ignores_temp(tmp_path, fast_sleep):
    folder = tmp_path / "indirilenler"
    folder.mkdir()
    mgr, notes = FakeMgr(), []
    w = watchers.FolderWatcher([str(folder)], mgr, notes.append)
    w.start()
    try:
        (folder / "yarim.crdownload").write_bytes(b"x" * 100)       # yok sayilmali
        (folder / "program.exe").write_bytes(b"MZ" + b"a" * 100)     # taranmali
        assert wait_for(lambda: any(c[1] == str(folder / "program.exe") for c in mgr.calls))
        assert not any(str(c[1]).endswith(".crdownload") for c in mgr.calls)
        assert all(c[0] == scan.CUSTOM and c[2] is True for c in mgr.calls)  # quiet=True
        # indirme bitince yeniden adlandirma: yeni ad taranmali
        os_rename = folder / "yarim.crdownload"
        os_rename.rename(folder / "belge.pdf")
        assert wait_for(lambda: any(c[1] == str(folder / "belge.pdf") for c in mgr.calls))
    finally:
        w.stop()


def test_folder_watcher_batches_many_files_into_directory_scan(tmp_path, fast_sleep):
    folder = tmp_path / "zip-acildi"
    folder.mkdir()
    mgr = FakeMgr()
    w = watchers.FolderWatcher([str(folder)], mgr, lambda m: None)
    w.start()
    try:
        for i in range(30):
            (folder / f"f{i}.txt").write_text("x")
        assert wait_for(lambda: len(mgr.calls) >= 1)
        REAL_SLEEP(0.5)
        paths_ = [c[1] for c in mgr.calls]
        assert str(folder) in paths_ and len(paths_) < 30  # tek tek degil, klasor olarak
    finally:
        w.stop()


def test_folder_watcher_notifies_threat_and_reports(tmp_path, fast_sleep):
    folder = tmp_path / "d"
    folder.mkdir()
    mgr, notes, seen = FakeMgr(threats_=["Trojan:Test"]), [], []
    w = watchers.FolderWatcher([str(folder)], mgr, notes.append, lambda n, p: seen.append((n, p)))
    w.start()
    try:
        (folder / "kotu.exe").write_bytes(b"MZ" + b"b" * 50)
        assert wait_for(lambda: bool(notes))
        assert "Trojan:Test" in notes[0] and "kotu.exe" in notes[0]
        assert seen[0][0] == "Trojan:Test"
    finally:
        w.stop()


def test_folder_watcher_retries_when_busy(tmp_path, fast_sleep, monkeypatch):
    folder = tmp_path / "d"
    folder.mkdir()
    mgr = FakeMgr(busy=2)
    w = watchers.FolderWatcher([str(folder)], mgr, lambda m: None)
    monkeypatch.setattr(w._stop, "wait", lambda t: False)  # 30 sn beklemeyi atla
    w.start()
    try:
        (folder / "a.exe").write_bytes(b"MZ" + b"c" * 50)
        assert wait_for(lambda: len(mgr.calls) == 1)  # 2 mesgul + 1 basarili
    finally:
        w.stop()


def test_folder_watcher_skips_missing_folders(tmp_path):
    w = watchers.FolderWatcher([str(tmp_path / "yok")], FakeMgr(), lambda m: None)
    assert w.folders == []


# ---------------- yardimci yoneticisi ----------------
class FakeComp:
    log = []

    def __init__(self, name, fail=False):
        self.name, self.fail = name, fail

    def start(self):
        if self.fail:
            raise RuntimeError("baslamadi")
        FakeComp.log.append(("start", self.name))

    def stop(self):
        FakeComp.log.append(("stop", self.name))


def manager(fail=()):
    FakeComp.log = []
    notes = []
    m = helpers_mod.HelperManager(FakeMgr(), notes.append, factories={
        n: (lambda c, n=n: FakeComp(n, n in fail)) for n in ("watch", "events", "usb", "schedule")})
    return m, notes


def test_apply_starts_only_enabled_and_is_idempotent():
    m, _ = manager()
    cfg = cfgmod.Config(watch_enabled=True, watch_folders=[r"C:\a"])
    m.apply(cfg)
    assert m.running == ["events", "watch"]
    FakeComp.log.clear()
    m.apply(cfg)  # ayni imza: hicbir sey yeniden baslatilmaz
    assert FakeComp.log == []


def test_apply_restarts_changed_and_stops_disabled():
    m, _ = manager()
    m.apply(cfgmod.Config(watch_enabled=True, watch_folders=[r"C:\a"], usb_scan=True))
    FakeComp.log.clear()
    m.apply(cfgmod.Config(watch_enabled=True, watch_folders=[r"C:\b"], usb_scan=False))
    assert ("stop", "watch") in FakeComp.log and ("start", "watch") in FakeComp.log
    assert ("stop", "usb") in FakeComp.log and "usb" not in m.running


def test_component_failure_is_isolated_and_reported():
    m, notes = manager(fail=("usb",))
    m.apply(cfgmod.Config(usb_scan=True, watch_enabled=True, watch_folders=[r"C:\a"]))
    assert "usb" not in m.running and "watch" in m.running
    assert any("usb" in n for n in notes)


def test_stop_all():
    m, _ = manager()
    m.apply(cfgmod.Config(watch_enabled=True, watch_folders=[r"C:\a"]))
    m.stop_all()
    assert m.running == []


def test_event_handling_remembers_threat_and_marks_handled(tmp_path):
    m, notes = manager()
    f = tmp_path / "x.exe"
    f.write_bytes(b"x")
    m.apply(cfgmod.Config(event_notifications=True))
    m._on_event(watchers.DefenderEvent(1116, "Trojan:X", "Yüksek", str(f), ""))
    assert "Trojan:X" in notes[0] and m.last_threat.quarantinable()
    m._on_event(watchers.DefenderEvent(1117, "Trojan:X", "Yüksek", str(f), "Karantina"))
    assert m.last_threat.handled and not m.last_threat.quarantinable()  # Defender halletti


def test_notifications_can_be_disabled():
    m, notes = manager()
    m.apply(cfgmod.Config(event_notifications=False))
    m._on_event(watchers.DefenderEvent(1116, "Trojan:X", "", "", ""))
    assert notes == [] and m.last_threat is not None


# ---------------- sag tik menusu (gercek HKCU, test alt anahtari) ----------------
def test_context_menu_install_remove_roundtrip(monkeypatch):
    monkeypatch.setattr(contextmenu, "TARGETS", (r"Software\AuxyTestM7\a\shell", r"Software\AuxyTestM7\b\shell"))
    try:
        assert not contextmenu.is_installed()
        contextmenu.install()
        assert contextmenu.is_installed()
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, contextmenu._paths(contextmenu.TARGETS[1])[1]) as k:
            cmd = winreg.QueryValueEx(k, None)[0]
        assert cmd.endswith('scan-file "%1"') and "-m auxy" in cmd
        contextmenu.install()  # tekrar: hata vermemeli
        contextmenu.remove()
        assert not contextmenu.is_installed()
        contextmenu.remove()  # yokken de hata vermemeli
    finally:
        for sub in ("a", "b"):
            for key in (rf"Software\AuxyTestM7\{sub}\shell\{contextmenu.KEY_NAME}\command",
                        rf"Software\AuxyTestM7\{sub}\shell\{contextmenu.KEY_NAME}",
                        rf"Software\AuxyTestM7\{sub}\shell", rf"Software\AuxyTestM7\{sub}"):
                try:
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
                except OSError:
                    pass
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\AuxyTestM7")
        except OSError:
            pass


# ---------------- ajan uyandirma (gercek Windows olayi) ----------------
def test_config_waiter_wakes_on_signal_and_on_wake():
    w = system.ConfigWaiter()
    woke = threading.Event()
    t = threading.Thread(target=lambda: (w.wait(), woke.set()), daemon=True)
    t.start()
    REAL_SLEEP(0.2)
    assert not woke.is_set()  # sinyal yokken uyur
    system.signal_config_changed()  # GUI tarafi
    assert woke.wait(3)
    # cikis icin wake()
    woke.clear()
    t2 = threading.Thread(target=lambda: (w.wait(), woke.set()), daemon=True)
    t2.start()
    REAL_SLEEP(0.2)
    w.wake()
    assert woke.wait(3)


# ---------------- scan-file CLI ve sessiz mod ----------------
def test_scan_file_cli_no_dialog(monkeypatch, capsys, tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    monkeypatch.setattr(scan.ScanManager, "run", lambda self, k, p=None, quiet=False: FakeMgr().run(k, p))
    assert cli.main(["scan-file", str(f), "--no-dialog"]) == 0
    out = capsys.readouterr().out
    assert "tehdit bulunamadı" in out and str(f) in out


def test_scan_file_cli_error_message(monkeypatch, capsys):
    def boom(self, k, p=None, quiet=False):
        raise AuxyError("Taranacak yol bulunamadı")

    monkeypatch.setattr(scan.ScanManager, "run", boom)
    assert cli.main(["scan-file", r"C:\yok", "--no-dialog"]) == 0
    assert "bulunamadı" in capsys.readouterr().out


class _P:
    returncode = 0

    def communicate(self):
        return b"", None


def test_quiet_scan_skips_history_for_clean_but_keeps_threats(monkeypatch, tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    monkeypatch.setattr(scan, "mpcmdrun_path", lambda: "MpCmdRun.exe")
    monkeypatch.setattr(scan.subprocess, "Popen", lambda *a, **k: _P())
    monkeypatch.setattr(scan.ScanManager, "_new_threats", staticmethod(lambda since: []))
    scan.ScanManager().run(scan.CUSTOM, str(f), quiet=True)
    assert scan.load_history() == []
    monkeypatch.setattr(scan.ScanManager, "_new_threats", staticmethod(lambda since: ["Tehdit"]))
    scan.ScanManager().run(scan.CUSTOM, str(f), quiet=True)
    assert len(scan.load_history()) == 1
    scan.ScanManager().run(scan.CUSTOM, str(f))  # sessiz degil -> yazilir
    assert len(scan.load_history()) == 2


# ---------------- tray menusu: son tehdidi kasaya al ----------------
def test_tray_menu_shows_quarantine_item_only_when_possible(tmp_path):
    from auxy.agent import tray

    agent = tray.Agent()
    texts = lambda: [i.text for i in agent.icon.menu.items if i.text]  # noqa: E731
    assert not any(t.startswith("Tehdidi kasaya al") for t in texts())
    f = tmp_path / "kotu.exe"
    f.write_bytes(b"x")
    agent._helpers.last_threat = helpers_mod.LastThreat("Trojan:X", str(f), datetime.now())
    assert any(t == "Tehdidi kasaya al: Trojan:X" for t in texts())
    agent._helpers.last_threat.handled = True
    assert not any(t.startswith("Tehdidi kasaya al") for t in texts())


# ---------------- COM / is parcacigi (gercek hata: ajanin izleme is parcacigi sessizce olmustu) ----------------
def test_wmi_readers_work_from_fresh_threads():
    """pywin32 yalnizca ilk import eden is parcacigi icin COM baslatir; her yeni is parcacigi calismali."""
    from auxy.core import defender, threats, winsec

    results = {}

    def run(name, fn):
        try:
            fn()
            results[name] = "ok"
        except Exception as exc:  # noqa: BLE001
            results[name] = f"HATA: {exc}"

    for name, fn in (("status", defender.read_status), ("threats", threats.read_detections),
                     ("seccenter", winsec.read_security_center), ("device", winsec.read_device_security)):
        for i in range(2):  # her seferinde TAZE is parcacigi
            t = threading.Thread(target=run, args=(f"{name}{i}", fn))
            t.start()
            t.join(30)
    assert all(v == "ok" for v in results.values()), results


def test_com_apartment_is_reentrant_and_safe():
    from auxy.core import defender

    with defender.com_apartment():
        with defender.com_apartment():
            defender.read_status()
    defender.read_status()  # apartment disinda da (modul ilk import ettiginden) calismali


def test_scan_survives_unreadable_detections(monkeypatch):
    from auxy.core.defender import DefenderError

    def boom():
        raise DefenderError("okunamadi")

    monkeypatch.setattr(scan.threats, "read_detections", boom)
    assert scan.ScanManager._new_threats(datetime.now()) == []


def test_folder_worker_survives_exception_and_keeps_scanning(tmp_path, fast_sleep):
    folder = tmp_path / "d"
    folder.mkdir()

    class Flaky(FakeMgr):
        def run(self, kind, path=None, quiet=False):
            if not self.calls and not getattr(self, "failed", False):
                self.failed = True
                raise RuntimeError("beklenmeyen")
            return super().run(kind, path, quiet)

    mgr = Flaky()
    w = watchers.FolderWatcher([str(folder)], mgr, lambda m: None)
    w.start()
    try:
        (folder / "a.exe").write_bytes(b"MZ" + b"1" * 50)
        REAL_SLEEP(0.8)
        (folder / "b.exe").write_bytes(b"MZ" + b"2" * 50)  # ilk dosya istisna firlatti; izleme OLMEMELI
        assert wait_for(lambda: any(c[1] == str(folder / "b.exe") for c in mgr.calls))
    finally:
        w.stop()


# ---------------- USB ----------------
def test_is_removable_drive_system_drive_is_not():
    assert watchers.is_removable_drive("C:") is False
    assert watchers.is_removable_drive("C:\\") is False


def test_usb_handle_scans_only_removable_and_reports(monkeypatch):
    notes, mgr = [], FakeMgr(threats_=["Trojan:Usb"])
    u = watchers.UsbWatcher(mgr, notes.append)
    monkeypatch.setattr(watchers, "is_removable_drive", lambda d: d.startswith("E"))
    u._handle("D:")  # cikarilabilir degil: sessizce atla
    assert mgr.calls == [] and notes == []
    u._handle("E:")
    assert mgr.calls == [(scan.CUSTOM, "E:\\", False)]
    assert "takıldı" in notes[0] and "Trojan:Usb" in notes[-1]


def test_usb_handle_reports_scan_failure(monkeypatch):
    notes = []
    u = watchers.UsbWatcher(FakeMgr(busy=1), notes.append)
    monkeypatch.setattr(watchers, "is_removable_drive", lambda d: True)
    u._handle("F:")
    assert "taranamadı" in notes[-1]
