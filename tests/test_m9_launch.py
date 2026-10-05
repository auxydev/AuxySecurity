import argparse
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import pytest

from auxy import __main__ as cli
from auxy.agent import supervisor
from auxy.core import autostart, contextmenu, hardening, system


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AUXY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AUXY_INSTANCE", "_m9")
    import auxy.core.log as log

    monkeypatch.setattr(log, "_configured", False)
    yield
    logger = log.get_logger()
    for h in list(logger.handlers):
        h.close()
        logger.removeHandler(h)


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    """Paketlenmis (PyInstaller) surumu taklit eder: sys.frozen + kurulum klasoru."""
    d = tmp_path / "AuxySecurity"
    d.mkdir()
    (d / "AuxySecurity.exe").write_bytes(b"MZ")
    (d / "auxy.exe").write_bytes(b"MZ")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(d / "AuxySecurity.exe"))
    return d


# ---------------- baslatma komutlari ----------------
def test_dev_mode_uses_python_dash_m():
    assert not system.is_frozen() and system.install_dir() is None
    assert system.app_args(["gui"]) == ["-m", "auxy", "gui"]
    assert system.launch_params(["set", "pua", "off"]) == "-m auxy set pua off"
    assert system.app_exe(False) == sys.executable


def test_frozen_mode_uses_exes_and_direct_args(frozen):
    assert system.is_frozen() and system.install_dir() == frozen.resolve()
    assert system.app_exe(windowless=True) == str(frozen.resolve() / "AuxySecurity.exe")
    assert system.app_exe(windowless=False) == str(frozen.resolve() / "auxy.exe")  # konsol: CLI
    assert system.app_args(["gui"]) == ["gui"]  # '-m auxy' YOK
    assert system.launch_params(["scan-file", r"C:\a b\x.txt"]) == 'scan-file "C:\\a b\\x.txt"'


def test_frozen_falls_back_to_current_exe_if_sibling_missing(frozen):
    (frozen / "auxy.exe").unlink()
    assert system.app_exe(windowless=False) == sys.executable


def test_autostart_task_points_to_installed_exe_when_frozen(frozen, monkeypatch):
    seen = {}

    def fake_schtasks(*args):
        seen["xml"] = Path(args[args.index("/XML") + 1]).read_text(encoding="utf-16")

        class R:
            returncode, stdout, stderr = 0, "", ""

        return R()

    monkeypatch.setattr(system, "is_admin", lambda: True)
    monkeypatch.setattr(autostart, "_schtasks", fake_schtasks)
    autostart.install()
    root = ET.fromstring(seen["xml"].replace('encoding="UTF-16"', ""))
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    assert root.find(".//t:Exec/t:Command", ns).text == str(frozen.resolve() / "AuxySecurity.exe")
    assert root.find(".//t:Exec/t:Arguments", ns).text == "agent"  # '-m auxy' yok


def test_context_menu_command_when_frozen(frozen):
    cmd = contextmenu.command_line()
    assert cmd == f'{frozen.resolve() / "AuxySecurity.exe"} scan-file "%1"' or cmd.startswith('"')
    assert "-m auxy" not in cmd and cmd.endswith('scan-file "%1"')


def test_tray_open_gui_command_when_frozen(frozen, monkeypatch):
    from auxy.agent import tray

    calls = []
    monkeypatch.setattr(tray.subprocess, "Popen", lambda cmd, **k: calls.append(cmd))
    tray.Agent().open_gui()
    assert calls[0] == [str(frozen.resolve() / "AuxySecurity.exe"), "gui"]


def test_elevated_helper_command_when_frozen(frozen, monkeypatch):
    got = {}

    def fake_shell(*a):
        got["a"] = a
        return 42

    monkeypatch.setattr(system.ctypes.windll.shell32, "ShellExecuteW", fake_shell, raising=False)
    assert system.relaunch_as_admin(["gui"], windowless=True)
    assert got["a"][1] == "runas" and got["a"][2].endswith("AuxySecurity.exe") and got["a"][3] == "gui"


def test_install_location_frozen_under_program_files_is_safe(frozen, monkeypatch, tmp_path):
    pf = tmp_path / "Program Files"
    (pf / "AuxySecurity").mkdir(parents=True)
    (pf / "AuxySecurity" / "AuxySecurity.exe").write_bytes(b"MZ")
    monkeypatch.setenv("ProgramFiles", str(pf))
    monkeypatch.setattr(sys, "executable", str(pf / "AuxySecurity" / "AuxySecurity.exe"))
    assert not hardening.install_location_risk().risky  # T1 kapandi
    monkeypatch.setattr(sys, "executable", str(frozen / "AuxySecurity.exe"))  # kullanici dizini
    assert hardening.install_location_risk().risky


def test_frozen_gui_exe_defaults_to_gui_when_no_args(frozen, monkeypatch):
    opened = []
    monkeypatch.setattr(cli, "cmd_gui", lambda a: opened.append(1) or 0)
    monkeypatch.setattr(sys, "argv", ["AuxySecurity.exe"])
    assert cli.main() == 0 and opened == [1]


