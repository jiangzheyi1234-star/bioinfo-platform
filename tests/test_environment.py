"""环境检测与安装模块测试 — 合并自 test_env_detector.py + test_env_installer.py"""

import base64
from unittest.mock import MagicMock, patch

import pytest

from core.environment.env_detector import (
    CondaStatus,
    detect,
    expected_env_path,
    infer_conda_root,
    install_miniforge,
    pin_create_env_to_conda_root,
    rewrite_install_cmd,
    _COMMON_CONDA_PATHS,
)
from core.environment.env_installer import EnvInstaller, INSTALL_BASE


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def make_ssh_fn(responses: dict):
    """创建模拟 ssh_run_fn，根据命令返回预设结果。"""
    calls = []
    def fn(cmd, timeout=15):
        calls.append(cmd)
        if cmd in responses:
            return responses[cmd]
        for key, val in responses.items():
            if cmd.startswith(key):
                return val
        return (1, "", "command not found")
    fn.calls = calls
    return fn


# ----------------------------------------------------------------------------
# detect() 检测测试
# ----------------------------------------------------------------------------

class TestDetect:
    """env_detector.detect() 检测测试 — 精简核心场景"""

    def test_which_conda_success(self):
        """bash -ic which conda 成功时返回 OK。"""
        fn = make_ssh_fn({
            "bash -ic 'which conda' 2>/dev/null": (0, "/home/user/anaconda3/bin/conda\n", ""),
            "bash -c '/home/user/anaconda3/bin/conda --version'": (0, "conda 24.3.0", ""),
            "eval echo /home/user/anaconda3/bin/conda": (0, "/home/user/anaconda3/bin/conda", ""),
        })
        result = detect(fn)
        assert result.status == CondaStatus.OK
        assert result.executable == "/home/user/anaconda3/bin/conda"

    def test_which_falls_back_to_scan(self):
        """which 失败，回退到常见目录扫描。"""
        scan_cmds = {}
        for i, path in enumerate(_COMMON_CONDA_PATHS):
            test_cmd = f'test -x "$(eval echo {path})" && eval echo {path}'
            version_path = path.replace("~/", "$HOME/", 1) if path.startswith("~") else path
            if i == 0:  # 第一个路径成功
                scan_cmds[test_cmd] = (0, path, "")
                scan_cmds[f"bash -c '{version_path} --version'"] = (0, "conda 22.9.0", "")
                scan_cmds[f"eval echo {version_path}"] = (0, "/home/user/anaconda3/bin/conda", "")
            else:
                scan_cmds[test_cmd] = (1, "", "")

        fn = make_ssh_fn({
            "bash -ic 'which conda' 2>/dev/null": (1, "", ""),
            **scan_cmds
        })
        result = detect(fn)
        assert result.status == CondaStatus.OK
        assert "/anaconda3/bin/conda" in result.executable

    def test_all_not_found(self):
        """全部未命中 → NOT_FOUND。"""
        fn = make_ssh_fn({})
        result = detect(fn)
        assert result.status == CondaStatus.NOT_FOUND
        assert result.executable is None


# ----------------------------------------------------------------------------
# install_miniforge() 测试
# ----------------------------------------------------------------------------

class TestInstallMiniforge:
    """Miniforge 安装测试"""

    def test_install_success(self):
        """Miniforge 安装成功流程。"""
        fn = make_ssh_fn({
            "uname -m": (0, "x86_64", ""),
            "command -v curl": (0, "/usr/bin/curl", ""),
            "curl -fsSL -o /tmp/miniforge_install.sh": (0, "", ""),
            "bash /tmp/miniforge_install.sh -b": (0, "", ""),
            "rm -f /tmp/miniforge_install.sh": (0, "", ""),
            "bash -c '~/miniforge3/bin/conda config --add channels bioconda'": (0, "", ""),
            "bash -c '~/miniforge3/bin/conda config --set channel_priority strict'": (0, "", ""),
            "bash -c '$HOME/miniforge3/bin/conda --version'": (0, "conda 24.7.1", ""),
            "eval echo $HOME/miniforge3/bin/conda": (0, "/home/user/miniforge3/bin/conda", ""),
        })
        result = install_miniforge(fn)
        assert result.status == CondaStatus.OK

    def test_install_fails_on_unsupported_arch(self):
        """不支持的架构应失败。"""
        fn = make_ssh_fn({"uname -m": (0, "armv7l", "")})
        result = install_miniforge(fn)
        assert result.status == CondaStatus.NOT_FOUND
        assert "不支持的架构" in result.message


# ----------------------------------------------------------------------------
# rewrite_install_cmd() 测试
# ----------------------------------------------------------------------------

class TestRewriteInstallCmd:
    """命令替换测试"""

    def test_basic_rewrite(self):
        result = rewrite_install_cmd(
            "conda create -n fastp_env -c bioconda fastp -y",
            "/home/user/miniconda3/bin/conda")
        assert "/home/user/miniconda3/bin/conda create" in result

    def test_non_conda_cmd_unchanged(self):
        result = rewrite_install_cmd("pip install fastp", "/home/user/conda/bin/conda")
        assert result == "pip install fastp"


# ----------------------------------------------------------------------------
# Conda Root Helpers 测试
# ----------------------------------------------------------------------------

class TestCondaRootHelpers:
    """conda 路径辅助函数测试"""

    def test_infer_conda_root(self):
        assert infer_conda_root("/home/user/anaconda3/bin/conda") == "/home/user/anaconda3"
        assert infer_conda_root("") == ""

    def test_expected_env_path(self):
        assert expected_env_path("/opt/miniconda3/bin/conda", "fastp_env") == "/opt/miniconda3/envs/fastp_env"

    def test_pin_create_env_to_conda_root(self):
        cmd = "/opt/conda/bin/conda create -n fastp_env -c bioconda fastp -y"
        pinned = pin_create_env_to_conda_root(cmd, "/opt/conda/bin/conda")
        assert " -p /opt/conda/envs/fastp_env " in f" {pinned} "


# ----------------------------------------------------------------------------
# EnvInstaller 测试
# ----------------------------------------------------------------------------

class TestEnvInstallerSubmit:
    """EnvInstaller.submit() 测试"""

    def test_submit_basic(self):
        """基本提交流程。"""
        fn = make_ssh_fn({
            "mkdir -p": (0, "", ""),
            "echo '": (0, "", ""),
            "screen -S h2o_install_fastp -X quit": (0, "", ""),
            "screen -dmS": (0, "", ""),
        })
        result = EnvInstaller.submit(
            fn, "fastp",
            "conda create -n fastp_env -c bioconda fastp -y",
            "/home/user/conda/bin/conda")
        assert result["job_id"] == "h2o_install_fastp"
        assert result["task_dir"] == f"{INSTALL_BASE}/fastp"

    def test_submit_rewrites_conda_path(self):
        """提交时替换 conda 路径。"""
        written_script = []
        def capture_fn(cmd, timeout=15):
            if cmd.startswith("echo '"):
                parts = cmd.split("'")
                if len(parts) >= 2:
                    try:
                        decoded = base64.b64decode(parts[1]).decode()
                        written_script.append(decoded)
                    except Exception:
                        pass
            return (0, "", "")

        EnvInstaller.submit(capture_fn, "fastp", "conda create -n fastp_env -y", "/opt/conda/bin/conda")
        assert len(written_script) == 1
        assert "/opt/conda/bin/conda create" in written_script[0]

