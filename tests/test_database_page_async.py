from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ui.pages import database_page as db_page_module
from ui.pages.database_page import DatabasePage


@pytest.fixture()
def page(_ensure_qapp):
    widget = DatabasePage()
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