def test_version_is_1_0_0(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--version"])
    assert capsys.readouterr().out.strip() == "1.0.0"


# ---------------- yukseltilmis yardimci: izinli alt komutlar ----------------
def test_elevated_allowlist_blocks_unlisted_commands(monkeypatch):
    monkeypatch.setattr(system, "is_admin", lambda: True)
    ns = lambda cmd, result="x": argparse.Namespace(command=cmd, result=result)  # noqa: E731
    assert cli._enforce_elevated_allowlist(ns("set")) is True
    assert cli._enforce_elevated_allowlist(ns("firewall-rule")) is True
    assert cli._enforce_elevated_allowlist(ns("gui")) is False  # yukseltilmis modda GUI/ajan/vault vb. REDDEDILIR
    assert cli._enforce_elevated_allowlist(ns("vault")) is False
    assert cli._enforce_elevated_allowlist(ns("agent")) is False
    assert cli._enforce_elevated_allowlist(ns("gui", result=None)) is True  # normal (--result yok) kullanim etkilenmez
    monkeypatch.setattr(system, "is_admin", lambda: False)
    assert cli._enforce_elevated_allowlist(ns("gui")) is True  # yonetici degilsek kisit yok


def test_every_command_that_accepts_result_is_in_the_allowlist():
    """Yeni bir komuta --result eklenip izin listesine eklenmeyi unutulursa yukseltme akisi sessizce bozulurdu."""
    parser_src = Path(cli.__file__).read_text(encoding="utf-8")
    import re

    names = set(re.findall(r'sub\.add_parser\("([a-z-]+)"', parser_src))
    with_result = set()
    for name in names:
        block = re.search(rf'sub\.add_parser\("{name}"(.*?)(?=sub\.add_parser\(|\n    args = )', parser_src, re.S)
        if block and '"--result"' in block.group(1):
            with_result.add(name)
    assert with_result and with_result <= cli.ELEVATED_ALLOWED
    assert cli.ELEVATED_ALLOWED - with_result <= {"autostart"} | set()  # autostart --result ekleyen ayri blok olabilir


def test_main_returns_4_for_blocked_elevated_command(monkeypatch, capsys):
    monkeypatch.setattr(system, "is_admin", lambda: True)
    monkeypatch.setattr(cli, "_enforce_elevated_allowlist", lambda a: False)
    assert cli.main(["status"]) == 4


# ---------------- ajan denetcisi ----------------
class Clock:
    def __init__(self):
        self.t = 0.0
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def test_supervise_restarts_after_exception_then_returns_normal_exit():
    c = Clock()
    calls = []

    def serve():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("tray dongusu coktu")
        return 0

    assert supervisor.supervise(serve, c.sleep, c.now) == 0
    assert len(calls) == 3 and c.slept == [2, 5]  # artan bekleme


def test_supervise_gives_up_when_crashing_too_often_and_logs():
    from auxy.core import paths

    c = Clock()
    n = []

    def serve():
        n.append(1)
        raise ValueError("surekli coker")

    assert supervisor.supervise(serve, c.sleep, c.now) == 1
    assert len(n) == supervisor.MAX_CRASHES and c.slept == [2, 5, 15, 30]
    log = (paths.log_dir() / "auxy.log").read_text(encoding="utf-8")
    assert "AJAN COKTU (5/5" in log and "yeniden baslatma durduruldu" in log and "surekli coker" in log


def test_supervise_forgets_old_crashes_outside_window():
    c = Clock()
    n = []

    def serve():
        n.append(1)
        if len(n) <= 4:
            c.t += supervisor.WINDOW_S + 1  # her cokme arasinda pencere gecer: sayac sifirlanir
            raise RuntimeError("seyrek")
        return 0

    assert supervisor.supervise(serve, c.sleep, c.now) == 0 and len(n) == 5


def test_supervise_does_not_swallow_keyboard_interrupt_or_system_exit():
    with pytest.raises(KeyboardInterrupt):
        supervisor.supervise(lambda: (_ for _ in ()).throw(KeyboardInterrupt()), lambda s: None)
    with pytest.raises(SystemExit):
        supervisor.supervise(lambda: sys.exit(3), lambda s: None)


def test_agent_run_cleans_up_background_parts_even_when_tray_raises(monkeypatch):
    from auxy.agent import tray

    a = tray.Agent()
    stopped = []
    monkeypatch.setattr(a._helpers, "stop_all", lambda: stopped.append("helpers"))
    monkeypatch.setattr(a.icon, "run", lambda setup=None: (_ for _ in ()).throw(RuntimeError("pystray coktu")))
    monkeypatch.setattr(a, "_loop", lambda: None)
    with pytest.raises(RuntimeError):
        a.run()
    assert a._stop.is_set() and stopped == ["helpers"]  # yeniden baslatmada sizinti yok


def test_agent_restarts_inprocess_end_to_end(monkeypatch):
    """tray.run: ilk Agent coker, supervisor yenisini baslatir ve o normal cikar."""
    from auxy.agent import tray

    made = []

    class FakeAgent:
        def __init__(self):
            made.append(self)

        def run(self):
            if len(made) == 1:
                raise RuntimeError("ilk ajan coktu")
            return 0

    monkeypatch.setattr(tray, "Agent", FakeAgent)
    monkeypatch.setattr(supervisor.time, "sleep", lambda s: None)
    assert tray.run() == 0 and len(made) == 2


# ---------------- gercek surec: PyInstaller'siz, donmus taklidi ile cokme -> yeniden baslama ----------------
def test_real_subprocess_supervisor_recovers_and_exits_zero(tmp_path):
    home = tmp_path / "h"
    code = (
        "import sys, time\n"
        "from auxy.agent import supervisor\n"
        "supervisor.time.sleep = lambda s: None\n"
        "n = []\n"
        "def serve():\n"
        "    n.append(1)\n"
        "    if len(n) < 3: raise RuntimeError('gercek surec ici cokme')\n"
        "    return 0\n"
        "sys.exit(supervisor.supervise(serve))\n"
    )
    import os

    env = {**os.environ, "AUXY_HOME": str(home), "AUXY_INSTANCE": "_m9sub"}
    p = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, timeout=60)
    assert p.returncode == 0
    log = (home / "logs" / "auxy.log").read_text(encoding="utf-8")
    assert log.count("AJAN COKTU") == 2 and "gercek surec ici cokme" in log
