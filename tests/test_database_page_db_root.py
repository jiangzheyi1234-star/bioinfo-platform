from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QMessageBox

from ui.pages.database_page import DatabasePage

pytestmark = pytest.mark.ui


@pytest.fixture(scope="module")
def qapp(_ensure_qapp):
    yield _ensure_qapp


def test_page_has_settings_button_only(qapp):
    page = DatabasePage()
    assert hasattr(page, "db_settings_btn")
    assert not hasattr(page, "db_root_edit")
    page.close()


def test_save_db_root_empty_uses_home_choice_and_auto_creates(qapp, monkeypatch):
    page = DatabasePage()
    page._ssh_client = object()

    saved = {}
    monkeypatch.setattr(
        "ui.pages.database_page.get_config",
        lambda: {"databases": {"db_root": "", "overrides": {}}, "runtime": {}},
    )
    monkeypatch.setattr("ui.pages.database_page.save_config", lambda cfg: saved.update(cfg))
    monkeypatch.setattr(page, "_refresh_all_status", lambda: None)
    monkeypatch.setattr(page, "_resolve_empty_db_root_candidate", lambda: "~/databases")

    infos: list[str] = []
    warns: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: infos.append(str(args[2])))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warns.append(str(args[2])))

    def fake_run(cmd: str, timeout: int = 10):
        del timeout
        if "p='~/databases';" in cmd:
            return 0, "/home/tester/databases\n", ""
        if cmd.startswith("test -d /home/tester/databases"):
            return 1, "", ""
        if cmd.startswith("mkdir -p /home/tester/databases"):
            return 0, "", ""
        if cmd.startswith("test -x /home/tester/databases"):
            return 0, "", ""
        if cmd.startswith("test -w /home/tester/databases"):
            return 0, "", ""
        if cmd.startswith("touch /home/tester/databases/.h2ometa_write_probe"):
            return 0, "", ""
        return 1, "", f"unexpected cmd: {cmd}"

    monkeypatch.setattr(page, "_run_ssh", fake_run)

    ok = page._save_db_root("")

    assert ok is True
    assert warns == []
    assert saved["databases"]["db_root"] == "/home/tester/databases"
    assert page._get_db_root() == "/home/tester/databases"
    assert any("已自动创建并保存目录" in m for m in infos)

    page.close()


def test_save_db_root_empty_manual_input_stops_save(qapp, monkeypatch):
    page = DatabasePage()
    page._ssh_client = object()

    save_calls: list[dict] = []
    monkeypatch.setattr(
        "ui.pages.database_page.get_config",
        lambda: {"databases": {"db_root": "", "overrides": {}}, "runtime": {}},
    )
    monkeypatch.setattr("ui.pages.database_page.save_config", lambda cfg: save_calls.append(cfg))
    monkeypatch.setattr(page, "_refresh_all_status", lambda: None)
    monkeypatch.setattr(page, "_resolve_empty_db_root_candidate", lambda: "")

    ok = page._save_db_root("")

    assert ok is False
    assert save_calls == []
    page.close()


def test_save_db_root_existing_path_saves_without_create(qapp, monkeypatch):
    page = DatabasePage()
    page._ssh_client = object()

    saved = {}
    monkeypatch.setattr(
        "ui.pages.database_page.get_config",
        lambda: {"databases": {"db_root": "", "overrides": {}}, "runtime": {}},
    )
    monkeypatch.setattr("ui.pages.database_page.save_config", lambda cfg: saved.update(cfg))
    monkeypatch.setattr(page, "_refresh_all_status", lambda: None)

    infos: list[str] = []
    warns: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: infos.append(str(args[2])))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warns.append(str(args[2])))

    def fake_run(cmd: str, timeout: int = 10):
        del timeout
        if "p=/data/databases/;" in cmd:
            return 0, "/data/databases/\n", ""
        if cmd.startswith("test -d /data/databases"):
            return 0, "", ""
        if cmd.startswith("test -x /data/databases"):
            return 0, "", ""
        if cmd.startswith("test -w /data/databases"):
            return 0, "", ""
        if cmd.startswith("touch /data/databases/.h2ometa_write_probe"):
            return 0, "", ""
        if cmd.startswith("mkdir -p /data/databases"):
            return 1, "", "should not create"
        return 1, "", f"unexpected cmd: {cmd}"

    monkeypatch.setattr(page, "_run_ssh", fake_run)

    ok = page._save_db_root("/data/databases/")

    assert ok is True
    assert warns == []
    assert saved["databases"]["db_root"] == "/data/databases"
    assert page._get_db_root() == "/data/databases"
    assert any("数据库根目录已保存" in m for m in infos)

    page.close()


