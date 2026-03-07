"""测试 ExecutionRecord 的新字段处理

验证：
- _row_to_record 正确读取 is_final_version 和 archived_at
- 向后兼容旧数据库（字段不存在时使用默认值）
"""

import sqlite3
import time
from pathlib import Path

import pytest

from core.project_manager import ProjectManager
from core.tool_engine import ToolEngine


@pytest.fixture
def temp_projects_root(tmp_path):
    """临时项目根目录"""
    return tmp_path / "projects"


@pytest.fixture
def project_manager(temp_projects_root):
    """项目管理器"""
    pm = ProjectManager(projects_root=temp_projects_root)
    project_id = pm.create_project("测试项目", "字段测试")
    pm.open_project(project_id)
    return pm


def test_row_to_record_reads_new_fields(project_manager):
    """测试 _row_to_record 正确读取新字段"""
    db = project_manager.db

    # 先创建样本
    db.execute(
        "INSERT INTO samples (sample_id, name) VALUES (?, ?)",
        ("smp_test", "测试样本"),
    )
    db.commit()

    # 插入包含新字段的执行记录
    execution_id = "exec_test123456"
    db.execute(
        "INSERT INTO executions "
        "(execution_id, sample_id, tool_id, tool_version, parameters, "
        "status, triggered_by, created_at, is_final_version, archived_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            execution_id,
            "smp_test",
            "fastp",
            "0.23.0",
            '{"qualified_quality_phred": 20}',
            "completed",
            "manual",
            time.time(),
            1,  # is_final_version
            time.time(),  # archived_at
        ),
    )
    db.commit()

    # 读取记录
    row = db.execute(
        "SELECT * FROM executions WHERE execution_id = ?",
        (execution_id,),
    ).fetchone()

    # 使用 _row_to_record 转换
    record = ToolEngine._row_to_record(row)

    # 验证新字段被正确读取
    assert record.is_final_version == 1
    assert record.archived_at is not None
    assert isinstance(record.archived_at, float)


def test_row_to_record_handles_missing_fields(project_manager):
    """测试 _row_to_record 处理缺失字段（向后兼容）"""
    db = project_manager.db

    # 先创建样本
    db.execute(
        "INSERT INTO samples (sample_id, name) VALUES (?, ?)",
        ("smp_test2", "测试样本2"),
    )
    db.commit()

    # 插入不包含新字段的执行记录（模拟旧数据库）
    execution_id = "exec_test789012"
    db.execute(
        "INSERT INTO executions "
        "(execution_id, sample_id, tool_id, tool_version, parameters, "
        "status, triggered_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            execution_id,
            "smp_test2",
            "fastp",
            "0.23.0",
            '{"qualified_quality_phred": 20}',
            "completed",
            "manual",
            time.time(),
        ),
    )
    db.commit()

    # 读取记录
    row = db.execute(
        "SELECT * FROM executions WHERE execution_id = ?",
        (execution_id,),
    ).fetchone()

    # 使用 _row_to_record 转换
    record = ToolEngine._row_to_record(row)

    # 验证新字段使用默认值
    assert record.is_final_version == 0  # 默认值
    assert record.archived_at is None  # 默认值


def test_row_to_record_preserves_all_fields(project_manager):
    """测试 _row_to_record 保留所有字段"""
    db = project_manager.db

    # 先创建样本
    db.execute(
        "INSERT INTO samples (sample_id, name) VALUES (?, ?)",
        ("smp_test3", "测试样本3"),
    )
    db.commit()

    # 插入完整的执行记录
    execution_id = "exec_complete"
    created_at = time.time()
    completed_at = time.time() + 100
    archived_at = time.time() + 200

    db.execute(
        "INSERT INTO executions "
        "(execution_id, sample_id, tool_id, tool_version, parameters, "
        "status, triggered_by, created_at, completed_at, error, "
        "retry_count, retry_of, remote_job_id, is_final_version, archived_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            execution_id,
            "smp_test3",
            "fastp",
            "0.23.0",
            '{"qualified_quality_phred": 20}',
            "completed",
            "manual",
            created_at,
            completed_at,
            "test error",
            2,
            None,  # retry_of 设为 NULL 避免外键约束
            "screen_12345",
            1,
            archived_at,
        ),
    )
    db.commit()

    # 读取记录
    row = db.execute(
        "SELECT * FROM executions WHERE execution_id = ?",
        (execution_id,),
    ).fetchone()

    # 使用 _row_to_record 转换
    record = ToolEngine._row_to_record(row)

    # 验证所有字段
    assert record.execution_id == execution_id
    assert record.sample_id == "smp_test3"
    assert record.tool_id == "fastp"
    assert record.tool_version == "0.23.0"
    assert record.parameters == {"qualified_quality_phred": 20}
    assert record.status == "completed"
    assert record.triggered_by == "manual"
    assert record.created_at == created_at
    assert record.completed_at == completed_at
    assert record.error == "test error"
    assert record.retry_count == 2
    assert record.retry_of is None  # 修改为 None
    assert record.remote_job_id == "screen_12345"
    assert record.is_final_version == 1
    assert record.archived_at == archived_at
