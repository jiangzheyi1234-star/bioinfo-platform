"""env_installer 单元测试 — 覆盖 screen 后台安装的 submit/check_status/read_log 等场景。"""

import base64
import pytest

from core.env_installer import EnvInstaller, _sanitize_log, INSTALL_BASE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_ssh_fn(responses: dict[str, tuple[int, str, str]]):
    """创建模拟 ssh_run_fn，根据命令前缀匹配返回预设结果。"""
    calls = []

    def fn(cmd, timeout=15):
        calls.append(cmd)
        # 精确匹配优先
        if cmd in responses:
            return responses[cmd]
        # 前缀匹配
        for key, val in responses.items():
            if cmd.startswith(key):
                return val
        # 默认成功
        return (0, "", "")

    fn.calls = calls
    return fn


# ---------------------------------------------------------------------------
# submit() 测试
# ---------------------------------------------------------------------------

class TestSubmit:
    """EnvInstaller.submit() 测试。"""

    def test_submit_basic(self):
        """基本提交流程：mkdir → 写脚本 → screen 启动。"""
        fn = make_ssh_fn({
            "mkdir -p": (0, "", ""),
            "echo '": (0, "", ""),   # base64 write
            "screen -S h2o_install_fastp -X quit": (0, "", ""),
            "screen -dmS": (0, "", ""),
        })
        result = EnvInstaller.submit(
            fn, "fastp",
            "conda create -n fastp_env -c bioconda fastp -y",
            "/home/user/conda/bin/conda",
        )
        assert result["job_id"] == "h2o_install_fastp"
        assert result["task_dir"] == f"{INSTALL_BASE}/fastp"

        # 验证 screen 命令被调用
        screen_calls = [c for c in fn.calls if c.startswith("screen -dmS")]
        assert len(screen_calls) == 1

    def test_submit_rewrites_conda_path(self):
        """提交时应使用 rewrite_install_cmd 替换 conda 路径。"""
        written_script = []

        def capture_fn(cmd, timeout=15):
            if cmd.startswith("echo '"):
                # 提取 base64 编码的脚本内容
                parts = cmd.split("'")
                if len(parts) >= 2:
                    try:
                        decoded = base64.b64decode(parts[1]).decode()
                        written_script.append(decoded)
                    except Exception:
                        pass
            return (0, "", "")

        EnvInstaller.submit(
            capture_fn, "fastp",
            "conda create -n fastp_env -y",
            "/opt/conda/bin/conda",
        )

        assert len(written_script) == 1
        assert "/opt/conda/bin/conda create -p /opt/conda/envs/fastp_env -y" in written_script[0]

    def test_submit_script_write_failure(self):
        """脚本写入失败时应抛出 RuntimeError。"""
        fn = make_ssh_fn({
            "mkdir -p": (0, "", ""),
            "echo '": (1, "", "Permission denied"),
        })
        with pytest.raises(RuntimeError, match="写入安装脚本失败"):
            EnvInstaller.submit(fn, "fastp", "conda create -n env -y")

    def test_submit_screen_failure(self):
        """screen 启动失败时应抛出 RuntimeError。"""
        call_count = [0]

        def fn(cmd, timeout=15):
            if cmd.startswith("screen -dmS"):
                return (1, "", "screen not found")
            return (0, "", "")

        with pytest.raises(RuntimeError, match="启动 screen 会话失败"):
            EnvInstaller.submit(fn, "fastp", "conda create -n env -y")


# ---------------------------------------------------------------------------
# check_status() 测试
# ---------------------------------------------------------------------------

