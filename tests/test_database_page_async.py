from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PyQt6.QtGui import QIcon

from core.data.database_service import DatabaseCheckResult, DatabaseStatus
from ui.pages import database_page as db_page_module
from ui.pages.database_page import DatabasePage
from core.remote.server_capabilities import ServerCapabilities
from ui.widgets import database_management_components as db_components_module
from ui.widgets.database_management_components import DatabaseInstallMonitor


def _caps(**overrides) -> ServerCapabilities:
    data = {
        "arch": "x86_64",
        "has_curl": True,
        "has_wget": False,
        "has_screen": True,
        "has_sha256sum": True,
        "free_disk_gb": 20.0,
    }
    data.update(overrides)
    return ServerCapabilities(**data)


@pytest.fixture()
def page(_ensure_qapp, monkeypatch):
    monkeypatch.setattr(db_page_module.qta, "icon", lambda *args, **kwargs: QIcon())
    widget = DatabasePage()
    widget.service_locator = SimpleNamespace(
        server_capabilities=_caps(),
        server_capability_error="",
    )
    widget._refresh_all_status = lambda: None
    yield widget
    widget.close()
    widget.deleteLater()
    _ensure_qapp.processEvents()


def _first_db_id(page: DatabasePage) -> str:
    assert page._cards, "database cards should be initialized"
    return next(iter(page._cards.keys()))


def _first_managed_db_id(page: DatabasePage) -> str:
    for card in page._cards.values():
        if not card.db_info.builtin:
            return card.db_info.db_id
    pytest.skip("no managed database available")


def _managed_db_id(page: DatabasePage, target_db_id: str) -> str:
    if target_db_id not in page._cards:
        pytest.skip(f"{target_db_id} card unavailable")
    return target_db_id


def test_check_database_status_uses_effective_override_path(page: DatabasePage, monkeypatch):
    db_id = _first_managed_db_id(page)
    info = page._get_database_info(db_id)
    assert info is not None
    calls: list[str] = []

    monkeypatch.setattr(
        db_page_module,
        "get_config",
        lambda: {"databases": {"db_root": "/data/databases", "overrides": {db_id: "/custom/db"}}},
    )
    monkeypatch.setattr(page, "_expand_remote_path", lambda value: value)
    monkeypatch.setattr(page, "_make_ssh_run_fn", lambda: fake_run)

    def fake_run(cmd: str, timeout: int = 10):
        del timeout
        calls.append(cmd)
        if "du -sm" in cmd:
            return 0, "50000\n", ""
        return 0, "", ""

    monkeypatch.setattr(page, "_run_ssh", fake_run)

    result = page._check_database_status(info)

    assert result.status == DatabaseStatus.READY
    assert any("/custom/db" in cmd for cmd in calls)
    assert all("/data/databases/" not in cmd for cmd in calls)


def test_on_path_override_rejects_incomplete_existing_path(page: DatabasePage, monkeypatch):
    db_id = _first_managed_db_id(page)
    warnings = []
    saved = []
    page._ssh_service = MagicMock(is_connected=True)
    monkeypatch.setattr(page, "_pick_remote_db_root", lambda _start, anchor=None: "/remote/incomplete")
    monkeypatch.setattr(page, "_expand_remote_path", lambda value: value)
    monkeypatch.setattr(
        page,
        "_check_database_path_remote",
        lambda info, path: DatabaseCheckResult(info.db_id, DatabaseStatus.INCOMPLETE, f"bad path: {path}"),
    )
    monkeypatch.setattr(db_page_module, "get_config", lambda: {"databases": {"db_root": "/data/databases", "overrides": {}}})
    monkeypatch.setattr(db_page_module, "save_config", lambda payload: saved.append(payload))
    monkeypatch.setattr(db_page_module.QMessageBox, "warning", lambda *a, **kw: warnings.append((a, kw)))

    page._on_path_override(db_id)

    assert not saved
    assert warnings
    assert "bad path" in str(warnings[-1])


