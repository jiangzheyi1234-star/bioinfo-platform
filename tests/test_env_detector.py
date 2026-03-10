"""env_detector 模块测试。"""

import pytest
from core import env_detector
from core.env_detector import (
    CondaStatus,
    CondaDetectResult,
    detect,
    install_miniforge,
    rewrite_install_cmd,
    _COMMON_CONDA_PATHS,
)

# ---------------------------------------------------------------------------
# Mock SSH 运行函数
# ---------------------------------------------------------------------------


def make_ssh_fn(responses: dict):
    """创建一个 mock SSH 运行函数，根据命令返回预定义的响应。"""

    def ssh_run_fn(cmd: str, timeout: int = 15):
        if cmd in responses:
            rc, stdout, stderr = responses[cmd]
            return (rc, stdout, stderr)
        # 默认失败
        return (1, "", "command not found")

    return ssh_run_fn


# ---------------------------------------------------------------------------
# detect() 测试
# ---------------------------------------------------------------------------


class TestDetect:
    """env_detector.detect() 检测测试。"""

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

    def test_which_fails_scan_hits_anaconda3(self):
        """which 失败，常见目录扫描优先命中 ~/anaconda3。"""
        # 构建所有 4 个路径的扫描命令（注意：~会被替换为$HOME）
        scan_cmds = {}
        for i, path in enumerate(_COMMON_CONDA_PATHS):
            test_cmd = f'test -x "$(eval echo {path})" && eval echo {path}'
            # ~ 替换为 $HOME 用于验证命令
            version_path = path.replace("~/", "$HOME/", 1) if path.startswith("~") else path
            if i == 0:  # 第一个路径（~/anaconda3）成功
                scan_cmds[test_cmd] = (0, path, "")
                scan_cmds[f"bash -c '{version_path} --version'"] = (0, "conda 22.9.0", "")
                scan_cmds[f"eval echo {version_path}"] = (0, "/home/user/anaconda3/bin/conda", "")
            else:  # 其他路径失败
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
        fn = make_ssh_fn({})  # 全部返回默认失败
        result = detect(fn)
        assert result.status == CondaStatus.NOT_FOUND
        assert result.executable is None

    def test_version_from_stderr(self):
        """conda 可能将版本输出到 stderr。"""
        fn = make_ssh_fn({
            "bash -ic 'which conda' 2>/dev/null": (0, "/custom/bin/conda\n", ""),
            "bash -c '/custom/bin/conda --version'": (0, "", "conda 24.7.1"),
            "eval echo /custom/bin/conda": (0, "/custom/bin/conda", ""),
        })
        result = detect(fn)
        assert result.status == CondaStatus.OK
        assert result.version == "24.7.1"

    def test_version_unparseable_still_ok(self):
        """rc==0 但版本格式异常 → 仍然 OK，version=None。"""
        fn = make_ssh_fn({
            "bash -ic 'which conda' 2>/dev/null": (0, "/usr/bin/conda\n", ""),
            "bash -c '/usr/bin/conda --version'": (0, "some weird output", ""),
            "eval echo /usr/bin/conda": (0, "/usr/bin/conda", ""),
        })
        result = detect(fn)
        assert result.status == CondaStatus.OK
        assert result.executable == "/usr/bin/conda"
        assert result.version is None


# ---------------------------------------------------------------------------
# install_miniforge() 测试
# ---------------------------------------------------------------------------


class TestInstallMiniforge:
    """install_miniforge() 安装测试。"""

    def test_install_success(self):
        """Miniforge 安装成功流程。"""
        fn = make_ssh_fn({
            "uname -m": (0, "x86_64", ""),
            "command -v curl": (0, "/usr/bin/curl", ""),
            "curl -fsSL -o /tmp/miniforge_install.sh https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh": (0, "", ""),
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
        fn = make_ssh_fn({
            "uname -m": (0, "armv7l", ""),
        })
        result = install_miniforge(fn)
        assert result.status == CondaStatus.NOT_FOUND
        assert "不支持的架构" in result.message

    def test_install_fails_no_download_tool(self):
        """没有 curl 或 wget 应失败。"""
        fn = make_ssh_fn({
            "uname -m": (0, "x86_64", ""),
            "command -v curl": (1, "", ""),
            "command -v wget": (1, "", ""),
        })
        result = install_miniforge(fn)
        assert result.status == CondaStatus.NOT_FOUND
        assert "需要 curl 或 wget" in result.message


# ---------------------------------------------------------------------------
# rewrite_install_cmd() 测试
# ---------------------------------------------------------------------------


class TestRewriteInstallCmd:
    """rewrite_install_cmd() 命令替换测试。"""

    def test_basic_rewrite(self):
        """基本替换测试。"""
        result = rewrite_install_cmd(
            "conda create -n fastp_env -c bioconda fastp -y",
            "/home/user/miniconda3/bin/conda",
        )
        assert result == "/home/user/miniconda3/bin/conda create -n fastp_env -c bioconda fastp -y"

    def test_preserves_leading_whitespace(self):
        """保留前导空白。"""
        result = rewrite_install_cmd(
            "  conda create -n test",
            "/opt/conda/bin/conda",
        )
        assert result == "  /opt/conda/bin/conda create -n test"

    def test_non_conda_cmd_unchanged(self):
        """非 conda 命令不变。"""
        result = rewrite_install_cmd(
            "pip install fastp",
            "/home/user/conda/bin/conda",
        )
        assert result == "pip install fastp"

    def test_empty_executable_no_change(self):
        """空 executable 不替换。"""
        result = rewrite_install_cmd(
            "conda create -n test",
            "",
        )
        assert result == "conda create -n test"

    def test_bare_conda_word(self):
        """单独的 conda 单词也替换。"""
        result = rewrite_install_cmd(
            "conda",
            "/usr/local/conda/bin/conda",
        )
        assert result == "/usr/local/conda/bin/conda"
