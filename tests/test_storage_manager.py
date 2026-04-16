"""StorageManager 单元测试"""

import pytest

from core.remote.storage_manager import DiskUsage, StorageManager, StorageReport


# ── Fake SSH ──────────────────────────────────────────────


class FakeSSH:
    """测试用 SSH 桩"""

    def __init__(self):
        self._responses: dict[str, tuple[int, str, str]] = {}

    def set_response(self, cmd_prefix: str, rc: int, stdout: str, stderr: str = ""):
        self._responses[cmd_prefix] = (rc, stdout, stderr)

    def run(self, cmd: str, timeout: int = 10) -> tuple[int, str, str]:
        for prefix, response in self._responses.items():
            if cmd.startswith(prefix) or prefix in cmd:
                return response
        return (1, "", f"command not found: {cmd}")


# ── DiskUsage / StorageReport 测试 ────────────────────────


class TestDataClasses:
    """测试数据类"""

    def test_disk_usage(self):
        usage = DiskUsage(
            total_gb=500.0, used_gb=200.0, available_gb=300.0,
            percent=0.4, mount_point="/home",
        )
        assert usage.total_gb == 500.0
        assert usage.percent == 0.4

    def test_storage_report_mb(self):
        report = StorageReport(
            raw_bytes=1024 * 1024 * 100,      # 100 MB
            intermediate_bytes=1024 * 1024 * 500,  # 500 MB
            result_bytes=1024 * 1024 * 50,      # 50 MB
            total_bytes=1024 * 1024 * 650,      # 650 MB
        )
        assert report.raw_mb == 100.0
        assert report.intermediate_mb == 500.0
        assert report.result_mb == 50.0
        assert report.total_mb == 650.0


# ── df 输出解析测试 ───────────────────────────────────────


class TestParseDfOutput:
    """测试 df 输出解析"""

    def test_standard_format(self):
        line = "/dev/sda1  500107862016  200043544064  274624765952  43% /home"
        usage = StorageManager._parse_df_output(line)

        assert abs(usage.total_gb - 465.8) < 1.0
        assert abs(usage.used_gb - 186.3) < 1.0
        assert abs(usage.percent - 0.43) < 0.01
        assert usage.mount_point == "/home"

    def test_high_usage(self):
        line = "/dev/sdb  1000000000000  900000000000  100000000000  90% /data"
        usage = StorageManager._parse_df_output(line)
        assert abs(usage.percent - 0.90) < 0.01

    def test_invalid_format(self):
        with pytest.raises(RuntimeError):
            StorageManager._parse_df_output("invalid")


# ── get_disk_usage 测试 ───────────────────────────────────


class TestCheckDiskUsage:
    """测试磁盘检查"""

    def test_success(self):
        ssh = FakeSSH()
        ssh.set_response(
            "df -B1",
            0,
            "/dev/sda1  500107862016  200043544064  274624765952  43% /h2ometa",
        )
        mgr = StorageManager(ssh)
        usage = mgr.get_disk_usage("/h2ometa")

        assert abs(usage.percent - 0.43) < 0.01
        assert usage.mount_point == "/h2ometa"

    def test_failure(self):
        ssh = FakeSSH()
        ssh.set_response("df -B1", 1, "", "No such file or directory")
        mgr = StorageManager(ssh)
        with pytest.raises(RuntimeError, match="df 命令失败"):
            mgr.get_disk_usage("/nonexistent")


# ── get_storage_report 测试 ───────────────────────────────


class TestStorageReport:
    """测试存储报告"""

    def test_report_three_tiers(self):
        ssh = FakeSSH()
        ssh.set_response("du -sb", 0, "104857600")  # 100 MB for each
        mgr = StorageManager(ssh)

        report = mgr.get_storage_report("/h2ometa/projects/proj_abc")
        assert report.raw_bytes == 104857600
        assert report.intermediate_bytes == 104857600
        assert report.result_bytes == 104857600

    def test_report_empty_dirs(self):
        ssh = FakeSSH()
        ssh.set_response("du -sb", 1, "")
        mgr = StorageManager(ssh)

        report = mgr.get_storage_report("/h2ometa/projects/proj_abc")
        assert report.total_bytes == 0


# ── cleanup_intermediate 测试 ─────────────────────────────


class TestCleanupIntermediate:
    """测试中间文件清理"""

    def test_dry_run(self):
        ssh = FakeSSH()
        ssh.set_response(
            "find",
            0,
            "/data/inter/file1.fq.gz\n/data/inter/file2.fq.gz\n",
        )
        mgr = StorageManager(ssh)

        files = mgr.cleanup_intermediate("/data/inter", dry_run=True)
        assert len(files) == 2

    def test_actual_cleanup(self):
        ssh = FakeSSH()
        ssh.set_response(
            "find",
            0,
            "/data/inter/file1.fq.gz\n/data/inter/file2.fq.gz\n",
        )
        mgr = StorageManager(ssh)

        files = mgr.cleanup_intermediate("/data/inter", dry_run=False)
        assert len(files) == 2

    def test_empty_dir(self):
        ssh = FakeSSH()
        ssh.set_response("find", 0, "")
        mgr = StorageManager(ssh)

        files = mgr.cleanup_intermediate("/data/inter")
        assert len(files) == 0


# ── should_cleanup 测试 ───────────────────────────────────


class TestShouldCleanup:
    """测试清理判断"""

    def test_above_threshold(self):
        ssh = FakeSSH()
        ssh.set_response(
            "df -B1",
            0,
            "/dev/sda  1000000000000  900000000000  100000000000  90% /h2ometa",
        )
        mgr = StorageManager(ssh)
        assert mgr.should_cleanup("/h2ometa", threshold=0.85) is True

    def test_below_threshold(self):
        ssh = FakeSSH()
        ssh.set_response(
            "df -B1",
            0,
            "/dev/sda  1000000000000  400000000000  600000000000  40% /h2ometa",
        )
        mgr = StorageManager(ssh)
        assert mgr.should_cleanup("/h2ometa", threshold=0.85) is False

    def test_ssh_failure(self):
        ssh = FakeSSH()
        # 所有命令都失败
        mgr = StorageManager(ssh)
        assert mgr.should_cleanup("/h2ometa") is False