class TestCheckStatus:
    """EnvInstaller.check_status() 测试。"""

    def test_running(self):
        fn = make_ssh_fn({
            "cat": (0, "RUNNING\n", ""),
        })
        result = EnvInstaller.check_status(fn, f"{INSTALL_BASE}/fastp")
        assert result["status"] == "RUNNING"
        assert result["exit_code"] == ""

    def test_done(self):
        fn = make_ssh_fn({})
        # 需要精确匹配两个不同的 cat 命令
        status_path = f'"$(eval echo $HOME/.h2ometa/env_installs/fastp)"/status.txt'
        exit_path = f'"$(eval echo $HOME/.h2ometa/env_installs/fastp)"/exit_code.txt'

        def custom_fn(cmd, timeout=10):
            if "status.txt" in cmd:
                return (0, "DONE\n", "")
            if "exit_code.txt" in cmd:
                return (0, "0\n", "")
            return (0, "", "")

        result = EnvInstaller.check_status(custom_fn, f"{INSTALL_BASE}/fastp")
        assert result["status"] == "DONE"
        assert result["exit_code"] == "0"

    def test_failed(self):
        def custom_fn(cmd, timeout=10):
            if "status.txt" in cmd:
                return (0, "FAILED\n", "")
            if "exit_code.txt" in cmd:
                return (0, "1\n", "")
            return (0, "", "")

        result = EnvInstaller.check_status(custom_fn, f"{INSTALL_BASE}/fastp")
        assert result["status"] == "FAILED"
        assert result["exit_code"] == "1"

    def test_no_status_file(self):
        fn = make_ssh_fn({
            "cat": (1, "", "No such file"),
        })
        result = EnvInstaller.check_status(fn, f"{INSTALL_BASE}/fastp")
        assert result["status"] == ""
        assert result["exit_code"] == ""


# ---------------------------------------------------------------------------
# read_log() 测试
# ---------------------------------------------------------------------------

class TestReadLog:
    """EnvInstaller.read_log() 测试。"""

    def test_basic_log(self):
        fn = make_ssh_fn({
            "tail": (0, "Solving environment...\nDone.\n", ""),
        })
        result = EnvInstaller.read_log(fn, f"{INSTALL_BASE}/fastp")
        assert "Solving environment" in result
        assert "Done." in result

    def test_log_with_ansi(self):
        fn = make_ssh_fn({
            "tail": (0, "\x1b[32mDone\x1b[0m\n", ""),
        })
        result = EnvInstaller.read_log(fn, f"{INSTALL_BASE}/fastp")
        assert "Done" in result
        assert "\x1b" not in result

    def test_empty_log(self):
        fn = make_ssh_fn({
            "tail": (1, "", "No such file"),
        })
        result = EnvInstaller.read_log(fn, f"{INSTALL_BASE}/fastp")
        assert result == ""


# ---------------------------------------------------------------------------
# is_session_alive() 测试
# ---------------------------------------------------------------------------

class TestIsSessionAlive:
    """EnvInstaller.is_session_alive() 测试。"""

    def test_alive(self):
        fn = make_ssh_fn({
            "screen -ls": (0, "h2o_install_fastp\n", ""),
        })
        assert EnvInstaller.is_session_alive(fn, "h2o_install_fastp") is True

    def test_not_alive(self):
        fn = make_ssh_fn({
            "screen -ls": (1, "", "No Sockets found"),
        })
        assert EnvInstaller.is_session_alive(fn, "h2o_install_fastp") is False


# ---------------------------------------------------------------------------
# cleanup() 测试
# ---------------------------------------------------------------------------

class TestCleanup:
    """EnvInstaller.cleanup() 测试。"""

    def test_cleanup(self):
        fn = make_ssh_fn({
            "rm -rf": (0, "", ""),
        })
        # Should not raise
        EnvInstaller.cleanup(fn, f"{INSTALL_BASE}/fastp")
        rm_calls = [c for c in fn.calls if c.startswith("rm -rf")]
        assert len(rm_calls) == 1

    def test_cleanup_failure_no_raise(self):
        """清理失败不应抛出异常。"""
        fn = make_ssh_fn({
            "rm -rf": (1, "", "Permission denied"),
        })
        EnvInstaller.cleanup(fn, f"{INSTALL_BASE}/fastp")  # Should not raise


