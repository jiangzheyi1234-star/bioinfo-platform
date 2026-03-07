"""测试工具执行的多版本支持

验证：
- 同一工具多次执行创建独立输出目录
- 输出目录包含 execution_id
- 数据注册正确关联到执行
- 历史执行查询功能
"""

import sqlite3
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.data_registry import DataRegistry
from core.plugin_registry import PluginRegistry
from core.project_manager import ProjectManager
from core.ssh_service import SSHService
from core.tool_engine import ToolEngine


@pytest.fixture
def temp_projects_root(tmp_path):
    """临时项目根目录"""
    return tmp_path / "projects"


@pytest.fixture
def project_manager(temp_projects_root):
    """项目管理器"""
    pm = ProjectManager(projects_root=temp_projects_root)
    project_id = pm.create_project("测试项目", "多版本测试")
    pm.open_project(project_id)
    return pm


@pytest.fixture
def mock_ssh():
    """Mock SSH 服务"""
    ssh = MagicMock(spec=SSHService)
    ssh.run.return_value = MagicMock(exit_code=0, stdout="", stderr="")
    return ssh


@pytest.fixture
def plugin_registry():
    """插件注册表"""
    from pathlib import Path
    plugins_dir = Path(__file__).parent.parent / "plugins"
    return PluginRegistry(plugins_dir=plugins_dir)


@pytest.fixture
def data_registry(project_manager):
    """数据注册表"""
    return DataRegistry(project_manager.db)


@pytest.fixture
def mock_job_queue():
    """Mock JobQueue"""
    queue = MagicMock()
    queue.enqueue.return_value = None
    return queue


@pytest.fixture
def tool_engine(project_manager, plugin_registry, data_registry, mock_ssh, mock_job_queue):
    """工具执行引擎"""
    return ToolEngine(
        ssh_service=mock_ssh,
        plugin_registry=plugin_registry,
        project_manager=project_manager,
        data_registry=data_registry,
        job_queue=mock_job_queue,
    )


def test_multiple_executions_create_separate_directories(
    project_manager, data_registry
):
    """测试同一工具多次执行创建独立目录"""
    # 创建样本
    sample_id = data_registry.add_sample("测试样本", source="local")

    # 模拟两次执行，直接插入数据库
    import uuid
    import time

    db = project_manager.db
    project = project_manager.current_project

    exec_id_1 = f"exec_{uuid.uuid4().hex[:12]}"
    exec_id_2 = f"exec_{uuid.uuid4().hex[:12]}"

    # 插入两次执行记录
    for exec_id, q_value in [(exec_id_1, 20), (exec_id_2, 30)]:
        db.execute(
            "INSERT INTO executions "
            "(execution_id, sample_id, tool_id, tool_version, parameters, "
            "status, triggered_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                exec_id,
                sample_id,
                "fastp",
                "0.23.0",
                f'{{"qualified_quality_phred": {q_value}}}',
                "completed",
                "manual",
                time.time(),
            ),
        )
    db.commit()

    # 验证生成了不同的 execution_id
    assert exec_id_1 != exec_id_2
    assert exec_id_1.startswith("exec_")
    assert exec_id_2.startswith("exec_")

    # 验证输出目录路径不同
    expected_dir_1 = f"{project.remote_base}/intermediate/{sample_id}/fastp_{exec_id_1}"
    expected_dir_2 = f"{project.remote_base}/intermediate/{sample_id}/fastp_{exec_id_2}"

    assert expected_dir_1 != expected_dir_2
    assert f"fastp_{exec_id_1}" in expected_dir_1
    assert f"fastp_{exec_id_2}" in expected_dir_2


def test_list_executions_returns_all_versions(
    project_manager, data_registry
):
    """测试列出同一工具的所有历史执行"""
    import uuid
    import time
    import json

    # 创建样本
    sample_id = data_registry.add_sample("测试样本", source="local")

    # 插入三次执行记录
    db = project_manager.db
    exec_ids = []
    for q_value in [20, 25, 30]:
        exec_id = f"exec_{uuid.uuid4().hex[:12]}"
        exec_ids.append(exec_id)
        db.execute(
            "INSERT INTO executions "
            "(execution_id, sample_id, tool_id, tool_version, parameters, "
            "status, triggered_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                exec_id,
                sample_id,
                "fastp",
                "0.23.0",
                f'{{"qualified_quality_phred": {q_value}}}',
                "completed",
                "manual",
                time.time() + q_value,  # 递增时间戳
            ),
        )
        time.sleep(0.01)
    db.commit()

    # 查询历史执行
    executions = data_registry.list_executions(sample_id, "fastp")

    # 验证返回了所有三次执行
    assert len(executions) == 3

    # 验证按创建时间倒序排列（最新的在前）
    returned_ids = [e["execution_id"] for e in executions]
    assert returned_ids == list(reversed(exec_ids))

    # 验证包含参数信息
    params_0 = json.loads(executions[0]["parameters"])
    assert params_0["qualified_quality_phred"] == 30  # 最新的


