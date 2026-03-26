from __future__ import annotations

import time

from ui.controllers.install_task_controller import InstallTaskController


def test_summary_running_has_priority():
    ctrl = InstallTaskController()
    ctrl.ingest_event(
        {
            "task_id": "db:kraken2",
            "title": "数据库安装 · Kraken2",
            "source": "db",
            "state": "running",
            "detail": "30%",
        }
    )
    ctrl.ingest_event(
        {
            "task_id": "tool_env:fastp",
            "title": "工具环境安装 · fastp",
            "source": "tool_env",
            "state": "failed",
            "detail": "command not found",
        }
    )

    summary = ctrl.summary()
    assert summary["level"] == "running"
    assert "正在安装" in str(summary["text"])


def test_summary_failed_when_no_running():
    ctrl = InstallTaskController()
    ctrl.ingest_event(
        {
            "task_id": "tool_env:kraken2",
            "title": "工具环境安装 · kraken2",
            "source": "tool_env",
            "state": "failed",
            "detail": "安装失败",
        }
    )

    summary = ctrl.summary()
    assert summary["level"] == "error"
    assert "失败" in str(summary["text"])


def test_snapshot_sorted_by_updated_at_desc():
    ctrl = InstallTaskController()
    ctrl.ingest_event(
        {
            "task_id": "a",
            "title": "任务A",
            "source": "db",
            "state": "running",
            "detail": "",
        }
    )
    time.sleep(0.01)
    ctrl.ingest_event(
        {
            "task_id": "b",
            "title": "任务B",
            "source": "db",
            "state": "success",
            "detail": "",
        }
    )

    rows = ctrl.snapshot()
    assert rows[0]["task_id"] == "b"
    assert rows[1]["task_id"] == "a"


def test_ingest_event_is_idempotent_for_same_task():
    ctrl = InstallTaskController()
    ctrl.ingest_event(
        {
            "task_id": "db:nt",
            "title": "数据库安装 · nt",
            "source": "db",
            "state": "running",
            "detail": "10%",
        }
    )
    ctrl.ingest_event(
        {
            "task_id": "db:nt",
            "title": "数据库安装 · nt",
            "source": "db",
            "state": "success",
            "detail": "完成",
        }
    )

    rows = ctrl.snapshot()
    assert len(rows) == 1
    assert rows[0]["state"] == "success"


def test_summary_running_includes_download_speed():
    ctrl = InstallTaskController()
    ctrl.ingest_event(
        {
            "task_id": "db:nt",
            "title": "数据库安装 · nt",
            "source": "db",
            "state": "running",
            "detail": "35% · 速度 2.1MB/s · 预计 00:10",
        }
    )

    summary = ctrl.summary()
    text = str(summary["text"])
    assert summary["level"] == "running"
    assert "2.1MB/s" in text
    assert "35%" in text
