import threading
import time
from pathlib import Path

import pytest

from auxy.agent import helpers as helpers_mod
from auxy.agent import watchers
from auxy.core import config as cfgmod
from auxy.core import scan, system

REAL_SLEEP = time.sleep


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AUXY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AUXY_INSTANCE", "_backfill1")  # gercek GUI/ajan kilidine dokunma
    import auxy.core.log as log

    monkeypatch.setattr(log, "_configured", False)
    yield tmp_path
    logger = log.get_logger()
    for h in list(logger.handlers):
        h.close()
        logger.removeHandler(h)


# ---------------- surecler arasi tarama kilidi ----------------
def test_scan_lock_excludes_other_thread_and_releases():
    a_has, b_try, a_release, results = threading.Event(), threading.Event(), threading.Event(), {}

    def holder():
        lock = system.ScanLock()
        results["a"] = lock.acquire()
        a_has.set()
        b_try.wait(5)
        lock.release()
        a_release.set()

    def contender():
        lock = system.ScanLock()
        results["b1"] = lock.acquire()  # A tutarken: reddedilmeli
        b_try.set()
        a_release.wait(5)
        results["b2"] = lock.acquire()  # A biraktiktan sonra: alinmali
        lock.release()

    ta = threading.Thread(target=holder)
    ta.start()
    a_has.wait(5)
    tb = threading.Thread(target=contender)
    tb.start()
    ta.join(5)
    tb.join(5)
    assert results == {"a": True, "b1": False, "b2": True}


def test_scan_lock_abandoned_by_dead_thread_is_recovered():
    """Kilidi tutarken olen is parcacigi (cokmus surec benzeri): devralinabilmeli."""
    def die_holding():
        system.ScanLock().acquire()  # release etmeden biter

    t = threading.Thread(target=die_holding)
    t.start()
    t.join(5)
    # join() dondugunde isletim sistemi sahipligi henuz "terk edilmis" isaretlememis olabilir: en gec 2 sn icinde devralinmali
    lock = system.ScanLock()
    assert wait_for(lock.acquire, timeout=2.0)  # WAIT_ABANDONED devralinir
    lock.release()


class _P:
    returncode = 0

    def communicate(self):
        return b"", None