def test_find_by_execution_returns_specific_version_output(
    project_manager, data_registry
):
    """测试按执行 ID 查找特定版本的输出"""
    import uuid
    import time

    # 创建样本
    sample_id = data_registry.add_sample("测试样本", source="local")

    # 插入两次执行记录
    db = project_manager.db
    exec_id_1 = f"exec_{uuid.uuid4().hex[:12]}"
    exec_id_2 = f"exec_{uuid.uuid4().hex[:12]}"

    for exec_id, q_value in [(exec_id_1, 20), (exec_id_2, 30)]:
        db.execute(
            "INSERT INTO executions "
            "(execution_id, sample_id, tool_id, tool_version, parameters, "
            "status, triggered_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                exec_id,
                sample_id,
                "fastp",
                "0.23.0",
                f'{{"qualified_quality_phred": {q_value}}}',
                "completed",
                "manual",
                time.time(),
            ),
        )
    db.commit()

    # 注册两次执行的输出
    output_1 = data_registry.register_output(
        execution_id=exec_id_1,
        file_path=f"/test/fastp_{exec_id_1}/output.fastq",
        sample_id=sample_id,
        data_type="fastq",
        tier="intermediate",
    )

    output_2 = data_registry.register_output(
        execution_id=exec_id_2,
        file_path=f"/test/fastp_{exec_id_2}/output.fastq",
        sample_id=sample_id,
        data_type="fastq",
        tier="intermediate",
    )

    # 查询第一次执行的输出
    outputs_1 = data_registry.find_by_execution(exec_id_1)
    assert len(outputs_1) == 1
    assert outputs_1[0].data_id == output_1
    assert f"fastp_{exec_id_1}" in outputs_1[0].file_path

    # 查询第二次执行的输出
    outputs_2 = data_registry.find_by_execution(exec_id_2)
    assert len(outputs_2) == 1
    assert outputs_2[0].data_id == output_2
    assert f"fastp_{exec_id_2}" in outputs_2[0].file_path


def test_database_migration_adds_new_fields(temp_projects_root):
    """测试数据库迁移添加新字段"""
    # 创建旧版本数据库（不包含新字段）
    pm = ProjectManager(projects_root=temp_projects_root)
    project_id = pm.create_project("测试项目", "迁移测试")

    # 手动删除新字段（模拟旧数据库）
    db_path = temp_projects_root / project_id / "project.db"
    conn = sqlite3.connect(str(db_path))
    try:
        # 检查字段存在
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(executions)")
        columns_before = [row[1] for row in cursor.fetchall()]
        assert "is_final_version" in columns_before
        assert "archived_at" in columns_before
    finally:
        conn.close()

    # 重新打开项目（应该触发迁移）
    pm.open_project(project_id)

    # 验证字段存在
    db = pm.db
    cursor = db.cursor()
    cursor.execute("PRAGMA table_info(executions)")
    columns_after = [row[1] for row in cursor.fetchall()]

    assert "is_final_version" in columns_after
    assert "archived_at" in columns_after


def test_find_compatible_still_returns_latest_by_default(
    project_manager, data_registry
):
    """测试 find_compatible 默认仍返回最新版本"""
    import uuid
    import time

    # 创建样本
    sample_id = data_registry.add_sample("测试样本", source="local")

    # 插入两次执行记录
    db = project_manager.db
    exec_id_1 = f"exec_{uuid.uuid4().hex[:12]}"
    exec_id_2 = f"exec_{uuid.uuid4().hex[:12]}"

    db.execute(
        "INSERT INTO executions "
        "(execution_id, sample_id, tool_id, tool_version, parameters, "
        "status, triggered_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            exec_id_1,
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

    # 注册第一次执行的输出
    output_1 = data_registry.register_output(
        execution_id=exec_id_1,
        file_path=f"/test/fastp_{exec_id_1}/output.fastq",
        sample_id=sample_id,
        data_type="fastq",
        tier="intermediate",
    )

    time.sleep(0.01)

    # 第二次执行
    db.execute(
        "INSERT INTO executions "
        "(execution_id, sample_id, tool_id, tool_version, parameters, "
        "status, triggered_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            exec_id_2,
            sample_id,
            "fastp",
            "0.23.0",
            '{"qualified_quality_phred": 30}',
            "completed",
            "manual",
            time.time(),
        ),
    )
    db.commit()

    # 注册第二次执行的输出
    output_2 = data_registry.register_output(
        execution_id=exec_id_2,
        file_path=f"/test/fastp_{exec_id_2}/output.fastq",
        sample_id=sample_id,
        data_type="fastq",
        tier="intermediate",
    )

    # 查询兼容数据（应该返回最新的）
    compatible = data_registry.find_compatible(sample_id, "fastq", tier="intermediate")

    # 验证返回了两个版本，最新的在前
    assert len(compatible) == 2
    assert compatible[0].data_id == output_2  # 最新的
    assert compatible[1].data_id == output_1  # 旧的
