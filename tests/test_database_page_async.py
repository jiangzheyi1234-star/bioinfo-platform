from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PyQt6.QtGui import QIcon

from ui.pages import database_page as db_page_module
from ui.pages.database_page import DatabasePage
from core.remote.server_capabilities import ServerCapabilities


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
