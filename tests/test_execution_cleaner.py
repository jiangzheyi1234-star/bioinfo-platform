"""测试执行清理器

验证：
- 归档执行（删除文件，保留记录）
- 标记最终版本
- 保留最近 N 次执行
- 磁盘占用统计
"""

import time
from unittest.mock import MagicMock

import pytest

from core.data.data_registry import DataRegistry
from core.data.execution_cleaner import ExecutionCleaner
from core.data.project_manager import ProjectManager
from core.remote.ssh_service import SSHService
from core.execution.tool_engine import ToolEngine


@pytest.fixture
def temp_projects_root(tmp_path):
    """临时项目根目录"""
    return tmp_path / "projects"


@pytest.fixture
def project_manager(temp_projects_root):
    """项目管理器"""
    pm = ProjectManager(projects_root=temp_projects_root)
    project_id = pm.create_project("测试项目", "清理测试")
    pm.open_project(project_id)
    return pm


@pytest.fixture
def mock_ssh():
    """Mock SSH 服务"""
    ssh = MagicMock(spec=SSHService)
    ssh.run.return_value = MagicMock(exit_code=0, stdout="", stderr="")
    return ssh


@pytest.fixture
def data_registry(project_manager):
    """数据注册表"""
    return DataRegistry(project_manager.db)


@pytest.fixture
def execution_cleaner(project_manager, mock_ssh):
    """执行清理器"""
    return ExecutionCleaner(projects=project_manager, ssh=mock_ssh)


def test_archive_execution_accepts_tuple_result_and_quotes_path(
    execution_cleaner, project_manager, data_registry, mock_ssh
):
    """archive_execution should support tuple SSH results and quote remote paths."""
    sample_id = data_registry.add_sample("quoted sample", source="local")

    db = project_manager.db
    execution_id = "exec_testquoted"
    db.execute(
        "INSERT INTO executions "
        "(execution_id, sample_id, tool_id, tool_version, parameters, "
        "status, triggered_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            execution_id,
            sample_id,
            "fastp",
            "0.23.0",
            '{}',
            "completed",
            "manual",
            time.time(),
        ),
    )
    db.commit()

    project_manager.current_project.remote_base = "/remote base/with spaces"
    mock_ssh.run.return_value = (0, "", "")

    execution_cleaner.archive_execution(execution_id)

    expected_dir = f"/remote base/with spaces/intermediate/{sample_id}/fastp_{execution_id}"
    mock_ssh.run.assert_called_with(f"rm -rf '{expected_dir}'", timeout=30)


def test_archive_execution_deletes_files_and_updates_db(
    execution_cleaner, project_manager, data_registry, mock_ssh
):
    """测试归档执行删除文件并更新数据库"""
    # 创建样本
    sample_id = data_registry.add_sample("测试样本", source="local")

    # 插入执行记录
    db = project_manager.db
    execution_id = "exec_test123456"
    db.execute(
        "INSERT INTO executions "
        "(execution_id, sample_id, tool_id, tool_version, parameters, "
        "status, triggered_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            execution_id,
            sample_id,
            "fastp",
            "0.23.0",
            '{"qualified_quality_phred": 20}',
            "completed",
            "manual",
            time.time(),
        ),
    )
    db.commit()

    # 归档执行
    execution_cleaner.archive_execution(execution_id)

    # 验证调用了 rm -rf
    project = project_manager.current_project
    expected_dir = f"{project.remote_base}/intermediate/{sample_id}/fastp_{execution_id}"
    mock_ssh.run.assert_called()
    rm_calls = [
        call for call in mock_ssh.run.call_args_list
        if "rm -rf" in str(call)
    ]
    assert len(rm_calls) > 0
    assert expected_dir in str(rm_calls[0])

    # 验证数据库更新
    row = db.execute(
        "SELECT archived_at FROM executions WHERE execution_id = ?",
        (execution_id,),
    ).fetchone()
    assert row is not None
    assert row["archived_at"] is not None


def test_archive_execution_raises_if_already_archived(
    execution_cleaner, project_manager, data_registry
):
    """测试重复归档抛出异常"""
    # 创建样本
    sample_id = data_registry.add_sample("测试样本", source="local")

    # 插入已归档的执行记录
    db = project_manager.db
    execution_id = "exec_test123456"
    db.execute(
        "INSERT INTO executions "
        "(execution_id, sample_id, tool_id, tool_version, parameters, "
        "status, triggered_by, created_at, archived_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            execution_id,
            sample_id,
            "fastp",
            "0.23.0",
            '{"qualified_quality_phred": 20}',
            "completed",
            "manual",
            time.time(),
            time.time(),  # 已归档
        ),
    )
    db.commit()

    # 尝试再次归档
    with pytest.raises(ValueError, match="执行已归档"):
        execution_cleaner.archive_execution(execution_id)