def test_on_path_override_saves_after_integrity_check(page: DatabasePage, monkeypatch):
    db_id = _first_managed_db_id(page)
    saved = []
    infos = []
    page._ssh_service = MagicMock(is_connected=True)
    monkeypatch.setattr(page, "_pick_remote_db_root", lambda _start, anchor=None: "/remote/ok")
    monkeypatch.setattr(page, "_expand_remote_path", lambda value: value)
    monkeypatch.setattr(
        page,
        "_check_database_path_remote",
        lambda info, path: DatabaseCheckResult(info.db_id, DatabaseStatus.READY, f"ok: {path}"),
    )
    monkeypatch.setattr(db_page_module, "get_config", lambda: {"databases": {"db_root": "/data/databases", "overrides": {}}})
    monkeypatch.setattr(db_page_module, "save_config", lambda payload: saved.append(payload))
    monkeypatch.setattr(db_page_module.QMessageBox, "information", lambda *a, **kw: infos.append((a, kw)))

    page._on_path_override(db_id)

    assert saved
    assert saved[-1]["databases"]["overrides"][db_id] == "/remote/ok"
    assert infos


def test_on_path_override_normalizes_prefix_database_to_canonical_value(page: DatabasePage, monkeypatch):
    db_id = _managed_db_id(page, "blast_nt")
    saved = []
    page._ssh_service = MagicMock(is_connected=True)
    monkeypatch.setattr(page, "_pick_remote_db_root", lambda _start, anchor=None: "/remote/blast_nt")
    monkeypatch.setattr(page, "_expand_remote_path", lambda value: value)
    monkeypatch.setattr(
        page,
        "_check_database_path_remote",
        lambda info, path: DatabaseCheckResult(info.db_id, DatabaseStatus.READY, f"ok: {path}"),
    )
    monkeypatch.setattr(db_page_module, "get_config", lambda: {"databases": {"db_root": "/data/databases", "overrides": {}}})
    monkeypatch.setattr(db_page_module, "save_config", lambda payload: saved.append(payload))
    monkeypatch.setattr(db_page_module.QMessageBox, "information", lambda *a, **kw: None)

    page._on_path_override(db_id)

    assert saved
    assert saved[-1]["databases"]["overrides"][db_id] == "/remote/blast_nt/nt"


def test_on_path_override_normalizes_specific_file_database_to_canonical_value(page: DatabasePage, monkeypatch):
    db_id = _managed_db_id(page, "gunc_db")
    saved = []
    page._ssh_service = MagicMock(is_connected=True)
    monkeypatch.setattr(page, "_pick_remote_db_root", lambda _start, anchor=None: "/remote/gunc")
    monkeypatch.setattr(page, "_expand_remote_path", lambda value: value)
    monkeypatch.setattr(
        page,
        "_check_database_path_remote",
        lambda info, path: DatabaseCheckResult(info.db_id, DatabaseStatus.READY, f"ok: {path}"),
    )
    monkeypatch.setattr(db_page_module, "get_config", lambda: {"databases": {"db_root": "/data/databases", "overrides": {}}})
    monkeypatch.setattr(db_page_module, "save_config", lambda payload: saved.append(payload))
    monkeypatch.setattr(db_page_module.QMessageBox, "information", lambda *a, **kw: None)

    page._on_path_override(db_id)

    assert saved
    assert saved[-1]["databases"]["overrides"][db_id] == "/remote/gunc/gunc_db_progenomes2.1.dmnd"


def test_set_ssh_service_triggers_recovery(page: DatabasePage, monkeypatch):
    calls = []
    monkeypatch.setattr(page, "_recover_running_install_monitors", lambda: calls.append("recover"))
    page._ssh_service = None
    page._ssh_client = None

    page.set_ssh_service(MagicMock(is_connected=True))

    assert calls == ["recover"]


def test_refresh_context_triggers_recovery(page: DatabasePage, monkeypatch):
    calls = []
    monkeypatch.setattr(page, "_recover_running_install_monitors", lambda: calls.append("recover"))
    page._ssh_service = MagicMock(is_connected=True)
    page._ssh_client = None

    page.refresh_context()

    assert calls == ["recover"]


def test_recover_running_install_monitors_starts_monitor_for_running_task(page: DatabasePage, monkeypatch):
    db_id = _first_managed_db_id(page)
    started = []
    page._ssh_service = MagicMock(is_connected=True)
    monkeypatch.setattr(
        page._database_service,
        "list_all",
        lambda: [SimpleNamespace(db_id=db_id)],
    )
    monkeypatch.setattr(
        page._database_service,
        "check_install_status",
        lambda _ssh_run_fn, _task_dir: {"status": "RUNNING"},
    )
    monkeypatch.setattr(page, "_start_install_monitor", lambda got_db_id, task_dir: started.append((got_db_id, task_dir)))
    monkeypatch.setattr(
        page,
        "_start_async_task",
        lambda _key, task_fn, on_success, on_error=None: on_success(task_fn()) or True,
    )

    page._recover_running_install_monitors()

    assert started == [(db_id, f"{page._database_service.INSTALL_BASE}/{db_id}")]


