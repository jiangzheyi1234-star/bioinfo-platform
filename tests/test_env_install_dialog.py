from __future__ import annotations

import pytest

from core.environment.h2o_env_paths import H2O_CONDA_EXE
from ui.widgets.linux_settings_components import EnvInstallDialog


@pytest.fixture(autouse=True)
def _stub_qtawesome(monkeypatch):
    from PyQt6.QtGui import QIcon
    import ui.widgets.linux_settings_components as components

    monkeypatch.setattr(components.qta, "icon", lambda *_args, **_kwargs: QIcon())
    monkeypatch.setattr(components.qta, "Spin", lambda *_args, **_kwargs: None)


def _make_dialog() -> EnvInstallDialog:
    return EnvInstallDialog(
        {
            "id": "fastp",
            "name": "fastp",
            "conda_env": "fastp_env",
            "install_cmd": "conda create -n fastp_env -y",
        },
        conda_executable=H2O_CONDA_EXE,
    )


def test_start_install_shows_immediate_feedback_and_emits(qapp):
    dialog = _make_dialog()
    requested = {"tool_id": ""}
    dialog.install_requested.connect(lambda tool_id: requested.__setitem__("tool_id", tool_id))

    assert dialog.minimumHeight() == 360
    assert dialog._log_content.isHidden() is True
    assert dialog._log_content.maximumHeight() == 0

    dialog._on_start_install()

    assert requested["tool_id"] == "fastp"
    assert "[INFO] 正在连接服务器，提交后台安装任务..." in dialog.output_edit.toPlainText()
    assert dialog.install_btn.isHidden() is True

    dialog.close()
    qapp.processEvents()


def test_running_snapshot_keeps_running_mode_and_updates_log(qapp):
    dialog = _make_dialog()

    dialog.apply_install_snapshot(
        {
            "status": "RUNNING",
            "message": "后台安装任务执行中",
            "log_text": "Collecting package metadata\nSolving environment: done",
            "updated_at": 1,
        }
    )
    assert dialog.install_btn.isHidden() is True
    assert "Collecting package metadata" in dialog.output_edit.toPlainText()

    dialog.close()
    qapp.processEvents()


def test_log_drawer_auto_expand_and_manual_expand_persists(qapp):
    dialog = _make_dialog()

    assert dialog._log_drawer.isHidden() is False
    assert dialog._log_content.isHidden() is True
    assert dialog._log_content.maximumHeight() == 0

    dialog.apply_install_snapshot(
        {
            "status": "FAILED",
            "message": "安装失败",
            "updated_at": 1,
        }
    )
    assert dialog._log_content.isHidden() is False
    assert dialog._log_content.maximumHeight() == dialog._EXPANDED_LOG_MAX_HEIGHT

    dialog._toggle_log_drawer()
    assert dialog._log_content.isHidden() is True
    assert dialog._log_content.maximumHeight() == 0

    dialog._toggle_log_drawer()
    assert dialog._log_content.isHidden() is False
    assert dialog._log_content.maximumHeight() == dialog._EXPANDED_LOG_MAX_HEIGHT

    dialog.apply_install_snapshot(
        {
            "status": "RUNNING",
            "log_text": "Downloading packages 20%",
            "updated_at": 2,
        }
    )
    assert dialog._log_content.isHidden() is False

    dialog.close()
    qapp.processEvents()


def test_failed_guidance_is_appended_once_and_resets_on_retry(qapp):
    dialog = _make_dialog()

    failed_snapshot = {
        "status": "FAILED",
        "message": "安装失败",
        "updated_at": 1,
    }
    dialog.apply_install_snapshot(failed_snapshot)
    dialog.apply_install_snapshot(failed_snapshot)

    first_log = dialog.output_edit.toPlainText()
    assert first_log.count("[DIAG] 排查建议") == 1

    dialog._on_start_install()
    dialog.apply_install_snapshot(
        {
            "status": "FAILED",
            "message": "安装失败",
            "updated_at": 2,
        }
    )
    second_log = dialog.output_edit.toPlainText()
    assert second_log.count("[DIAG] 排查建议") == 1

    dialog.close()
    qapp.processEvents()


def test_terminal_state_ignores_late_running_snapshots(qapp):
    dialog = _make_dialog()

    dialog.apply_install_snapshot(
        {
            "status": "DONE",
            "message": "安装成功",
            "updated_at": 10,
        }
    )
    dialog.apply_install_snapshot(
        {
            "status": "RUNNING",
            "message": "50%",
            "log_text": "Downloading and Extracting Packages:\npython 50%",
            "updated_at": 11,
        }
    )

    assert dialog.install_btn.text() == "完成"

    dialog.close()
    qapp.processEvents()

    dialog = _make_dialog()
    dialog.apply_install_snapshot(
        {
            "status": "FAILED",
            "message": "安装失败",
            "updated_at": 20,
        }
    )
    dialog.apply_install_snapshot(
        {
            "status": "RUNNING",
            "message": "80%",
            "log_text": "Downloading and Extracting Packages:\npython 80%",
            "updated_at": 21,
        }
    )

    assert dialog.install_btn.text() == "重试"

    dialog.close()
    qapp.processEvents()


def test_older_snapshot_is_ignored(qapp):
    dialog = _make_dialog()

    dialog.apply_install_snapshot(
        {
            "status": "RUNNING",
            "message": "73% · 速度 2.1MB/s",
            "log_text": "Downloading and Extracting Packages:\npython 73% 2.1MB/s",
            "updated_at": 5,
        }
    )
    dialog.apply_install_snapshot(
        {
            "status": "RUNNING",
            "message": "20%",
            "log_text": "Downloading and Extracting Packages:\npython 20%",
            "updated_at": 4,
        }
    )

    assert "73%" in dialog.output_edit.toPlainText()

    dialog.close()
    qapp.processEvents()
