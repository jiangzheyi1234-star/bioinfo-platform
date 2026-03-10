"""env_detector 单元测试 — 覆盖 conda 检测、Miniforge 安装、命令重写等场景。"""

import pytest

from core.env_detector import (
    CondaDetectResult,
    CondaStatus,
    detect,
    install_miniforge,
    rewrite_install_cmd,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_ssh_fn(responses: dict[str, tuple[int, str, str]]):
    """创建模拟 ssh_run_fn，根据命令前缀匹配返回预设结果。"""
    def fn(cmd, timeout=15):
        # 精确匹配优先
        if cmd in responses:
            return responses[cmd]
        # 前缀匹配
        for key, val in responses.items():
            if cmd.startswith(key):
                return val
        # 默认失败
        return (1, "", "command not found")
    return fn


# ---------------------------------------------------------------------------
# detect() 测试
# ---------------------------------------------------------------------------

class TestDetect:
    """env_detector.detect() 检测测试。"""

    def test_cached_path_verified_first(self):
        """cached_path 有效时直接返回，不执行 which。"""
        fn = make_ssh_fn({
            "/custom/bin/conda --version": (0, "conda 24.1.2", ""),
        })
        result = detect(fn, cached_path="/custom/bin/conda")
        assert result.status == CondaStatus.OK
        assert result.executable == "/custom/bin/conda"
        assert result.version == "24.1.2"

    def test_cached_path_invalid_falls_through_to_which(self):
        """cached_path 无效时 fallback 到 which conda。"""
        fn = make_ssh_fn({
            "/bad/path/conda --version": (1, "", "not found"),
            "bash -ic 'which conda'": (0, "/usr/bin/conda\n", ""),
            "/usr/bin/conda --version": (0, "conda 23.5.0", ""),
        })
        result = detect(fn, cached_path="/bad/path/conda")
        assert result.status == CondaStatus.OK
        assert result.executable == "/usr/bin/conda"
        assert result.version == "23.5.0"

    def test_which_conda_success(self):
        """bash -ic which conda 成功时返回 OK。"""
        fn = make_ssh_fn({
            "bash -ic 'which conda'": (0, "/home/user/anaconda3/bin/conda\n", ""),
            "/home/user/anaconda3/bin/conda --version": (0, "conda 24.3.0", ""),
        })
        result = detect(fn)
        assert result.status == CondaStatus.OK
        assert result.executable == "/home/user/anaconda3/bin/conda"

    def test_which_fails_scan_hits_anaconda3(self):
        """which 失败，常见目录扫描优先命中 ~/anaconda3。"""
        fn = make_ssh_fn({
            "bash -ic 'which conda'": (1, "", ""),
            'test -x "$(eval echo ~/anaconda3/bin/conda)"': (0, "", ""),
            "~/anaconda3/bin/conda --version": (0, "conda 22.9.0", ""),
        })
        result = detect(fn)
        assert result.status == CondaStatus.OK
        assert result.executable == "~/anaconda3/bin/conda"

    def test_all_not_found(self):
        """全部未命中 → NOT_FOUND。"""
        fn = make_ssh_fn({})  # 全部返回默认失败
        result = detect(fn)
        assert result.status == CondaStatus.NOT_FOUND
        assert result.executable is None

    def test_empty_cached_path_ignored(self):
        """空 cached_path 应被忽略。"""
        fn = make_ssh_fn({
            "bash -ic 'which conda'": (0, "/usr/bin/conda\n", ""),
            "/usr/bin/conda --version": (0, "conda 24.0.0", ""),
        })
        result = detect(fn, cached_path="")
        assert result.status == CondaStatus.OK

    def test_version_from_stderr(self):
        """conda 可能将版本输出到 stderr。"""
        fn = make_ssh_fn({
            "/custom/conda --version": (0, "", "conda 24.7.1"),
        })
        result = detect(fn, cached_path="/custom/conda")
        assert result.status == CondaStatus.OK
        assert result.version == "24.7.1"

    def test_version_unparseable_still_ok(self):
        """rc==0 但版本格式异常 → 仍然 OK，version=None。"""
        fn = make_ssh_fn({
            "bash -ic 'which conda'": (0, "/usr/bin/conda\n", ""),
            "/usr/bin/conda --version": (0, "some weird output", ""),
        })
        result = detect(fn)
        assert result.status == CondaStatus.OK
        assert result.executable == "/usr/bin/conda"
        assert result.version is None


# ---------------------------------------------------------------------------
# install_miniforge() 测试
# ---------------------------------------------------------------------------

class TestInstallMiniforge:

    def test_install_success(self):
        fn = make_ssh_fn({
            # pre-checks
            "uname -m": (0, "x86_64", ""),
            "command -v curl": (0, "/usr/bin/curl", ""),
            "command -v wget": (1, "", ""),
            # download
            "curl -fsSL": (0, "", ""),
            # install
            "bash /tmp/miniforge_install.sh": (0, "", ""),
            # cleanup
            "rm -f /tmp/miniforge_install.sh": (0, "", ""),
            # channel config
            "~/miniforge3/bin/conda config --add channels bioconda": (0, "", ""),
            "~/miniforge3/bin/conda config --set channel_priority strict": (0, "", ""),
            # validate
            "~/miniforge3/bin/conda --version": (0, "conda 24.7.1", ""),
        })
        result = install_miniforge(fn)
        assert result.status == CondaStatus.OK
        assert result.version == "24.7.1"

    def test_install_fails_on_unsupported_arch(self):
        fn = make_ssh_fn({
            "uname -m": (0, "armv7l", ""),
        })
        result = install_miniforge(fn)
        assert result.status == CondaStatus.NOT_FOUND
        assert "架构" in result.message

    def test_install_fails_no_download_tool(self):
        fn = make_ssh_fn({
            "uname -m": (0, "x86_64", ""),
            "command -v curl": (1, "", ""),
            "command -v wget": (1, "", ""),
        })
        result = install_miniforge(fn)
        assert result.status == CondaStatus.NOT_FOUND
        assert "curl" in result.message or "wget" in result.message


# ---------------------------------------------------------------------------
# rewrite_install_cmd() 测试
# ---------------------------------------------------------------------------

class TestRewriteInstallCmd:
    """rewrite_install_cmd() 命令重写测试。"""

    def test_basic_rewrite(self):
        result = rewrite_install_cmd(
            "conda create -n fastp_env -c bioconda fastp -y",
            "/home/user/miniconda3/bin/conda",
        )
        assert result == "/home/user/miniconda3/bin/conda create -n fastp_env -c bioconda fastp -y"

    def test_preserves_leading_whitespace(self):
        result = rewrite_install_cmd(
            "  conda create -n env -y",
            "/opt/conda/bin/conda",
        )
        assert result == "  /opt/conda/bin/conda create -n env -y"

    def test_non_conda_cmd_unchanged(self):
        result = rewrite_install_cmd(
            "pip install fastp",
            "/opt/conda/bin/conda",
        )
        assert result == "pip install fastp"

    def test_empty_executable_no_change(self):
        result = rewrite_install_cmd(
            "conda create -n env -y",
            "",
        )
        assert result == "conda create -n env -y"

    def test_bare_conda_word(self):
        result = rewrite_install_cmd("conda", "/usr/bin/conda")
        assert result == "/usr/bin/conda"
