# tests/test_job_dispatcher.py
"""JobDispatcher + JobMonitor 单元测试 — 使用 mock SSH 服务测试分发和监控逻辑。"""
import sys
from unittest.mock import MagicMock, call, patch

import pytest

from core.job_dispatcher import DispatchError, JobDispatcher
from core.job_monitor import JobMonitor, MonitoredJob

# PyQt6 信号需要 QCoreApplication 实例才能工作
from PyQt6.QtCore import QCoreApplication

_app = QCoreApplication.instance() or QCoreApplication(sys.argv)


# ---------------------------------------------------------------------------
# Mock SSH Service
# ---------------------------------------------------------------------------

class MockSSHService:
    """模拟 SSHService，可预设每次 run() 调用的返回值。"""

    def __init__(self, responses: list[tuple[int, str, str]] | None = None):
        self._responses = list(responses) if responses else []
        self._call_index = 0
        self.commands: list[str] = []

    def run(self, cmd: str, timeout: int = 10) -> tuple[int, str, str]:
        self.commands.append(cmd)
        if self._call_index < len(self._responses):
            resp = self._responses[self._call_index]
            self._call_index += 1
            return resp
        return (0, "", "")


# ---------------------------------------------------------------------------
# JobDispatcher 测试
# ---------------------------------------------------------------------------

class TestJobDispatcher:
    """JobDispatcher.submit() 测试。"""

    def test_submit_success(self) -> None:
        """成功分发任务应返回 job_id。"""
        ssh = MockSSHService([
            (0, "", ""),   # mkdir -p
            (0, "", ""),   # cat > run.sh (heredoc)
            (0, "", ""),   # chmod +x
            (0, "", ""),   # screen -dmS
        ])
        job_id = JobDispatcher.submit(
            ssh_service=ssh,
            wrapped_script="#!/bin/bash\necho hello",
            execution_id="exec_001",
            task_dir="/tmp/task_001",
        )
        assert job_id == "h2o_exec_001"
        assert len(ssh.commands) == 4
        assert "mkdir -p /tmp/task_001" in ssh.commands[0]
        assert "screen -dmS h2o_exec_001" in ssh.commands[3]

    def test_submit_mkdir_failure(self) -> None:
        """创建目录失败应抛出 DispatchError。"""
        ssh = MockSSHService([
            (1, "", "Permission denied"),  # mkdir -p 失败
        ])
        with pytest.raises(DispatchError, match="创建任务目录失败"):
            JobDispatcher.submit(ssh, "echo", "exec_002", "/tmp/task_002")

    def test_submit_write_script_failure(self) -> None:
        """写入脚本失败应抛出 DispatchError。"""
        ssh = MockSSHService([
            (0, "", ""),   # mkdir OK
            (1, "", "No space left"),  # cat > run.sh 失败
        ])
        with pytest.raises(DispatchError, match="写入脚本失败"):
            JobDispatcher.submit(ssh, "echo", "exec_003", "/tmp/task_003")

    def test_submit_chmod_failure(self) -> None:
        """设置权限失败应抛出 DispatchError。"""
        ssh = MockSSHService([
            (0, "", ""),   # mkdir OK
            (0, "", ""),   # cat OK
            (1, "", "Operation not permitted"),  # chmod 失败
        ])
        with pytest.raises(DispatchError, match="设置脚本权限失败"):
            JobDispatcher.submit(ssh, "echo", "exec_004", "/tmp/task_004")

    def test_submit_screen_failure(self) -> None:
        """启动 screen 失败应抛出 DispatchError。"""
        ssh = MockSSHService([
            (0, "", ""),   # mkdir OK
            (0, "", ""),   # cat OK
            (0, "", ""),   # chmod OK
            (1, "", "screen not found"),  # screen 失败
        ])
        with pytest.raises(DispatchError, match="启动 screen 会话失败"):
            JobDispatcher.submit(ssh, "echo", "exec_005", "/tmp/task_005")

    def test_submit_script_content_in_heredoc(self) -> None:
        """包装脚本内容应通过 heredoc 写入。"""
        ssh = MockSSHService([
            (0, "", ""),  # mkdir
            (0, "", ""),  # cat heredoc
            (0, "", ""),  # chmod
            (0, "", ""),  # screen
        ])
        script = "#!/bin/bash\nset -e\necho 'running fastp'"
        JobDispatcher.submit(ssh, script, "exec_006", "/tmp/t006")
        # 第二条命令应包含 heredoc 和脚本内容
        write_cmd = ssh.commands[1]
        assert "H2O_SCRIPT_EOF" in write_cmd
        assert "echo 'running fastp'" in write_cmd