# ---------------------------------------------------------------------------
# scan_running() 测试
# ---------------------------------------------------------------------------

class TestScanRunning:
    """EnvInstaller.scan_running() 测试。"""

    def test_scan_with_results(self):
        fn = make_ssh_fn({
            "for d in": (0, "fastp|RUNNING\nkraken2|DONE\nbusco|FAILED\n", ""),
        })
        results = EnvInstaller.scan_running(fn)
        assert len(results) == 3
        assert results[0] == {
            "tool_id": "fastp",
            "task_dir": f"{INSTALL_BASE}/fastp",
            "status": "RUNNING",
        }
        assert results[1]["status"] == "DONE"
        assert results[2]["status"] == "FAILED"

    def test_scan_empty(self):
        fn = make_ssh_fn({
            "for d in": (0, "", ""),
        })
        results = EnvInstaller.scan_running(fn)
        assert results == []

    def test_scan_failure(self):
        fn = make_ssh_fn({
            "for d in": (1, "", "error"),
        })
        results = EnvInstaller.scan_running(fn)
        assert results == []


# ---------------------------------------------------------------------------
# _sanitize_log() 测试
# ---------------------------------------------------------------------------

class TestSanitizeLog:
    """_sanitize_log() 日志清理测试。"""

    def test_removes_ansi(self):
        result = _sanitize_log("\x1b[32mhello\x1b[0m\nworld")
        assert result == "hello\nworld"

    def test_handles_cr_overwrite(self):
        result = _sanitize_log("downloading 10%\rdownloading 50%\rdownloading 100%")
        assert "downloading 100%" in result
        # \r 覆写后只保留最后一段，不应出现 "50%"
        assert "50%" not in result

    def test_filters_blank_lines(self):
        result = _sanitize_log("hello\n\n\n\nworld")
        assert result == "hello\nworld"

    def test_filters_spinner_lines(self):
        """conda spinner 行（纯 - \\ | / 字符）应被过滤。"""
        log = (
            "Collecting package metadata (repodata.json): "
            "- \r \\ \r | \r / \r - \r done\n"
            "Solving environment: / \r - \r \\ \r done"
        )
        result = _sanitize_log(log)
        assert "done" in result
        # spinner 字符不应单独出现
        lines = result.strip().splitlines()
        for line in lines:
            assert line.strip() not in ("-", "\\", "|", "/")

    def test_filters_pure_spinner_lines(self):
        """纯 spinner 行 '- \\ | /' 应被过滤。"""
        result = _sanitize_log("- \n\\ \n| \n/ \nactual content")
        assert "actual content" in result
        assert result.strip() == "actual content"

    def test_filters_spinner_tail_lines(self):
        """'Collecting package metadata (repodata.json): \\' 这类 spinner 尾行应被过滤。"""
        log = "\n".join([
            "Collecting package metadata (repodata.json): -",
            "Collecting package metadata (repodata.json): \\",
            "Collecting package metadata (repodata.json): |",
            "Collecting package metadata (repodata.json): /",
            "Collecting package metadata (repodata.json): done",
            "Solving environment: -",
            "Solving environment: \\",
            "Solving environment: done",
        ])
        result = _sanitize_log(log)
        lines = result.strip().splitlines()
        # 只保留 "done" 结尾的有意义行
        assert all("done" in l for l in lines)
        # spinner 尾行被过滤
        assert not any(l.strip().endswith(": -") for l in lines)
        assert not any(l.strip().endswith(": \\") for l in lines)
        assert not any(l.strip().endswith(": |") for l in lines)
        assert not any(l.strip().endswith(": /") for l in lines)

    def test_dedup_repeated_lines(self):
        """重复的行应被去重。"""
        log = "hello\nhello\nhello\nworld"
        result = _sanitize_log(log)
        assert result == "hello\nworld"

    def test_empty_input(self):
        assert _sanitize_log("") == ""

    def test_only_whitespace(self):
        assert _sanitize_log("   \n  \n  ") == ""
