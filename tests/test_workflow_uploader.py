"""Tests for core.execution.workflow_uploader."""
import errno
import os
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

from core.execution.workflow_uploader import get_local_workflow_dir, upload_workflow


# ── get_local_workflow_dir ────────────────────────────────


def test_returns_path_when_workflow_exists(tmp_path):
    """tool.yaml 同级有 workflow/ 目录时返回其路径。"""
    yaml_file = tmp_path / "tool.yaml"
    yaml_file.write_text("id: test_tool")
    wf_dir = tmp_path / "workflow"
    wf_dir.mkdir()
    (wf_dir / "run.sh").write_text("#!/bin/bash")

    result = get_local_workflow_dir(str(yaml_file))
    assert result == wf_dir


def test_returns_none_when_no_workflow(tmp_path):
    """tool.yaml 同级无 workflow/ 目录时返回 None。"""
    yaml_file = tmp_path / "tool.yaml"
    yaml_file.write_text("id: test_tool")

    result = get_local_workflow_dir(str(yaml_file))
    assert result is None


def test_returns_none_for_empty_path():
    """空路径返回 None。"""
    assert get_local_workflow_dir("") is None


# ── upload_workflow ───────────────────────────────────────


def test_upload_creates_dirs_and_puts_files(tmp_path):
    """验证 SFTP 调用：创建目录 + 上传文件 + chmod 可执行。"""
    # 构建本地 workflow 目录
    wf = tmp_path / "workflow"
    wf.mkdir()
    (wf / "run.sh").write_text("#!/bin/bash\necho hello")
    sub = wf / "my_code"
    sub.mkdir()
    (sub / "step1.py").write_text("print('ok')")
    (sub / "step2.sh").write_text("echo ok")

    # mock SSH + SFTP
    mock_sftp = MagicMock()
    mock_sftp.stat.side_effect = FileNotFoundError  # 所有目录不存在，需创建
    mock_ssh = MagicMock()
    mock_ssh.sftp.return_value = mock_sftp

    remote_dir = "/tmp/test_workflow"
    upload_workflow(mock_ssh, wf, remote_dir)

    # 验证 sftp.put 被调用了 3 次（run.sh, step1.py, step2.sh）
    put_calls = mock_sftp.put.call_args_list
    remote_files_uploaded = {c.args[1] for c in put_calls}
    assert f"{remote_dir}/run.sh" in remote_files_uploaded
    assert f"{remote_dir}/my_code/step1.py" in remote_files_uploaded
    assert f"{remote_dir}/my_code/step2.sh" in remote_files_uploaded

    # 验证 .sh 文件设置了可执行权限
    chmod_calls = mock_sftp.chmod.call_args_list
    chmod_files = {c.args[0] for c in chmod_calls}
    assert f"{remote_dir}/run.sh" in chmod_files
    assert f"{remote_dir}/my_code/step2.sh" in chmod_files
    # .py 文件不应设置可执行权限
    assert f"{remote_dir}/my_code/step1.py" not in chmod_files


def test_upload_binary_without_extension(tmp_path):
    """无后缀的二进制文件（如 mfeprimer）也应设置可执行权限。"""
    wf = tmp_path / "workflow"
    wf.mkdir()
    (wf / "mfeprimer").write_bytes(b"\x7fELF")  # fake binary

    mock_sftp = MagicMock()
    mock_sftp.stat.side_effect = FileNotFoundError
    mock_ssh = MagicMock()
    mock_ssh.sftp.return_value = mock_sftp

    upload_workflow(mock_ssh, wf, "/tmp/wf")

    chmod_calls = mock_sftp.chmod.call_args_list
    chmod_files = {c.args[0] for c in chmod_calls}
    assert "/tmp/wf/mfeprimer" in chmod_files


def test_upload_handles_paramiko_missing_dir_oserror(tmp_path):
    """远端目录不存在时，Paramiko 风格的 OSError(errno=2) 也应被当作缺失目录处理。"""
    wf = tmp_path / "workflow"
    wf.mkdir()
    (wf / "run.sh").write_text("#!/bin/bash\necho hello")

    missing_dir_error = OSError("No such file")
    missing_dir_error.errno = errno.ENOENT

    mock_sftp = MagicMock()
    mock_sftp.stat.side_effect = missing_dir_error
    mock_ssh = MagicMock()
    mock_ssh.sftp.return_value = mock_sftp

    upload_workflow(mock_ssh, wf, "/tmp/wf")

    assert mock_sftp.mkdir.called
    assert mock_sftp.put.called