class TestJobDispatcherSessionOps:
    """JobDispatcher 会话操作测试。"""

    def test_check_session_exists_true(self) -> None:
        """session 存在时返回 True。"""
        ssh = MockSSHService([(0, "", "")])
        assert JobDispatcher.check_session_exists(ssh, "h2o_test") is True

    def test_check_session_exists_false(self) -> None:
        """session 不存在时返回 False。"""
        ssh = MockSSHService([(1, "", "")])
        assert JobDispatcher.check_session_exists(ssh, "h2o_test") is False

    def test_check_session_handles_exception(self) -> None:
        """SSH 异常时返回 False。"""
        ssh = MagicMock()
        ssh.run.side_effect = RuntimeError("SSH disconnected")
        assert JobDispatcher.check_session_exists(ssh, "h2o_test") is False

    def test_kill_session_success(self) -> None:
        """成功终止 session 返回 True。"""
        ssh = MockSSHService([(0, "", "")])
        assert JobDispatcher.kill_session(ssh, "h2o_test") is True

    def test_kill_session_failure(self) -> None:
        """终止 session 失败返回 False。"""
        ssh = MockSSHService([(1, "", "")])
        assert JobDispatcher.kill_session(ssh, "h2o_test") is False


# ---------------------------------------------------------------------------
# JobMonitor 测试（不启动线程，直接测试内部方法）
# ---------------------------------------------------------------------------

