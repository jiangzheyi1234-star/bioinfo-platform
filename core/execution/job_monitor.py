# core/job_monitor.py
"""任务监控器 — 使用 QThread 轮询远端任务状态。

职责:
  1. 定期检查任务目录下的 status.txt 和 heartbeat.txt
  2. 根据状态变化发出信号: job_completed, job_failed, job_stalled, job_progress
  3. 检测心跳超时（任务卡死）
"""
import logging
import shlex
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from core.qt_compat import QMutex, QMutexLocker, QObject, QThread, pyqtSignal

logger = logging.getLogger(__name__)

# 默认心跳超时（秒）: 超过此时间无心跳更新则判定任务可能卡住
DEFAULT_HEARTBEAT_TIMEOUT = 120

# 默认轮询间隔（秒）
DEFAULT_POLL_INTERVAL = 5


@dataclass
class MonitoredJob:
    """被监控的任务信息。"""
    execution_id: str
    job_id: str
    task_dir: str
    ssh_service: Any
    last_status: str = "RUNNING"
    last_heartbeat: float = field(default_factory=time.time)
    stall_notified: bool = False


class JobMonitor(QThread):
    """任务监控线程 — 轮询远端任务状态。

    信号:
        job_completed(execution_id): 任务正常完成。
        job_failed(execution_id, error_msg): 任务失败。
        job_stalled(execution_id): 任务可能卡住（心跳超时）。
        job_progress(execution_id, status): 任务状态更新。

    用法::

        monitor = JobMonitor()
        monitor.job_completed.connect(on_completed)
        monitor.add_job("exec_001", "h2o_exec_001", "/tmp/task_dir", ssh_service)
        monitor.start()
    """

    job_completed = pyqtSignal(str)            # execution_id
    job_failed = pyqtSignal(str, str)          # execution_id, error_msg
    job_stalled = pyqtSignal(str)              # execution_id
    job_progress = pyqtSignal(str, str)        # execution_id, status

    def __init__(
        self,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        heartbeat_timeout: float = DEFAULT_HEARTBEAT_TIMEOUT,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._poll_interval = poll_interval
        self._heartbeat_timeout = heartbeat_timeout
        self._jobs: Dict[str, MonitoredJob] = {}
        self._mutex = QMutex()
        self._stop_requested = False

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def add_job(
        self,
        execution_id: str,
        job_id: str,
        task_dir: str,
        ssh_service: Any,
    ) -> None:
        """添加一个任务到监控队列。

        Args:
            execution_id: 执行记录 ID。
            job_id: screen 会话名。
            task_dir: 远端任务目录。
            ssh_service: SSHService 实例。
        """
        with QMutexLocker(self._mutex):
            self._jobs[execution_id] = MonitoredJob(
                execution_id=execution_id,
                job_id=job_id,
                task_dir=task_dir,
                ssh_service=ssh_service,
            )
        logger.info("已添加监控任务: %s (job_id=%s)", execution_id, job_id)

    def remove_job(self, execution_id: str) -> None:
        """从监控队列中移除任务。"""
        with QMutexLocker(self._mutex):
            if execution_id in self._jobs:
                del self._jobs[execution_id]
                logger.info("已移除监控任务: %s", execution_id)

    def request_stop(self) -> None:
        """请求停止监控线程。"""
        self._stop_requested = True

    @property
    def monitored_count(self) -> int:
        """当前被监控的任务数量。"""
        with QMutexLocker(self._mutex):
            return len(self._jobs)

    # ------------------------------------------------------------------
    # QThread 主循环
    # ------------------------------------------------------------------

    def run(self) -> None:
        """轮询循环: 定期检查所有任务状态。"""
        logger.info("任务监控线程已启动 (间隔: %.1fs)", self._poll_interval)
        self._stop_requested = False

        while not self._stop_requested:
            # 获取当前任务快照
            with QMutexLocker(self._mutex):
                jobs_snapshot = list(self._jobs.values())

            for job in jobs_snapshot:
                if self._stop_requested:
                    break
                try:
                    self._poll_job(job)
                except Exception:
                    logger.exception("轮询任务失败: %s", job.execution_id)

            # 等待下次轮询
            self._interruptible_sleep(self._poll_interval)

        logger.info("任务监控线程已停止")

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _poll_job(self, job: MonitoredJob) -> None:
        """检查单个任务的状态。"""
        ssh = job.ssh_service
        task_dir = job.task_dir

        # 读取 status.txt
        status = self._read_remote_file(ssh, f"{task_dir}/status.txt").strip()

        if status == "DONE":
            logger.info("任务完成: %s", job.execution_id)
            self.job_completed.emit(job.execution_id)
            self.remove_job(job.execution_id)
            return

        if status == "FAILED":
            # 尝试读取错误日志
            error_msg = self._read_remote_file(ssh, f"{task_dir}/task.log")
            # 截取最后 500 字符作为错误信息
            if len(error_msg) > 500:
                error_msg = f"...{error_msg[-500:]}"
            logger.error("任务失败: %s, 错误: %s", job.execution_id, error_msg[:200])
            self.job_failed.emit(job.execution_id, error_msg)
            self.remove_job(job.execution_id)
            return

        if status == "RUNNING":
            self.job_progress.emit(job.execution_id, "RUNNING")
            # 检查心跳
            self._check_heartbeat(job, ssh)
            return

        # 状态未知（可能任务还在初始化，或文件不存在）
        # 检查 screen 会话是否存在
        session_exists = self._check_screen_session(ssh, job.job_id)
        if not session_exists:
            # screen 会话不存在，检查 exit_code
            exit_code = self._read_remote_file(
                ssh, f"{task_dir}/exit_code.txt"
            ).strip()
            if exit_code == "0":
                logger.info("任务完成 (通过 exit_code): %s", job.execution_id)
                self.job_completed.emit(job.execution_id)
            else:
                error_msg = f"任务异常终止 (exit_code={exit_code})"
                logger.error("任务异常: %s, %s", job.execution_id, error_msg)
                self.job_failed.emit(job.execution_id, error_msg)
            self.remove_job(job.execution_id)
            return

        self.job_progress.emit(job.execution_id, f"UNKNOWN({status})")

    def _check_heartbeat(self, job: MonitoredJob, ssh: Any) -> None:
        """检查任务心跳是否超时。"""
        heartbeat_str = self._read_remote_file(
            ssh, f"{job.task_dir}/heartbeat.txt"
        ).strip()

        if heartbeat_str:
            try:
                heartbeat_ts = float(heartbeat_str)
                job.last_heartbeat = heartbeat_ts
                job.stall_notified = False
            except ValueError:
                pass

        # 获取远端当前时间来计算差值
        current_time_str = self._read_remote_file_cmd(ssh, "date +%s")
        try:
            current_ts = float(current_time_str.strip())
        except (ValueError, TypeError):
            current_ts = time.time()

        elapsed = current_ts - job.last_heartbeat
        if elapsed > self._heartbeat_timeout and not job.stall_notified:
            logger.warning(
                "任务心跳超时: %s (%.0fs 无心跳)", job.execution_id, elapsed
            )
            self.job_stalled.emit(job.execution_id)
            job.stall_notified = True

    def _read_remote_file(self, ssh: Any, remote_path: str) -> str:
        """读取远端文件内容，失败时返回空字符串。"""
        try:
            rc, out, _ = ssh.run(f"cat {shlex.quote(remote_path)} 2>/dev/null", timeout=10)
            return out if rc == 0 else ""
        except Exception:
            return ""

    def _read_remote_file_cmd(self, ssh: Any, cmd: str) -> str:
        """执行远端命令并返回输出。"""
        try:
            rc, out, _ = ssh.run(cmd, timeout=10)
            return out if rc == 0 else ""
        except Exception:
            return ""

    def _check_screen_session(self, ssh: Any, job_id: str) -> bool:
        """检查 screen 会话是否存在。"""
        try:
            rc, _, _ = ssh.run(
                f"screen -ls | grep -Fq -- {shlex.quote(job_id)}",
                timeout=10,
            )
            return rc == 0
        except Exception:
            return False

    def _interruptible_sleep(self, seconds: float) -> None:
        """可中断的睡眠: 每 0.5 秒检查一次停止标志。"""
        elapsed = 0.0
        while elapsed < seconds and not self._stop_requested:
            step = min(0.5, seconds - elapsed)
            self.msleep(int(step * 1000))
            elapsed += step
