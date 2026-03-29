from __future__ import annotations

import json

import pytest
from PyQt6.QtCore import QObject, Qt
from PyQt6.QtWidgets import QWidget

from core.environment.h2o_env_paths import H2O_CONDA_EXE
from ui.widgets.linux_settings_components import EnvInstallDialog


class _FakePage(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.channel = None

    def setWebChannel(self, channel) -> None:
        self.channel = channel


class _FakeWebView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._page = _FakePage(self)
        self.url = None

    def page(self):
        return self._page

    def setUrl(self, url) -> None:
        self.url = url


@pytest.fixture(autouse=True)
def _stub_webview(monkeypatch):
    import ui.widgets.linux_settings_components as components

    monkeypatch.setattr(
        components,
        "create_local_web_ui_host",
        lambda **kwargs: (_FakeWebView(kwargs.get("parent")), object()),
    )


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


def test_request_tool_info_replays_info_and_initial_snapshot(qapp):
    dialog = _make_dialog()
    tool_infos = []
    snapshots = []
    dialog._install_bridge.toolInfoReady.connect(lambda raw: tool_infos.append(json.loads(raw)))
    dialog._install_bridge.snapshotUpdated.connect(lambda raw: snapshots.append(json.loads(raw)))

    dialog._install_bridge.requestToolInfo()

    assert tool_infos
    assert tool_infos[-1]["name"] == "fastp"
    assert snapshots
    assert snapshots[-1]["status"] == "IDLE"
    assert snapshots[-1]["primary_label"] == "开始安装"

    dialog.close()
    qapp.processEvents()


def test_dialog_uses_independent_non_modal_window_flags(qapp):
    dialog = _make_dialog()

    flags = dialog.windowFlags()
    assert bool(flags & Qt.WindowType.Window)
    assert bool(flags & Qt.WindowType.WindowMinimizeButtonHint)
    assert bool(flags & Qt.WindowType.WindowCloseButtonHint)
    assert dialog.windowModality() == Qt.WindowModality.NonModal

    dialog.close()
    qapp.processEvents()


def test_request_install_emits_signal_and_immediate_snapshot(qapp):
    dialog = _make_dialog()
    requested = {"tool_id": ""}
    snapshots = []
    dialog.install_requested.connect(lambda tool_id: requested.__setitem__("tool_id", tool_id))
    dialog._install_bridge.snapshotUpdated.connect(lambda raw: snapshots.append(json.loads(raw)))

    dialog._install_bridge.requestInstall()

    assert requested["tool_id"] == "fastp"
    assert snapshots
    assert snapshots[-1]["status"] == "SUBMITTING"
    assert "[INFO] 正在连接服务器，提交后台安装任务..." in snapshots[-1]["log_text"]
    assert snapshots[-1]["primary_enabled"] is False

    dialog.close()
    qapp.processEvents()


def test_apply_install_snapshot_emits_running_payload(qapp):
    dialog = _make_dialog()
    snapshots = []
    dialog._install_bridge.snapshotUpdated.connect(lambda raw: snapshots.append(json.loads(raw)))

    dialog.apply_install_snapshot(
        {
            "status": "RUNNING",
            "message": "后台安装任务执行中",
            "log_text": "Collecting package metadata\nSolving environment: done",
            "updated_at": 1,
        }
    )

    assert snapshots
    assert snapshots[-1]["status"] == "RUNNING"
    assert snapshots[-1]["phase_text"] == "正在解析依赖"
    assert "Collecting package metadata" in snapshots[-1]["log_text"]

    dialog.close()
    qapp.processEvents()


def test_failed_guidance_is_appended_once_and_resets_on_retry(qapp):
    dialog = _make_dialog()

    dialog.apply_install_snapshot(
        {
            "status": "FAILED",
            "message": "安装失败",
            "updated_at": 1,
        }
    )
    first_payload = dict(dialog._latest_snapshot_payload)
    dialog.apply_install_snapshot(
        {
            "status": "FAILED",
            "message": "安装失败",
            "updated_at": 1,
        }
    )

    assert first_payload["log_text"].count("[DIAG] 排查建议") == 1
    assert str(dialog._latest_snapshot_payload["log_text"]).count("[DIAG] 排查建议") == 1

    dialog._install_bridge.requestInstall()
    dialog.apply_install_snapshot(
        {
            "status": "FAILED",
            "message": "安装失败",
            "updated_at": 2,
        }
    )

    assert str(dialog._latest_snapshot_payload["log_text"]).count("[DIAG] 排查建议") == 1

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

    assert dialog._latest_snapshot_payload["status"] == "DONE"
    assert dialog._latest_snapshot_payload["primary_label"] == "关闭"

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

    assert dialog._latest_snapshot_payload["status"] == "FAILED"
    assert dialog._latest_snapshot_payload["primary_label"] == "重试"

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

    assert "73%" in str(dialog._latest_snapshot_payload["log_text"])

    dialog.close()
    qapp.processEvents()


def test_unknown_snapshot_status_raises_loudly(qapp):
    dialog = _make_dialog()

    with pytest.raises(RuntimeError, match="Unknown install snapshot status"):
        dialog.apply_install_snapshot({"status": "PAUSED", "message": "paused"})

    dialog.close()
    qapp.processEvents()


def test_request_close_rejects_running_dialog_and_accepts_success(qapp):
    dialog = _make_dialog()
    dialog.apply_install_snapshot({"status": "RUNNING", "message": "运行中", "updated_at": 1})
    dialog._install_bridge.requestClose()

    assert dialog.result() == int(dialog.DialogCode.Rejected)

    dialog = _make_dialog()
    dialog.apply_install_snapshot({"status": "DONE", "message": "安装成功", "updated_at": 2})
    dialog._install_bridge.requestClose()

    assert dialog.result() == int(dialog.DialogCode.Accepted)
