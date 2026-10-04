import json
from datetime import datetime, timezone

import pytest

from auxy.core import paths, scan, threats
from auxy.core.service import AuxyError
from auxy.gui import scan_page
from auxy.gui.worker import FAST_MS, SLOW_MS, Worker


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("AUXY_HOME", str(tmp_path))
    import auxy.core.log as log

    monkeypatch.setattr(log, "_configured", False)
    yield tmp_path
    logger = log.get_logger()
    for h in list(logger.handlers):
        h.close()
        logger.removeHandler(h)


# ---- threats ----
def test_clean_resource_prefixes():
    assert threats.clean_resource(r"file:_C:\a\b.exe") == r"C:\a\b.exe"
    assert threats.clean_resource(r"containerfile:_C:\a.zip") == r"C:\a.zip"
    assert threats.clean_resource(r"C:\duz\yol.exe") == r"C:\duz\yol.exe"


def test_parse_dmtf_utc_and_offset():
    d = threats.parse_dmtf("20261004195413.691000+000")
    assert d == datetime(2026, 10, 4, 19, 54, 13, tzinfo=timezone.utc)
    # +180 dk sapma: yerel saat UTC'den 3 saat ileri -> UTC 16:54
    d2 = threats.parse_dmtf("20261004195413.000000+180")
    assert d2 == datetime(2026, 10, 4, 16, 54, 13, tzinfo=timezone.utc)
    assert threats.parse_dmtf("bozuk") is None


def test_to_local_naive_handles_str_datetime_and_junk():
    assert threats.to_local_naive("20261004195413.691000+000").tzinfo is None
    assert threats.to_local_naive(datetime(2026, 1, 1)) == datetime(2026, 1, 1)
    assert threats.to_local_naive(None) is None


# ---- scan ----
def test_build_scan_args(tmp_path):
    assert scan.build_scan_args(scan.QUICK) == ["-Scan", "-ScanType", "1"]
    assert scan.build_scan_args(scan.FULL) == ["-Scan", "-ScanType", "2"]
    f = tmp_path / "x.txt"
    f.write_text("a")
    assert scan.build_scan_args(scan.CUSTOM, str(f)) == ["-Scan", "-ScanType", "3", "-File", str(f)]


def test_build_scan_args_rejects_missing_or_invalid():
    with pytest.raises(AuxyError):
        scan.build_scan_args(scan.CUSTOM, None)
    with pytest.raises(AuxyError):
        scan.build_scan_args(scan.CUSTOM, r"C:\yok\boyle\yol")
    with pytest.raises(AuxyError):
        scan.build_scan_args(9)


def test_history_roundtrip_and_limit(home):
    for i in range(scan.HISTORY_LIMIT + 5):
        scan.append_history(scan.ScanResult(scan.QUICK, "", f"2026-10-04T10:{i % 60:02d}:00",
                                            1.0, scan.COMPLETED, 0, []))
    items = scan.load_history()
    assert len(items) == scan.HISTORY_LIMIT
    assert json.loads(paths.scan_history_file().read_text())  # gecerli json


def test_history_tolerates_corruption(home):
    paths.scan_history_file().write_text("{bozuk", encoding="utf-8")
    assert scan.load_history() == []


def test_summaries():
    mk = lambda **k: scan.ScanResult(k.pop("t", scan.QUICK), "", "2026-10-04T10:00:00", 5.0,  # noqa: E731
                                     k.pop("status", scan.COMPLETED), k.pop("code", 0),
                                     k.pop("threats", []))
    assert "tehdit bulunamadı" in mk().summary()
    assert "1 tehdit bulundu (EICAR)" in mk(threats=["EICAR"]).summary()
    assert "iptal edildi" in mk(status=scan.CANCELLED).summary()
    assert "başarısız" in mk(status=scan.FAILED, code=2).summary()
    assert scan.format_duration(125) == "02:05"


class FakeProc:
    def __init__(self, rc=0):
        self.returncode = rc

    def communicate(self):
        return b"Scan finished.", None


def test_manager_run_completed_and_records_threats(monkeypatch):
    monkeypatch.setattr(scan, "mpcmdrun_path", lambda: "MpCmdRun.exe")
    monkeypatch.setattr(scan.subprocess, "Popen", lambda *a, **k: FakeProc(0))
    monkeypatch.setattr(scan.threats, "read_detections", lambda: [
        threats.Detection(1, "Virus:Test", "Yüksek", ["C:\\x"], datetime.now()),
        threats.Detection(2, "Eski", "Düşük", [], datetime(2020, 1, 1)),
    ])
    res = scan.ScanManager().run(scan.QUICK)
    assert res.status == scan.COMPLETED and res.threats == ["Virus:Test"]
    assert scan.load_history()[-1].threats == ["Virus:Test"]


def test_manager_failed_and_cancelled(monkeypatch):
    monkeypatch.setattr(scan, "mpcmdrun_path", lambda: "MpCmdRun.exe")
    monkeypatch.setattr(scan.subprocess, "Popen", lambda *a, **k: FakeProc(2))
    m = scan.ScanManager()
    assert m.run(scan.QUICK).status == scan.FAILED
    m.mark_cancel_requested()
    # mark_cancel_requested yeni calismada sifirlanir; once calismayi baslat, sonra isaretle
    monkeypatch.setattr(scan.subprocess, "Popen", lambda *a, **k: _CancelProc(m))
    assert m.run(scan.FULL).status == scan.CANCELLED


class _CancelProc(FakeProc):
    def __init__(self, manager):
        super().__init__(2)
        self.manager = manager

    def communicate(self):
        self.manager.mark_cancel_requested()  # tarama sirasinda iptal istendi
        return b"", None


def test_manager_rejects_second_concurrent_scan(monkeypatch):
    monkeypatch.setattr(scan, "mpcmdrun_path", lambda: "MpCmdRun.exe")
    m = scan.ScanManager()
    m._proc = object()  # calisiyor gibi
    with pytest.raises(scan.ScanBusyError):
        m.run(scan.QUICK)


# ---- worker ----
def test_worker_interval_slow_only_for_long_jobs():
    w = Worker(lambda ms, cb: None)
    assert w._interval() == FAST_MS
    w._pending, w._long_pending = 1, 1
    assert w._interval() == SLOW_MS
    w._pending = 2  # yanina kisa is gelince hizli yoklama
    assert w._interval() == FAST_MS


# ---- gorunum bicimleri ----
def test_format_detection_and_history():
    d = threats.Detection(1, "Virus:DOS/EICAR_Test_File", "Çok yüksek", [r"C:\a\e.txt"],
                          datetime(2026, 10, 4, 22, 54), True)
    out = scan_page.format_detection(d)
    assert "2026-10-04 22:54" in out and "EICAR" in out and "işlem uygulandı" in out
    assert r"C:\a\e.txt" in out
    r = scan.ScanResult(scan.CUSTOM, r"C:\x", "2026-10-04T22:56:10", 3.0, scan.COMPLETED, 0, [])
    assert "2026-10-04 22:56" in scan_page.format_history_item(r)