def test_database_install_monitor_emits_stall_when_heartbeat_stale_but_screen_alive(monkeypatch):
    class _FakeService:
        def check_install_status(self, ssh_run_fn, task_dir):
            del ssh_run_fn, task_dir
            return {"status": "RUNNING", "heartbeat": "1"}

        def read_install_log(self, ssh_run_fn, task_dir, tail=80):
            del ssh_run_fn, task_dir, tail
            return "35% 2.1MB/s 00:10"

        def parse_progress(self, log_text):
            del log_text
            return {"percent": 35, "speed": "2.1MB/s", "eta": "00:10"}

    def fake_run(cmd: str, timeout: int = 10):
        del timeout
        if cmd == "date +%s":
            return 0, "1000\n", ""
        if "screen -ls" in cmd:
            return 0, "", ""
        return 0, "", ""

    monitor = DatabaseInstallMonitor(
        database_service=_FakeService(),
        ssh_run_fn=fake_run,
        db_id="kraken2_standard",
        task_dir="/tmp/task_1",
        verify_db_path="/remote/db",
    )
    stalled = []
    finished = []
    monkeypatch.setattr(DatabaseInstallMonitor, "_is_heartbeat_stale", lambda self, _heartbeat_value: True)
    monkeypatch.setattr(DatabaseInstallMonitor, "_is_screen_running", lambda self: True)
    monkeypatch.setattr(db_components_module.time, "sleep", lambda _seconds: None)
    monitor.install_stalled = SimpleNamespace(emit=lambda db_id, message: (stalled.append((db_id, message)), monitor.cancel()))
    monitor.install_finished = SimpleNamespace(emit=lambda *args: finished.append(args))

    monitor.run()

    assert stalled
    assert stalled[0][0] == "kraken2_standard"
    assert "心跳超时" in stalled[0][1]
    assert not finished


def test_database_install_monitor_fails_on_stale_heartbeat_without_screen(monkeypatch):
    class _FakeService:
        def check_install_status(self, ssh_run_fn, task_dir):
            del ssh_run_fn, task_dir
            return {"status": "RUNNING", "heartbeat": "1"}

        def read_install_log(self, ssh_run_fn, task_dir, tail=80):
            del ssh_run_fn, task_dir, tail
            return "35% 2.1MB/s 00:10"

        def parse_progress(self, log_text):
            del log_text
            return {"percent": 35, "speed": "2.1MB/s", "eta": "00:10"}

    def fake_run(cmd: str, timeout: int = 10):
        del timeout
        if cmd == "date +%s":
            return 0, "1000\n", ""
        if "screen -ls" in cmd:
            return 1, "", ""
        return 0, "", ""

    monitor = DatabaseInstallMonitor(
        database_service=_FakeService(),
        ssh_run_fn=fake_run,
        db_id="kraken2_standard",
        task_dir="/tmp/task_2",
        verify_db_path="/remote/db",
    )
    finished = []
    monitor.install_finished.connect(lambda *args: finished.append(args))

    monitor.run()

    assert finished
    assert finished[0][0] == "kraken2_standard"
    assert finished[0][1] is False
    assert "心跳超时" in finished[0][2]


def test_save_db_root_async_success_persists(page: DatabasePage, monkeypatch):
    cfg = {"databases": {"db_root": "", "overrides": {}}}
    saved = []
    infos = []
    done = []

    monkeypatch.setattr(db_page_module, "get_config", lambda: cfg)
    monkeypatch.setattr(db_page_module, "save_config", lambda payload: saved.append(payload))
    monkeypatch.setattr(
        page,
        "_start_async_task",
        lambda _k, _fn, on_success, on_error=None: on_success(
            {"allow_create": False, "result": (True, "/home/zyserver/databases", "", False)}
        )
        or True,
    )
    monkeypatch.setattr(db_page_module.QMessageBox, "information", lambda *a, **kw: infos.append((a, kw)))
    page._ssh_service = MagicMock(is_connected=True)

    started = page._save_db_root("~/databases", done.append)

    assert started is True
    assert done == [True]
    assert page._db_root_value == "/home/zyserver/databases"
    assert saved
    assert infos


def test_save_db_root_async_rejects_when_task_running(page: DatabasePage, monkeypatch):
    warnings = []
    done = []
    page._ssh_service = MagicMock(is_connected=True)
    monkeypatch.setattr(page, "_start_async_task", lambda *a, **kw: False)
    monkeypatch.setattr(db_page_module.QMessageBox, "warning", lambda *a, **kw: warnings.append((a, kw)))

    started = page._save_db_root("~/databases", done.append)

    assert started is False
    assert done == [False]
    assert warnings