def test_mark_as_final_updates_database(
    execution_cleaner, project_manager, data_registry
):
    """测试标记最终版本更新数据库"""
    # 创建样本
    sample_id = data_registry.add_sample("测试样本", source="local")

    # 插入执行记录
    db = project_manager.db
    execution_id = "exec_test123456"
    db.execute(
        "INSERT INTO executions "
        "(execution_id, sample_id, tool_id, tool_version, parameters, "
        "status, triggered_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            execution_id,
            sample_id,
            "fastp",
            "0.23.0",
            '{"qualified_quality_phred": 20}',
            "completed",
            "manual",
            time.time(),
        ),
    )
    db.commit()

    # 标记为最终版本
    execution_cleaner.mark_as_final(execution_id)

    # 验证数据库更新
    row = db.execute(
        "SELECT is_final_version FROM executions WHERE execution_id = ?",
        (execution_id,),
    ).fetchone()
    assert row is not None
    assert row["is_final_version"] == 1

    # 取消标记
    execution_cleaner.unmark_as_final(execution_id)

    # 验证数据库更新
    row = db.execute(
        "SELECT is_final_version FROM executions WHERE execution_id = ?",
        (execution_id,),
    ).fetchone()
    assert row is not None
    assert row["is_final_version"] == 0


def test_keep_recent_n_archives_old_executions(
    execution_cleaner, project_manager, data_registry, mock_ssh
):
    """测试保留最近 N 次执行，归档旧执行"""
    # 创建样本
    sample_id = data_registry.add_sample("测试样本", source="local")

    # 插入 5 次执行记录
    db = project_manager.db
    execution_ids = []
    for i in range(5):
        execution_id = f"exec_test{i:06d}"
        execution_ids.append(execution_id)
        db.execute(
            "INSERT INTO executions "
            "(execution_id, sample_id, tool_id, tool_version, parameters, "
            "status, triggered_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                execution_id,
                sample_id,
                "fastp",
                "0.23.0",
                '{"qualified_quality_phred": 20}',
                "completed",
                "manual",
                time.time() + i,  # 递增时间戳
            ),
        )
        time.sleep(0.01)
    db.commit()

    # 保留最近 3 次
    archived = execution_cleaner.keep_recent_n(sample_id, "fastp", keep_count=3)

    # 验证归档了 2 次（最旧的两次）
    assert len(archived) == 2
    assert execution_ids[0] in archived
    assert execution_ids[1] in archived

    # 验证数据库状态
    for i in range(5):
        row = db.execute(
            "SELECT archived_at FROM executions WHERE execution_id = ?",
            (execution_ids[i],),
        ).fetchone()
        if i < 2:
            # 最旧的两次应该被归档
            assert row["archived_at"] is not None
        else:
            # 最近的三次应该未归档
            assert row["archived_at"] is None


def test_get_disk_usage_returns_statistics(
    execution_cleaner, project_manager, data_registry
):
    """测试磁盘占用统计"""
    # 创建样本
    sample_id = data_registry.add_sample("测试样本", source="local")

    # 插入多个工具的执行记录
    db = project_manager.db
    for tool_id in ["fastp", "kraken2", "metabat2"]:
        for i in range(3):
            execution_id = f"exec_{tool_id}_{i:03d}"
            archived_at = time.time() if i == 0 else None  # 第一次归档
            db.execute(
                "INSERT INTO executions "
                "(execution_id, sample_id, tool_id, tool_version, parameters, "
                "status, triggered_by, created_at, archived_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    execution_id,
                    sample_id,
                    tool_id,
                    "1.0.0",
                    "{}",
                    "completed",
                    "manual",
                    time.time(),
                    archived_at,
                ),
            )
    db.commit()

    # 查询磁盘占用
    usage = execution_cleaner.get_disk_usage(sample_id=sample_id)

    # 验证统计结果
    assert len(usage) == 3

    for stat in usage:
        assert stat.execution_count == 3
        assert stat.archived_count == 1  # 每个工具有一次归档
        assert stat.tool_id in ["fastp", "kraken2", "metabat2"]


def test_archive_execution_emits_signals(
    execution_cleaner, project_manager, data_registry, mock_ssh
):
    """测试归档执行发出信号"""
    # 创建样本
    sample_id = data_registry.add_sample("测试样本", source="local")

    # 插入执行记录
    db = project_manager.db
    execution_id = "exec_test123456"
    db.execute(
        "INSERT INTO executions "
        "(execution_id, sample_id, tool_id, tool_version, parameters, "
        "status, triggered_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            execution_id,
            sample_id,
            "fastp",
            "0.23.0",
            '{"qualified_quality_phred": 20}',
            "completed",
            "manual",
            time.time(),
        ),
    )
    db.commit()

    # 连接信号
    started_received = []
    completed_received = []

    execution_cleaner.archive_started.connect(lambda eid: started_received.append(eid))
    execution_cleaner.archive_completed.connect(lambda eid: completed_received.append(eid))

    # 归档执行
    execution_cleaner.archive_execution(execution_id)

    # 验证信号发出
    assert execution_id in started_received
    assert execution_id in completed_received