def test_save_db_root_blocks_on_permission_denied(qapp, monkeypatch):
    page = DatabasePage()
    page._ssh_client = object()

    save_calls: list[dict] = []
    monkeypatch.setattr(
        "ui.pages.database_page.get_config",
        lambda: {"databases": {"db_root": "", "overrides": {}}, "runtime": {}},
    )
    monkeypatch.setattr("ui.pages.database_page.save_config", lambda cfg: save_calls.append(cfg))
    monkeypatch.setattr(page, "_refresh_all_status", lambda: None)

    infos: list[str] = []
    warns: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: infos.append(str(args[2])))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warns.append(str(args[2])))

    def fake_run(cmd: str, timeout: int = 10):
        del timeout
        if "p=/data/databases;" in cmd:
            return 0, "/data/databases\n", ""
        if cmd.startswith("test -d /data/databases"):
            return 0, "", ""
        if cmd.startswith("test -x /data/databases"):
            return 0, "", ""
        if cmd.startswith("test -w /data/databases"):
            return 1, "", "permission denied"
        if cmd == "whoami":
            return 0, "tester\n", ""
        return 1, "", f"unexpected cmd: {cmd}"

    monkeypatch.setattr(page, "_run_ssh", fake_run)

    ok = page._save_db_root("/data/databases")

    assert ok is False
    assert infos == []
    assert save_calls == []
    assert warns
    assert "chown tester:tester /data/databases" in warns[0]
    assert "chgrp bio /data/databases" in warns[0]

    page.close()


def test_pick_remote_db_root_returns_selected_path(qapp, monkeypatch):
    page = DatabasePage()
    page._ssh_client = object()

    warnings: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(str(args[2])))

    captured_start: list[str] = []

    class _FakeDialog:
        def __init__(self, start_path, list_dirs_fn, parent=None):
            del list_dirs_fn, parent
            captured_start.append(start_path)
            self.selected_path = "/home/tester/databases"

        def exec(self):
            return 1

    monkeypatch.setattr("ui.pages.database_page.RemoteDirectoryPickerDialog", _FakeDialog)

    selected = page._pick_remote_db_root("~")

    assert warnings == []
    assert captured_start == ["~"]
    assert selected == "/home/tester/databases"

    page.close()


def test_open_settings_dialog_passes_current_db_root(qapp, monkeypatch):
    page = DatabasePage()
    page._ssh_client = object()
    page._db_root_value = "/data/databases"

    captured_initial: list[str] = []

    class _FakeDialog:
        def __init__(self, initial_path, info_fn, browse_fn, save_fn, parent=None):
            del info_fn, browse_fn, save_fn, parent
            captured_initial.append(initial_path)

        def exec(self):
            return 1

    monkeypatch.setattr("ui.pages.database_page.DatabaseSettingsDialog", _FakeDialog)
    page._open_db_settings_dialog()

    assert captured_initial == ["/data/databases"]
    page.close()


def test_collect_db_root_info_degrades_without_ssh(qapp):
    page = DatabasePage()
    page._ssh_client = None
    info = page._collect_db_root_info("/data/databases")
    assert info["user"] == "--"
    assert info["resolved"] == "--"
    assert info["disk"] == "--"
    page.close()


def test_list_remote_directories_success(qapp, monkeypatch):
    page = DatabasePage()
    page._ssh_client = object()

    def fake_run(cmd: str, timeout: int = 10):
        del timeout
        if "p='~/databases';" in cmd:
            return 0, "/home/tester/databases\n", ""
        if cmd.startswith("test -d /home/tester/databases"):
            return 0, "", ""
        if cmd.startswith("find /home/tester/databases "):
            return 0, "alpha\nbeta\n", ""
        return 1, "", f"unexpected cmd: {cmd}"

    monkeypatch.setattr(page, "_run_ssh", fake_run)
    ok, resolved, dirs, message = page._list_remote_directories("~/databases")

    assert ok is True
    assert resolved == "/home/tester/databases"
    assert dirs == ["alpha", "beta"]
    assert message == ""

    page.close()


def test_list_remote_directories_not_exists(qapp, monkeypatch):
    page = DatabasePage()
    page._ssh_client = object()

    def fake_run(cmd: str, timeout: int = 10):
        del timeout
        if "p=/missing/path;" in cmd:
            return 0, "/missing/path\n", ""
        if cmd.startswith("test -d /missing/path"):
            return 1, "", ""
        return 1, "", f"unexpected cmd: {cmd}"

    monkeypatch.setattr(page, "_run_ssh", fake_run)
    ok, _, _, message = page._list_remote_directories("/missing/path")

    assert ok is False
    assert "目录不存在" in message

    page.close()


def test_resolve_empty_candidate_uses_saved_preference(qapp, monkeypatch):
    page = DatabasePage()
    page._ssh_client = object()
    monkeypatch.setattr(
        "ui.pages.database_page.get_config",
        lambda: {"databases": {"db_root": "", "overrides": {}}, "runtime": {"db_root_empty_action": "use_home"}},
    )

    assert page._resolve_empty_db_root_candidate() == "~/databases"

    page.close()