def test_submit_install_prevents_reentry(page: DatabasePage, monkeypatch):
    db_id = _first_db_id(page)
    infos = []
    page._install_submit_pending.add(db_id)
    monkeypatch.setattr(db_page_module.QMessageBox, "information", lambda *a, **kw: infos.append((a, kw)))

    page._submit_install_async(db_id, 0)

    assert infos, "should notify duplicate submit"


def test_submit_install_async_success_starts_monitor(page: DatabasePage, monkeypatch):
    db_id = _first_db_id(page)
    monitors = []
    page._ssh_service = MagicMock(is_connected=True)
    monkeypatch.setattr(page, "_make_ssh_run_fn", lambda: (lambda _cmd, _timeout=15: (0, "", "")))
    monkeypatch.setattr(page, "_start_install_monitor", lambda did, task_dir: monitors.append((did, task_dir)))
    monkeypatch.setattr(page._cards[db_id], "set_installing", lambda _installing: None)
    monkeypatch.setattr(
        page,
        "_start_async_task",
        lambda _k, _fn, on_success, on_error=None: on_success({"task_dir": "/tmp/task_1"}) or True,
    )

    page._submit_install_async(db_id, 0)

    assert (db_id, "/tmp/task_1") in monitors
    assert db_id not in page._install_submit_pending


def test_submit_install_emits_running_task_event(page: DatabasePage, monkeypatch):
    db_id = _first_db_id(page)
    page._ssh_service = MagicMock(is_connected=True)
    monkeypatch.setattr(page._cards[db_id], "set_installing", lambda _installing: None)
    monkeypatch.setattr(
        page,
        "_start_async_task",
        lambda _k, _fn, on_success, on_error=None: on_success({"task_dir": "/tmp/task_2"}) or True,
    )
    monkeypatch.setattr(page, "_start_install_monitor", lambda *_args, **_kwargs: None)

    events = []
    page.install_task_event.connect(lambda payload: events.append(payload))
    page._submit_install_async(db_id, 0)

    assert any(
        e.get("task_id") == f"db:{db_id}"
        and e.get("state") == "running"
        and e.get("message") == "正在提交安装任务"
        and e.get("location_hint") == "database"
        and "detail" not in e
        for e in events
    )


def test_progress_and_finish_emit_install_task_events(page: DatabasePage):
    db_id = _first_db_id(page)
    events = []
    page.install_task_event.connect(lambda payload: events.append(payload))

    page._on_progress_updated(db_id, 35, "2.1MB/s", "00:10")
    page._on_install_finished(db_id, True, "安装完成")

    assert any(
        e.get("state") == "running"
        and e.get("message") == "35% · 速度 2.1MB/s · 预计 00:10"
        and e.get("progress_value") == 35
        and e.get("progress_text") == "35%"
        and e.get("speed_text") == "2.1MB/s"
        and "detail" not in e
        for e in events
    )
    assert any(
        e.get("state") == "success"
        and e.get("message") == "安装完成"
        and e.get("location_hint") == "database"
        and "detail" not in e
        for e in events
    )


def test_submit_install_async_blocks_when_preflight_missing(page: DatabasePage, monkeypatch):
    db_id = _first_db_id(page)
    warnings = []
    page._ssh_service = MagicMock(is_connected=True)
    page.service_locator.server_capabilities = None
    page.service_locator.server_capability_error = "远端缺少 screen"
    monkeypatch.setattr(db_page_module.QMessageBox, "warning", lambda *a, **kw: warnings.append((a, kw)))

    page._submit_install_async(db_id, 0)

    assert warnings


def test_close_event_cleans_async_tasks(page: DatabasePage, monkeypatch):
    from PyQt6.QtGui import QCloseEvent

    stopped = []
    monkeypatch.setattr(page, "_cleanup_status_worker", lambda: None)
    monkeypatch.setattr(page, "_stop_install_monitor", lambda _db_id: None)
    monkeypatch.setattr(page, "_stop_async_task", lambda task_key: stopped.append(task_key))
    page._async_tasks = {"task:a": (None, None), "task:b": (None, None)}  # type: ignore[assignment]

    page.closeEvent(QCloseEvent())
    page._async_tasks = {}

    assert set(stopped) == {"task:a", "task:b"}