class TestJobMonitor:
    """JobMonitor 单元测试。"""

    def test_add_and_remove_job(self) -> None:
        """添加和移除任务。"""
        monitor = JobMonitor(poll_interval=1.0)
        ssh = MockSSHService()
        monitor.add_job("exec_001", "h2o_001", "/tmp/t001", ssh)
        assert monitor.monitored_count == 1

        monitor.add_job("exec_002", "h2o_002", "/tmp/t002", ssh)
        assert monitor.monitored_count == 2

        monitor.remove_job("exec_001")
        assert monitor.monitored_count == 1

        monitor.remove_job("exec_002")
        assert monitor.monitored_count == 0

    def test_remove_nonexistent_job(self) -> None:
        """移除不存在的任务应无异常。"""
        monitor = JobMonitor()
        monitor.remove_job("nonexistent")
        assert monitor.monitored_count == 0

    def test_poll_job_completed(self) -> None:
        """状态为 DONE 时应发出 job_completed 信号。"""
        ssh = MockSSHService([
            (0, "DONE\n", ""),  # cat status.txt
        ])
        monitor = JobMonitor(poll_interval=1.0)
        job = MonitoredJob(
            execution_id="exec_done",
            job_id="h2o_done",
            task_dir="/tmp/done",
            ssh_service=ssh,
        )

        completed_ids = []
        monitor.job_completed.connect(lambda eid: completed_ids.append(eid))
        monitor._poll_job(job)

        assert "exec_done" in completed_ids

    def test_poll_job_failed(self) -> None:
        """状态为 FAILED 时应发出 job_failed 信号。"""
        ssh = MockSSHService([
            (0, "FAILED\n", ""),       # cat status.txt
            (0, "Error: OOM\n", ""),   # cat task.log
        ])
        monitor = JobMonitor(poll_interval=1.0)
        job = MonitoredJob(
            execution_id="exec_fail",
            job_id="h2o_fail",
            task_dir="/tmp/fail",
            ssh_service=ssh,
        )

        failed_ids = []
        monitor.job_failed.connect(lambda eid, msg: failed_ids.append((eid, msg)))
        monitor._poll_job(job)

        assert len(failed_ids) == 1
        assert failed_ids[0][0] == "exec_fail"
        assert "OOM" in failed_ids[0][1]

    def test_poll_job_running_emits_progress(self) -> None:
        """状态为 RUNNING 时应发出 job_progress 信号。"""
        import time
        current_ts = str(int(time.time()))
        ssh = MockSSHService([
            (0, "RUNNING\n", ""),       # cat status.txt
            (0, current_ts + "\n", ""), # cat heartbeat.txt
            (0, current_ts + "\n", ""), # date +%s
        ])
        monitor = JobMonitor(poll_interval=1.0)
        job = MonitoredJob(
            execution_id="exec_run",
            job_id="h2o_run",
            task_dir="/tmp/run",
            ssh_service=ssh,
        )

        progress_updates = []
        monitor.job_progress.connect(lambda eid, status: progress_updates.append((eid, status)))
        monitor._poll_job(job)

        assert len(progress_updates) >= 1
        assert progress_updates[0] == ("exec_run", "RUNNING")

    def test_poll_job_stalled_heartbeat(self) -> None:
        """心跳超时时应发出 job_stalled 信号。"""
        ssh = MockSSHService([
            (0, "RUNNING\n", ""),   # cat status.txt
            (0, "1000\n", ""),      # cat heartbeat.txt (很久以前)
            (0, "9999999999\n", ""),  # date +%s (远端当前时间)
        ])
        monitor = JobMonitor(poll_interval=1.0, heartbeat_timeout=60)
        job = MonitoredJob(
            execution_id="exec_stall",
            job_id="h2o_stall",
            task_dir="/tmp/stall",
            ssh_service=ssh,
            last_heartbeat=1000.0,
        )

        stalled_ids = []
        monitor.job_stalled.connect(lambda eid: stalled_ids.append(eid))
        monitor._poll_job(job)

        assert "exec_stall" in stalled_ids

    def test_poll_unknown_status_screen_gone_exit_0(self) -> None:
        """状态未知且 screen 不存在但 exit_code=0 应视为完成。"""
        ssh = MockSSHService([
            (0, "\n", ""),     # cat status.txt -> 空
            (1, "", ""),       # screen -ls grep -> 不存在
            (0, "0\n", ""),    # cat exit_code.txt
        ])
        monitor = JobMonitor(poll_interval=1.0)
        job = MonitoredJob(
            execution_id="exec_ghost",
            job_id="h2o_ghost",
            task_dir="/tmp/ghost",
            ssh_service=ssh,
        )

        completed_ids = []
        monitor.job_completed.connect(lambda eid: completed_ids.append(eid))
        monitor._poll_job(job)

        assert "exec_ghost" in completed_ids

    def test_poll_unknown_status_screen_gone_nonzero_exit(self) -> None:
        """状态未知且 screen 不存在且 exit_code!=0 应视为失败。"""
        ssh = MockSSHService([
            (0, "\n", ""),     # cat status.txt -> 空
            (1, "", ""),       # screen -ls grep -> 不存在
            (0, "137\n", ""),  # cat exit_code.txt (OOM kill)
        ])
        monitor = JobMonitor(poll_interval=1.0)
        job = MonitoredJob(
            execution_id="exec_crash",
            job_id="h2o_crash",
            task_dir="/tmp/crash",
            ssh_service=ssh,
        )

        failed_ids = []
        monitor.job_failed.connect(lambda eid, msg: failed_ids.append((eid, msg)))
        monitor._poll_job(job)

        assert len(failed_ids) == 1
        assert "137" in failed_ids[0][1]

    def test_request_stop(self) -> None:
        """request_stop 应设置停止标志。"""
        monitor = JobMonitor()
        assert monitor._stop_requested is False
        monitor.request_stop()
        assert monitor._stop_requested is True
