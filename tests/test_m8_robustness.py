import os
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from auxy import __main__ as cli
from auxy.core import autostart, crashlog, system


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AUXY_HOME", str(tmp_path / "home"))
    import auxy.core.log as log

    monkeypatch.setattr(log, "_configured", False)
    saved = (threading.excepthook, sys.excepthook, sys.unraisablehook)
    yield
    threading.excepthook, sys.excepthook, sys.unraisablehook = saved
    logger = log.get_logger()
    for h in list(logger.handlers):
        h.close()
        logger.removeHandler(h)


def log_text() -> str:
    from auxy.core import paths

    p = paths.log_dir() / "auxy.log"
    return p.read_text(encoding="utf-8") if p.exists() else ""


# ---------------- yakalanmamis istisna kancalari ----------------
def test_thread_exception_is_logged_with_traceback_and_thread_name():
    crashlog.install("test-bileseni")

    def boom():
        raise ValueError("izleme dongusu coktu")

    t = threading.Thread(target=boom, name="auxy-test-thread")
    t.start()
    t.join()
    text = log_text()
    assert "YAKALANMAMIS ISTISNA [test-bileseni]" in text and "auxy-test-thread" in text
    assert "ValueError: izleme dongusu coktu" in text and "Traceback" in text


def test_system_exit_in_thread_is_not_logged_as_error():
    crashlog.install("x")

    def quit_():
        raise SystemExit(0)

    t = threading.Thread(target=quit_)
    t.start()
    t.join()
    assert "YAKALANMAMIS" not in log_text()


def test_main_thread_hook_logs_and_chains(monkeypatch):
    crashlog.install("ana")
    chained = []
    monkeypatch.setattr(sys, "__excepthook__", lambda t, v, tb: chained.append(t))
    try:
        raise RuntimeError("ana is parcacigi")
    except RuntimeError:
        sys.excepthook(*sys.exc_info())
    assert "YAKALANMAMIS ISTISNA [ana] ana is parcacigi" in log_text() and chained == [RuntimeError]
    chained.clear()
    try:
        raise KeyboardInterrupt
    except KeyboardInterrupt:
        sys.excepthook(*sys.exc_info())
    assert chained == [KeyboardInterrupt]  # Ctrl+C hata gibi gunluge yazilmaz ama zincirlenir
    assert log_text().count("YAKALANMAMIS") == 1


def test_unraisable_hook_logs():
    crashlog.install("u")

    class Unraisable:
        err_msg, exc_type, exc_value, exc_traceback = "finalizer", ValueError, ValueError("v"), None

    sys.unraisablehook(Unraisable())
    assert "finalizer" in log_text()


def test_log_exception_helper():
    try:
        raise OSError("disk")
    except OSError as exc:
        crashlog.log_exception("yedek yazma", exc)
    assert "ISTISNA [yedek yazma]" in log_text() and "OSError: disk" in log_text()


# ---------------- ajan cokme sarmalayicisi ----------------
def test_agent_wrapper_returns_nonzero_and_logs_on_crash(monkeypatch):
    from auxy.agent import tray

    def boom():
        raise RuntimeError("tray dongusu coktu")

    monkeypatch.setattr(tray, "run", boom)
    assert cli.main(["agent"]) == 1
    text = log_text()
    assert "AJAN COKTU" in text and "tray dongusu coktu" in text


def test_agent_wrapper_passes_through_normal_exit(monkeypatch):
    from auxy.agent import tray

    monkeypatch.setattr(tray, "run", lambda: 0)
    assert cli.main(["agent"]) == 0
    assert "AJAN COKTU" not in log_text()


def test_real_subprocess_crash_exit_code_and_log(tmp_path):
    """Gercek bir alt surecte: tray.run coker -> cikis kodu 1 (Gorev Zamanlayici yeniden baslatir) ve gunluk dolu."""
    home = tmp_path / "subhome"
    code = (
        "import sys; from auxy.agent import tray\n"
        "def boom(): raise RuntimeError('gercek surec cokmesi')\n"
        "tray.run = boom\n"
        "from auxy.__main__ import main\n"
        "sys.exit(main(['agent']))\n"
    )
    env = {**os.environ, "AUXY_HOME": str(home), "AUXY_INSTANCE": "_crashtest"}
    proc = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, timeout=60)
    assert proc.returncode == 1
    log = (home / "logs" / "auxy.log").read_text(encoding="utf-8")
    assert "AJAN COKTU" in log and "gercek surec cokmesi" in log


def test_gui_callback_exceptions_are_logged(app):
    try:
        raise ValueError("dugme isleyicisi hatasi")
    except ValueError:
        app.report_callback_exception(*sys.exc_info())
    assert "GUI olay isleyicisi istisnasi" in log_text() and "dugme isleyicisi hatasi" in log_text()


# ---------------- gorev: hata durumunda yeniden baslat ----------------
def test_task_xml_restarts_on_failure():
    xml = autostart.build_task_xml("PC\\kullanici", r"C:\x\pythonw.exe", r"C:\proje")
    root = ET.fromstring(xml.replace('encoding="UTF-16"', ""))
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    assert root.find(".//t:RestartOnFailure/t:Interval", ns).text == "PT1M"
    assert root.find(".//t:RestartOnFailure/t:Count", ns).text == "3"


# ---------------- calisma kumesi / simge onbellegi ----------------
def test_trim_working_set_reduces_working_set_without_breaking_anything():
    import psutil

    blob = bytearray(40 * 1024 * 1024)  # 40 MB dokun
    for i in range(0, len(blob), 4096):
        blob[i] = 1
    before = psutil.Process().memory_info().rss
    assert system.trim_working_set() is True
    after = psutil.Process().memory_info().rss
    assert after < before * 0.6  # belirgin kuculur
    assert blob[4096] == 1 and sum(blob[::4096]) == len(blob[::4096])  # veri bozulmaz, sayfalar geri yuklenir


def test_icon_is_cached_per_level():
    from auxy.agent.icon import make_icon

    assert make_icon("ok") is make_icon("ok") and make_icon("ok") is not make_icon("crit")
    assert make_icon(None).size == (64, 64)


def test_agent_refresh_trims_working_set(monkeypatch):
    from auxy.agent import tray

    agent = tray.Agent()
    trims = []
    monkeypatch.setattr(system, "trim_working_set", lambda: trims.append(1))
    monkeypatch.setattr(tray.defender, "read_status", lambda: (_ for _ in ()).throw(RuntimeError("wmi yok")))
    agent.refresh()  # WMI hatasi ajani dusurmez; yine de kuculturur
    assert trims == [1] and agent.health is None
