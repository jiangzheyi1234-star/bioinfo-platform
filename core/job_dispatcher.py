# core/job_dispatcher.py
"""任务分发器 — 通过 SSH + screen 在远端启动分析任务。

职责:
  1. 将包装脚本写入远端任务目录
  2. 使用 screen -dmS 启动后台会话
  3. 可选：同步等待任务完成（事件驱动模式）
"""
import logging
import shlex
import time
import uuid
from typing import Any, Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot

logger = logging.getLogger(__name__)


class DispatchError(Exception):
    """任务分发失败异常。"""


class JobDispatcher(QObject):
    """任务分发器 — 在远端 Linux 服务器上启动 screen 会话。

    用法::

        job_id = JobDispatcher.submit(ssh, wrapped_script, execution_id, task_dir)
    """

    # screen 启动超时（秒）
    SCREEN_TIMEOUT = 15

    # 默认检查间隔（秒）- 事件驱动模式下轮询 screen 状态
    CHECK_INTERVAL = 2

    job_completed = pyqtSignal(str)  # execution_id
    job_failed = pyqtSignal(str, str)  # execution_id, error_msg

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running_waiters: dict[str, _WaiterThread] = {}

    @staticmethod
    def submit(
        ssh_service: Any,
        wrapped_script: str,
        execution_id: str,
        task_dir: str,
    ) -> str:
        """将包装脚本写入远端并通过 screen 启动。

        Args:
            ssh_service: SSHService 实例（需要 run 方法）。
            wrapped_script: CommandBuilder.wrap() 生成的完整 bash 脚本。
            execution_id: 执行记录 ID。
            task_dir: 远端任务目录路径。

        Returns:
            job_id (screen 会话名)。

        Raises:
            DispatchError: 创建目录或启动 screen 失败。
        """
        job_id = f"h2o_{execution_id}"
        script_path = f"{task_dir}/run.sh"
        q_task_dir = shlex.quote(task_dir)
        q_script_path = shlex.quote(script_path)
        q_job_id = shlex.quote(job_id)

        # 1. 创建任务目录
        rc, _, err = ssh_service.run(f"mkdir -p {q_task_dir}", timeout=10)
        if rc != 0:
            raise DispatchError(f"创建任务目录失败: {err}")

        # 2. 将包装脚本写入远端
        # 使用 heredoc 避免转义问题
        marker = f"H2O_SCRIPT_EOF_{uuid.uuid4().hex}"
        write_cmd = f"cat > {q_script_path} << '{marker}'\n{wrapped_script}\n{marker}"
        rc, _, err = ssh_service.run(write_cmd, timeout=10)
        if rc != 0:
            raise DispatchError(f"写入脚本失败: {err}")

        # 3. 设置执行权限
        rc, _, err = ssh_service.run(f"chmod +x {q_script_path}", timeout=10)
        if rc != 0:
            raise DispatchError(f"设置脚本权限失败: {err}")

        # 4. 使用 screen 启动
        screen_cmd = f"screen -dmS {q_job_id} bash {q_script_path}"
        rc, _, err = ssh_service.run(screen_cmd, timeout=JobDispatcher.SCREEN_TIMEOUT)
        if rc != 0:
            raise DispatchError(f"启动 screen 会话失败: {err}")

        logger.info("已分发任务: job_id=%s, task_dir=%s", job_id, task_dir)
        return job_id

    @staticmethod
    def check_session_exists(ssh_service: Any, job_id: str) -> bool:
        """检查 screen 会话是否存在。

        Args:
            ssh_service: SSHService 实例。
            job_id: screen 会话名。

        Returns:
            True 如果会话存在。
        """
        try:
            rc, _, _ = ssh_service.run(
                f"screen -ls | grep -Fq -- {shlex.quote(job_id)}",
                timeout=10,
            )
            return rc == 0
        except Exception:
            logger.exception("检查 screen 会话失败: %s", job_id)
            return False

    @staticmethod
    def kill_session(ssh_service: Any, job_id: str) -> bool:
        """终止 screen 会话。

        Args:
            ssh_service: SSHService 实例。
            job_id: screen 会话名。

        Returns:
            True 如果成功终止。
        """
        try:
            rc, _, _ = ssh_service.run(
                f"screen -S {shlex.quote(job_id)} -X quit",
                timeout=10,
            )
            if rc == 0:
                logger.info("已终止 screen 会话: %s", job_id)
            return rc == 0
        except Exception:
            logger.exception("终止 screen 会话失败: %s", job_id)
            return False

    # ------------------------------------------------------------------
    # 事件驱动模式：后台线程同步等待任务完成
    # ------------------------------------------------------------------

    def start_waiting(
        self,
        ssh_service: Any,
        execution_id: str,
        job_id: str,
        task_dir: str,
    ) -> None:
        """启动后台线程等待任务完成（事件驱动）。

        任务完成后通过信号通知：
        - job_completed(execution_id)
        - job_failed(execution_id, error_msg)

        Args:
            ssh_service: SSHService 实例。
            execution_id: 执行记录 ID。
            job_id: screen 会话名。
            task_dir: 远端任务目录。
        """
        # 如果已有等待中的线程，先停止
        if execution_id in self._running_waiters:
            self._running_waiters[execution_id].stop()
            del self._running_waiters[execution_id]

        waiter = _WaiterThread(
            ssh_service=ssh_service,
            execution_id=execution_id,
            job_id=job_id,
            task_dir=task_dir,
            check_interval=self.CHECK_INTERVAL,
        )
        waiter.completed.connect(self._on_waiter_completed)
        waiter.failed.connect(self._on_waiter_failed)
        waiter.start()

        self._running_waiters[execution_id] = waiter
        logger.info("已启动任务等待线程: %s", execution_id)

    def stop_waiting(self, execution_id: str) -> None:
        """停止指定任务的等待线程。

        Args:
            execution_id: 执行记录 ID。
        """
        if execution_id in self._running_waiters:
            waiter = self._running_waiters[execution_id]
            waiter.stop()
            waiter.wait(2000)  # 等待最多 2 秒
            del self._running_waiters[execution_id]
            logger.info("已停止任务等待线程: %s", execution_id)

    def stop_all(self) -> None:
        """停止所有等待线程。"""
        for execution_id in list(self._running_waiters.keys()):
            self.stop_waiting(execution_id)

    @pyqtSlot(str)
    def _on_waiter_completed(self, execution_id: str) -> None:
        """等待线程完成回调。"""
        if execution_id in self._running_waiters:
            del self._running_waiters[execution_id]
        self.job_completed.emit(execution_id)

    @pyqtSlot(str, str)
    def _on_waiter_failed(self, execution_id: str, error_msg: str) -> None:
        """等待线程失败回调。"""
        if execution_id in self._running_waiters:
            del self._running_waiters[execution_id]
        self.job_failed.emit(execution_id, error_msg)