def test_manager_refuses_when_other_process_scans(monkeypatch, tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    monkeypatch.setattr(scan, "mpcmdrun_path", lambda: "MpCmdRun.exe")
    held, done = threading.Event(), threading.Event()

    def other_process():
        lock = system.ScanLock()
        lock.acquire()
        held.set()
        done.wait(5)
        lock.release()

    t = threading.Thread(target=other_process)
    t.start()
    held.wait(5)
    try:
        with pytest.raises(scan.ScanBusyError, match="Başka bir AuxySecurity"):
            scan.ScanManager().run(scan.CUSTOM, str(f))
    finally:
        done.set()
        t.join(5)
    # kilit serbest kalinca tarama calisir
    monkeypatch.setattr(scan.subprocess, "Popen", lambda *a, **k: _P())
    monkeypatch.setattr(scan.ScanManager, "_new_threats", staticmethod(lambda s: []))
    assert scan.ScanManager().run(scan.CUSTOM, str(f)).status == scan.COMPLETED


def test_lock_released_after_popen_failure_and_after_success(monkeypatch, tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    monkeypatch.setattr(scan, "mpcmdrun_path", lambda: "MpCmdRun.exe")

    def boom(*a, **k):
        raise OSError("baslatilamadi")

    monkeypatch.setattr(scan.subprocess, "Popen", boom)
    with pytest.raises(OSError):
        scan.ScanManager().run(scan.CUSTOM, str(f))
    probe = system.ScanLock()
    assert probe.acquire()  # kilit sizmadi
    probe.release()
    monkeypatch.setattr(scan.subprocess, "Popen", lambda *a, **k: _P())
    monkeypatch.setattr(scan.ScanManager, "_new_threats", staticmethod(lambda s: []))
    scan.ScanManager().run(scan.CUSTOM, str(f))
    probe2 = system.ScanLock()
    assert probe2.acquire()
    probe2.release()


# ---------------- alt klasor izleme ----------------
class FakeMgr:
    def __init__(self):
        self.calls = []

    def run(self, kind, path=None, quiet=False):
        self.calls.append(path)
        return scan.ScanResult(kind, path or "", "2026-10-05T10:00:00", 1.0, scan.COMPLETED, 0, [])


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


@pytest.mark.parametrize("recursive", [False, True])
def test_recursive_watch_option(tmp_path, fast_sleep, recursive):
    root = tmp_path / "indirilenler"
    sub = root / "alt" / "klasor"
    sub.mkdir(parents=True)
    mgr = FakeMgr()
    w = watchers.FolderWatcher([str(root)], mgr, lambda m: None, recursive=recursive)
    w.start()
    try:
        (sub / "derin.exe").write_bytes(b"MZ" + b"1" * 50)
        (root / "ust.exe").write_bytes(b"MZ" + b"2" * 50)
        assert wait_for(lambda: str(root / "ust.exe") in mgr.calls)
        REAL_SLEEP(1.0)
        assert (str(sub / "derin.exe") in mgr.calls) is recursive
    finally:
        w.stop()


def test_config_recursive_roundtrip_and_helper_restart():
    c = cfgmod.Config(watch_enabled=True, watch_folders=[r"C:\a"], watch_recursive=True)
    cfgmod.save(c)
    assert cfgmod.load().watch_recursive is True
    assert cfgmod.Config().watch_recursive is False
    s1 = helpers_mod.HelperManager.signatures(cfgmod.Config(watch_enabled=True, watch_folders=[r"C:\a"]))
    s2 = helpers_mod.HelperManager.signatures(c)
    assert s1["watch"] != s2["watch"]  # secenek degisince izleyici yeniden baslatilir


# ---------------- surukle-birak ----------------
# (app fixture'i tests/conftest.py'de: tum GUI testleri tek Tk kokunu paylasir)

def pump(a, cond, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        a.update()
        if cond():
            return True
        REAL_SLEEP(0.05)
    return False


def test_dnd_initialized_and_drop_filters_missing_paths(app, tmp_path):
    assert app.dnd_ready is True
    f = tmp_path / "a.txt"
    f.write_text("x")
    got = []
    app.pages["scan"].scan_paths = lambda paths: got.append(paths)
    app.on_drop([str(f), r"C:\yok\boyle\dosya"])
    assert got == [[str(f)]]
    app.on_drop([r"C:\yok"])  # hepsi yoksa hicbir sey yapma
    assert len(got) == 1


def test_drop_single_path_starts_custom_scan(app, tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    page = app.pages["scan"]
    seen = []
    page.start = lambda kind, path=None: seen.append((kind, path))
    page.scan_paths([str(f)])
    assert seen == [(scan.CUSTOM, str(f))]


def test_drop_multiple_paths_scans_each_and_summarizes(app, tmp_path):
    files = []
    for i in range(3):
        f = tmp_path / f"f{i}.txt"
        f.write_text("x")
        files.append(str(f))
    page = app.pages["scan"]
    calls = []

    def fake_run(kind, path=None, quiet=False):
        calls.append(path)
        threats = ["Trojan:Test"] if path == files[1] else []
        return scan.ScanResult(kind, path, "2026-10-05T10:00:00", 0.1, scan.COMPLETED, 0, threats)

    page.manager.run = fake_run
    page.scan_paths(files)
    assert pump(app, lambda: "tarandı" in page.status.cget("text"))
    assert calls == files
    assert "3 öğe tarandı" in page.status.cget("text") and "Trojan:Test" in page.status.cget("text")
    assert page.start_buttons[0].cget("state") == "normal"  # kilit acildi


def test_drop_multiple_stops_on_cancel(app, tmp_path):
    files = []
    for i in range(3):
        f = tmp_path / f"f{i}.txt"
        f.write_text("x")
        files.append(str(f))
    page = app.pages["scan"]
    calls = []

    def fake_run(kind, path=None, quiet=False):
        calls.append(path)
        page._cancel_all = True  # kullanici iptal etti
        return scan.ScanResult(kind, path, "2026-10-05T10:00:00", 0.1, scan.CANCELLED, 2, [])

    page.manager.run = fake_run
    page.scan_paths(files)
    assert pump(app, lambda: "tarandı" in page.status.cget("text"))
    assert calls == files[:1]  # ilkinden sonra durdu


def test_idle_progress_bar_hidden(app):
    page = app.pages["scan"]
    assert not page.progress.winfo_ismapped()
    page._set_busy(True)
    app.update()
    assert page.progress.winfo_ismapped()
    page._set_busy(False)
    app.update()
    assert not page.progress.winfo_ismapped()
