import threading
import time
from datetime import datetime, timedelta

from auxy.core import defender
from auxy.gui import viewmodel as vm
from auxy.gui.worker import Worker

NOW = datetime(2026, 10, 4, 12, 0, 0)


def make(**over):
    status = {k: None for k in defender.STATUS_FIELDS}
    status.update(
        AMServiceEnabled=True, AntivirusEnabled=True, RealTimeProtectionEnabled=True,
        BehaviorMonitorEnabled=True, IsTamperProtected=True,
        AntivirusSignatureLastUpdated=NOW - timedelta(hours=5),
    )
    prefs = dict(MAPSReporting=2, PUAProtection=1, EnableControlledFolderAccess=0,
                 EnableNetworkProtection=0, DisableRealtimeMonitoring=False)
    status.update(over.pop("status", {}))
    prefs.update(over.pop("prefs", {}))
    return defender.DefenderStatus(status=status, prefs=prefs)


def test_all_good_is_ok():
    h = vm.evaluate(make(), NOW)
    assert h.level == vm.OK


def test_realtime_off_is_critical():
    h = vm.evaluate(make(status={"RealTimeProtectionEnabled": False}), NOW)
    assert h.level == vm.CRIT and any("Gerçek zamanlı" in r for r in h.reasons)


def test_defender_off_is_critical():
    assert vm.evaluate(make(status={"AntivirusEnabled": False}), NOW).level == vm.CRIT


def test_old_signature_is_warning():
    old = NOW - timedelta(days=5)
    h = vm.evaluate(make(status={"AntivirusSignatureLastUpdated": old}), NOW)
    assert h.level == vm.WARN and "5 gün" in h.reasons[0]


def test_tamper_off_is_warning_and_maps_off_is_warning():
    h = vm.evaluate(make(status={"IsTamperProtected": False}, prefs={"MAPSReporting": 0}), NOW)
    assert h.level == vm.WARN and len(h.reasons) == 2


def test_crit_includes_warnings_too():
    h = vm.evaluate(make(status={"RealTimeProtectionEnabled": False,
                                 "IsTamperProtected": False}), NOW)
    assert h.level == vm.CRIT and len(h.reasons) == 2


def test_signature_age_unknown():
    assert vm.signature_age_days(make(status={"AntivirusSignatureLastUpdated": None})) is None


def test_worker_runs_off_thread_and_polls_only_while_pending():
    scheduled = []
    results = []
    w = Worker(lambda ms, cb: scheduled.append(cb))
    main = threading.get_ident()
    seen = {}

    def job():
        seen["thread"] = threading.get_ident()
        return 42

    w.submit(job, lambda res, exc: results.append((res, exc)))
    assert len(scheduled) == 1  # tek poll planlandi
    deadline = time.time() + 2
    while not results and time.time() < deadline:
        scheduled.pop(0)()  # tk.after'in cagiracagi sey
        if not results:
            scheduled.append(lambda: None) if not scheduled else None
            time.sleep(0.01)
            scheduled.insert(0, w._drain)
    assert results == [(42, None)]
    assert seen["thread"] != main
    # is bitince yeni poll planlanmaz
    scheduled.clear()
    w._drain()
    assert scheduled == []


def test_worker_reports_exceptions():
    scheduled = []
    results = []
    w = Worker(lambda ms, cb: scheduled.append(cb))

    def boom():
        raise ValueError("x")

    w.submit(boom, lambda res, exc: results.append((res, exc)))
    deadline = time.time() + 2
    while not results and time.time() < deadline:
        w._drain()
        time.sleep(0.01)
    assert results[0][0] is None and isinstance(results[0][1], ValueError)