class _WaiterThread(QThread):
    """后台等待线程 — 同步轮询 screen 会话状态，不阻塞 UI。

    优势：比 JobMonitor 的固定轮询更轻量，只有在任务完成时才频繁检查。
    """

    completed = pyqtSignal(str)  # execution_id
    failed = pyqtSignal(str, str)  # execution_id, error_msg

    def __init__(
        self,
        ssh_service: Any,
        execution_id: str,
        job_id: str,
        task_dir: str,
        check_interval: int = 2,
    ):
        super().__init__()
        self._ssh_service = ssh_service
        self._execution_id = execution_id
        self._job_id = job_id
        self._task_dir = task_dir
        self._check_interval = check_interval
        self._stop_requested = False

    def run(self) -> None:
        """轮询等待任务完成。"""
        logger.debug("开始等待任务: %s", self._execution_id)

        while not self._stop_requested:
            # 检查 screen 会话是否还存在
            session_exists = self._check_screen_session()
            if session_exists is None:
                # 网络抖动/SSH 临时异常时，继续等待，避免误判任务失败。
                self._sleep(self._check_interval)
                continue

            if not session_exists:
                # screen 会话已结束，读取最终状态
                self._check_final_status()
                return

            # 会话还在运行，检查状态文件（可选，用于心跳）
            self._check_status_file()

            # 等待下次检查
            self._sleep(self._check_interval)

        # 请求停止
        logger.info("等待线程已停止: %s", self._execution_id)

    def stop(self) -> None:
        """请求停止等待。"""
        self._stop_requested = True

    def _check_screen_session(self) -> Optional[bool]:
        """检查 screen 会话是否存在。

        Returns:
            True: 会话存在
            False: 会话不存在
            None: 检查过程发生瞬时错误，状态未知
        """
        try:
            rc, _, _ = self._ssh_service.run(
                f"screen -ls | grep -Fq -- {shlex.quote(self._job_id)}",
                timeout=10,
            )
            return rc == 0
        except Exception as exc:
            logger.debug("检查 screen 会话异常(忽略并重试): %s", exc)
            return None

    def _check_status_file(self) -> None:
        """检查任务状态文件。"""
        try:
            # 读取状态
            rc, status, _ = self._ssh_service.run(
                f"cat {shlex.quote(f'{self._task_dir}/status.txt')} 2>/dev/null",
                timeout=10,
            )
            if rc == 0:
                status = status.strip()
                # 可以在这里发出 progress 信号
                if status in ("DONE", "FAILED"):
                    logger.debug("任务状态提前完成: %s -> %s", self._execution_id, status)

        except Exception:
            pass

    def _check_final_status(self) -> None:
        """检查最终状态并发出信号。"""
        try:
            # 读取 exit_code
            rc, exit_code, _ = self._ssh_service.run(
                f"cat {shlex.quote(f'{self._task_dir}/exit_code.txt')} 2>/dev/null",
                timeout=10,
            )

            if rc == 0 and exit_code.strip() == "0":
                logger.info("任务完成: %s", self._execution_id)
                self.completed.emit(self._execution_id)
                return

            # 读取失败原因
            error_msg = "任务异常终止"
            try:
                rc2, log_content, _ = self._ssh_service.run(
                    f"tail -20 {shlex.quote(f'{self._task_dir}/task.log')} 2>/dev/null",
                    timeout=10,
                )
                if rc2 == 0 and log_content:
                    error_msg = log_content[-500:]
            except Exception:
                pass

            logger.error("任务失败: %s, %s", self._execution_id, error_msg[:100])
            self.failed.emit(self._execution_id, error_msg)

        except Exception as e:
            logger.exception("检查最终状态失败: %s", self._execution_id)
            self.failed.emit(self._execution_id, str(e))

    def _sleep(self, seconds: float) -> None:
        """可中断的睡眠。"""
        elapsed = 0.0
        while elapsed < seconds and not self._stop_requested:
            step = min(0.2, seconds - elapsed)
            self.msleep(int(step * 1000))
            elapsed += step
