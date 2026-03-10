"""env_detector 单元测试 — 覆盖 conda 检测、Miniforge 安装、命令重写等场景。"""

import pytest

from core.env_detector import (
    CondaDetectResult,
    CondaStatus,
    can_install,
    detect,
    enable_libmamba,
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

    def test_configured_path_ok(self):
        """configured_path 有效且 which 不可用时，回退到 configured_path。"""
        fn = make_ssh_fn({
            "/custom/bin/conda --version": (0, "conda 24.1.2", ""),
        })
        result = detect(fn, configured_path="/custom/bin/conda")
        assert result.status == CondaStatus.OK
        assert result.executable == "/custom/bin/conda"
        assert result.version == "24.1.2"

    def test_configured_path_valid_but_which_takes_precedence(self):
        """configured_path 有效，但当前用户 which conda 优先。"""
        fn = make_ssh_fn({
            "/custom/bin/conda --version": (0, "conda 24.1.2", ""),
            "bash -l -c 'which conda'": (0, "/opt/conda/bin/conda\n", ""),
            "/opt/conda/bin/conda --version": (0, "conda 24.3.1", ""),
        })
        result = detect(fn, configured_path="/custom/bin/conda")
        assert result.status == CondaStatus.OK
        assert result.executable == "/opt/conda/bin/conda"
        assert result.version == "24.3.1"

    def test_configured_path_invalid_falls_through_to_which(self):
        """configured_path 无效时 fallback 到 which conda。"""
        fn = make_ssh_fn({
            "/bad/path/conda --version": (1, "", "not found"),
            "bash -l -c 'which conda'": (0, "/usr/bin/conda\n", ""),
            "/usr/bin/conda --version": (0, "conda 23.5.0", ""),
        })
        result = detect(fn, configured_path="/bad/path/conda")
        assert result.status == CondaStatus.OK
        assert result.executable == "/usr/bin/conda"
        assert result.version == "23.5.0"

    def test_which_conda_success(self):
        """which conda 成功时返回 OK。"""
        fn = make_ssh_fn({
            "bash -l -c 'which conda'": (0, "/home/user/miniconda3/bin/conda\n", ""),
            "/home/user/miniconda3/bin/conda --version": (0, "conda 24.3.0", ""),
        })
        result = detect(fn)
        assert result.status == CondaStatus.OK
        assert result.executable == "/home/user/miniconda3/bin/conda"

    def test_which_fails_scan_hits_anaconda3(self):
        """which 失败，常见目录扫描优先命中 ~/anaconda3。"""
        fn = make_ssh_fn({
            "bash -l -c 'which conda'": (1, "", ""),
            "bash -i -c 'which conda'": (1, "", ""),
            "which conda": (1, "", ""),
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

    def test_version_parse_failed(self):
        """conda --version 输出格式异常 → VERSION_PARSE_FAILED。"""
        fn = make_ssh_fn({
            "bash -l -c 'which conda'": (0, "/usr/bin/conda\n", ""),
            "/usr/bin/conda --version": (0, "some weird output", ""),
            # 扫描也匹配到同一个
            'test -x "$(eval echo ~/.h2ometa/conda/bin/conda)"': (1, "", ""),
            'test -x "$(eval echo ~/miniforge3/bin/conda)"': (1, "", ""),
            'test -x "$(eval echo ~/miniconda3/bin/conda)"': (1, "", ""),
            'test -x "$(eval echo ~/anaconda3/bin/conda)"': (1, "", ""),
            'test -x "$(eval echo /opt/miniforge3/bin/conda)"': (1, "", ""),
            'test -x "$(eval echo /opt/conda/bin/conda)"': (1, "", ""),
        })
        result = detect(fn)
        assert result.status == CondaStatus.VERSION_PARSE_FAILED

    def test_empty_configured_path_ignored(self):
        """空 configured_path 应被忽略。"""
        fn = make_ssh_fn({
            "bash -l -c 'which conda'": (0, "/usr/bin/conda\n", ""),
            "/usr/bin/conda --version": (0, "conda 24.0.0", ""),
        })
        result = detect(fn, configured_path="")
        assert result.status == CondaStatus.OK

    def test_version_from_stderr(self):
        """conda 可能将版本输出到 stderr。"""
        fn = make_ssh_fn({
            "/custom/conda --version": (0, "", "conda 24.7.1"),
        })
        result = detect(fn, configured_path="/custom/conda")
        assert result.status == CondaStatus.OK
        assert result.version == "24.7.1"

    def test_bash_interactive_fallback(self):
        """bash -l 失败但 bash -i 成功（conda init 在 .bashrc）。"""
        fn = make_ssh_fn({
            "bash -l -c 'which conda'": (1, "", ""),
            "bash -i -c 'which conda'": (0, "/home/user/anaconda3/bin/conda\n", ""),
            "/home/user/anaconda3/bin/conda --version": (0, "conda 23.11.0", ""),
        })
        result = detect(fn)
        assert result.status == CondaStatus.OK
        assert result.executable == "/home/user/anaconda3/bin/conda"
        assert result.version == "23.11.0"

    def test_plain_which_fallback(self):
        """bash -l 和 bash -i 都失败，plain which conda 成功。"""
        fn = make_ssh_fn({
            "bash -l -c 'which conda'": (1, "", ""),
            "bash -i -c 'which conda'": (1, "", ""),
            "which conda": (0, "/opt/conda/bin/conda\n", ""),
            "/opt/conda/bin/conda --version": (0, "conda 24.5.0", ""),
        })
        result = detect(fn)
        assert result.status == CondaStatus.OK
        assert result.executable == "/opt/conda/bin/conda"


# ---------------------------------------------------------------------------
# can_install() 测试
# ---------------------------------------------------------------------------

class TestCanInstall:
    """can_install() 前置检查测试。"""

    def test_ok(self):
        fn = make_ssh_fn({
            "uname -m": (0, "x86_64", ""),
            "command -v curl": (0, "/usr/bin/curl", ""),
            "command -v wget": (0, "/usr/bin/wget", ""),
            "dir=": (0, "ok", ""),  # 前缀匹配 can_install 的目录检查命令
        })
        ok, _ = can_install(fn)
        assert ok

    def test_unsupported_arch(self):
        fn = make_ssh_fn({
            "uname -m": (0, "armv7l", ""),
        })
        ok, reason = can_install(fn)
        assert not ok
        assert "架构" in reason

    def test_no_download_tool(self):
        fn = make_ssh_fn({
            "uname -m": (0, "x86_64", ""),
            "command -v curl": (1, "", ""),
            "command -v wget": (1, "", ""),
        })
        ok, reason = can_install(fn)
        assert not ok
        assert "curl" in reason or "wget" in reason

    def test_dir_exists(self):
        fn = make_ssh_fn({
            "uname -m": (0, "x86_64", ""),
            "command -v curl": (0, "/usr/bin/curl", ""),
            "command -v wget": (1, "", ""),
            "dir=": (0, "exists", ""),  # 前缀匹配
        })
        ok, reason = can_install(fn)
        assert not ok
        assert "已存在" in reason


# ---------------------------------------------------------------------------
# install_miniforge() 测试
# ---------------------------------------------------------------------------

class TestInstallMiniforge:

    def test_install_success(self):
        fn = make_ssh_fn({
            # can_install checks
            "uname -m": (0, "x86_64", ""),
            "command -v curl": (0, "/usr/bin/curl", ""),
            "command -v wget": (1, "", ""),
            "dir=": (0, "ok", ""),  # 前缀匹配目录检查
            # download
            "curl -fsSL": (0, "", ""),
            # install
            "bash /tmp/miniforge_install.sh": (0, "", ""),
            # cleanup
            "rm -f /tmp/miniforge_install.sh": (0, "", ""),
            # channel config
            "~/.h2ometa/conda/bin/conda config --add channels bioconda": (0, "", ""),
            "~/.h2ometa/conda/bin/conda config --set channel_priority strict": (0, "", ""),
            # validate
            "~/.h2ometa/conda/bin/conda --version": (0, "conda 24.7.1", ""),
        })
        result = install_miniforge(fn)
        assert result.status == CondaStatus.OK
        assert result.version == "24.7.1"

    def test_install_fails_on_precondition(self):
        fn = make_ssh_fn({
            "uname -m": (0, "armv7l", ""),
        })
        result = install_miniforge(fn)
        assert result.status == CondaStatus.NOT_FOUND
        assert "架构" in result.message or "无法安装" in result.message


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


# ---------------------------------------------------------------------------
# enable_libmamba() 测试
# ---------------------------------------------------------------------------

class TestEnableLibmamba:

    def test_success(self):
        fn = make_ssh_fn({
            "/usr/bin/conda config --set solver libmamba": (0, "", ""),
        })
        assert enable_libmamba(fn, "/usr/bin/conda") is True

    def test_failure(self):
        fn = make_ssh_fn({
            "/usr/bin/conda config --set solver libmamba": (1, "", "error"),
        })
        assert enable_libmamba(fn, "/usr/bin/conda") is False
