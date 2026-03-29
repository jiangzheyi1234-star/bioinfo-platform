from __future__ import annotations

import time

import pytest

from ui.controllers.install_task_controller import InstallTaskController


def test_summary_running_has_priority():
    ctrl = InstallTaskController()
    ctrl.ingest_event(
        {
            "task_id": "db:kraken2",
            "title": "数据库安装 · Kraken2",
            "source": "db",
            "state": "running",
            "message": "正在安装数据库",
            "progress_text": "30%",
            "speed_text": "2.1MB/s",
            "location_hint": "database",
        }
    )
    ctrl.ingest_event(
        {
            "task_id": "tool_env:fastp",
            "title": "工具环境安装 · fastp",
            "source": "tool_env",
            "state": "failed",
            "message": "command not found",
            "location_hint": "settings",
        }
    )

    summary = ctrl.summary()
    assert summary["level"] == "running"
    assert str(summary["text"]) == "安装: Kraken2 30% 2.1MB/s"


def test_summary_failed_when_no_running():
    ctrl = InstallTaskController()
    ctrl.ingest_event(
        {
            "task_id": "tool_env:kraken2",
            "title": "工具环境安装 · kraken2",
            "source": "tool_env",
            "state": "failed",
            "message": "安装失败",
            "location_hint": "settings",
        }
    )

    summary = ctrl.summary()
    assert summary["level"] == "error"
    assert str(summary["text"]) == "安装: kraken2 失败"


def test_snapshot_sorted_by_updated_at_desc():
    ctrl = InstallTaskController()
    ctrl.ingest_event(
        {
            "task_id": "a",
            "title": "任务A",
            "source": "db",
            "state": "running",
            "location_hint": "database",
        }
    )
    time.sleep(0.01)
    ctrl.ingest_event(
        {
            "task_id": "b",
            "title": "任务B",
            "source": "db",
            "state": "success",
            "location_hint": "database",
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
            "progress_text": "10%",
            "message": "下载中",
            "location_hint": "database",
        }
    )
    ctrl.ingest_event(
        {
            "task_id": "db:nt",
            "title": "数据库安装 · nt",
            "source": "db",
            "state": "success",
            "message": "完成",
            "location_hint": "database",
        }
    )

    rows = ctrl.snapshot()
    assert len(rows) == 1
    assert rows[0]["state"] == "success"
    assert rows[0]["message"] == "完成"


def test_summary_running_includes_download_speed():
    ctrl = InstallTaskController()
    ctrl.ingest_event(
        {
            "task_id": "db:nt",
            "title": "数据库安装 · nt",
            "source": "db",
            "state": "running",
            "progress_text": "35%",
            "speed_text": "2.1MB/s",
            "message": "下载中",
            "location_hint": "database",
        }
    )

    summary = ctrl.summary()
    text = str(summary["text"])
    assert summary["level"] == "running"
    assert "2.1MB/s" in text
    assert "35%" in text
    assert text == "安装: nt 35% 2.1MB/s"


def test_legacy_detail_payload_raises():
    ctrl = InstallTaskController()

    with pytest.raises(ValueError, match="Legacy install_task_event.detail"):
        ctrl.ingest_event(
            {
                "task_id": "db:legacy",
                "title": "数据库安装 · Legacy",
                "source": "db",
                "state": "running",
                "detail": "42% · 速度 1.2MB/s",
            }
        )


def test_summary_success_uses_compact_title():
    ctrl = InstallTaskController()
    ctrl.ingest_event(
        {
            "task_id": "tool_env:prodigal",
            "title": "工具环境安装 · Prodigal",
            "source": "tool_env",
            "state": "success",
            "message": "工具环境安装完成",
            "location_hint": "settings",
        }
    )

    summary = ctrl.summary()
    assert summary["level"] == "success"
    assert str(summary["text"]) == "安装: Prodigal 完成"


def test_snapshot_keeps_location_hint():
    ctrl = InstallTaskController()
    ctrl.ingest_event(
        {
            "task_id": "bootstrap:miniforge",
            "title": "运行环境初始化",
            "source": "bootstrap",
            "state": "running",
            "message": "后台初始化任务执行中",
            "location_hint": "settings",
        }
    )

    rows = ctrl.snapshot()
    assert rows[0]["location_hint"] == "settings"
