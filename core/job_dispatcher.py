# core/job_dispatcher.py
"""任务分发器 — 通过 SSH + screen 在远端启动分析任务。

职责:
  1. 将包装脚本写入远端任务目录
  2. 使用 screen -dmS 启动后台会话
  3. 返回 job_id 供 JobMonitor 追踪
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)


class DispatchError(Exception):
    """任务分发失败异常。"""


class JobDispatcher:
    """任务分发器 — 在远端 Linux 服务器上启动 screen 会话。

    用法::

        job_id = JobDispatcher.submit(ssh, wrapped_script, execution_id, task_dir)
    """

    # screen 启动超时（秒）
    SCREEN_TIMEOUT = 15

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

        # 1. 创建任务目录
        rc, _, err = ssh_service.run(f"mkdir -p {task_dir}", timeout=10)
        if rc != 0:
            raise DispatchError(f"创建任务目录失败: {err}")

        # 2. 将包装脚本写入远端
        # 使用 heredoc 避免转义问题
        write_cmd = f"cat > {script_path} << 'H2O_SCRIPT_EOF'\n{wrapped_script}\nH2O_SCRIPT_EOF"
        rc, _, err = ssh_service.run(write_cmd, timeout=10)
        if rc != 0:
            raise DispatchError(f"写入脚本失败: {err}")

        # 3. 设置执行权限
        rc, _, err = ssh_service.run(f"chmod +x {script_path}", timeout=10)
        if rc != 0:
            raise DispatchError(f"设置脚本权限失败: {err}")

        # 4. 使用 screen 启动
        screen_cmd = f"screen -dmS {job_id} bash {script_path}"
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
            rc, out, _ = ssh_service.run(f"screen -ls | grep -q {job_id}", timeout=10)
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
            rc, _, _ = ssh_service.run(f"screen -S {job_id} -X quit", timeout=10)
            if rc == 0:
                logger.info("已终止 screen 会话: %s", job_id)
            return rc == 0
        except Exception:
            logger.exception("终止 screen 会话失败: %s", job_id)
            return False
