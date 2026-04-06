"""重试管理器 — 区分瞬时/永久错误，自动重试瞬时错误

瞬时错误（SSH 断连、超时、连接错误）自动重试最多 2 次。
永久错误（参数错误、文件不存在等）直接标记为需手动重试。
"""
import logging
from typing import Callable, Dict, Optional

from core.qt_compat import QObject, pyqtSignal

logger = logging.getLogger(__name__)

# 瞬时错误关键词（不区分大小写匹配）
TRANSIENT_ERRORS = [
    "ssh",
    "timeout",
    "connection",
    "timed out",
    "network",
    "broken pipe",
    "reset by peer",
    "transport",
    "socket",
]

# 最大自动重试次数
MAX_AUTO_RETRY = 2


class RetryManager(QObject):
    """重试管理器

    根据错误类型决定是否自动重试：
    - 瞬时错误：自动重试，最多 MAX_AUTO_RETRY 次
    - 永久错误：标记为需手动重试

    Signals:
        retry_scheduled(str): 已安排自动重试，参数为 execution_id
        retry_exhausted(str, str): 自动重试用尽，参数为 (execution_id, error_msg)
    """

    retry_scheduled = pyqtSignal(str)  # execution_id
    retry_exhausted = pyqtSignal(str, str)  # execution_id, error_msg

    def __init__(
        self,
        retry_callback: Optional[Callable[[str], None]] = None,
        parent: Optional[QObject] = None,
    ):
        """
        Args:
            retry_callback: 执行重试的回调函数，接收 execution_id。
                            由外部模块（如 ToolEngine）提供，负责重新提交任务。
            parent: 父 QObject
        """
        super().__init__(parent)
        self._retry_callback = retry_callback
        self._retry_counts: Dict[str, int] = {}

    def on_task_failed(self, execution_id: str, error_msg: str) -> str:
        """处理任务失败

        根据错误类型和已重试次数决定处理方式。

        Args:
            execution_id: 失败任务的标识
            error_msg: 错误消息

        Returns:
            'auto_retry': 已安排自动重试
            'manual_required': 需要手动重试（永久错误或重试次数已用尽）
        """
        if self._is_transient(error_msg):
            current_count = self._retry_counts.get(execution_id, 0)

            if current_count < MAX_AUTO_RETRY:
                self._retry_counts[execution_id] = current_count + 1
                logger.info(
                    "任务 %s 瞬时错误 (第 %d/%d 次重试): %s",
                    execution_id, current_count + 1, MAX_AUTO_RETRY, error_msg,
                )

                if self._retry_callback:
                    try:
                        self._retry_callback(execution_id)
                    except Exception as e:
                        logger.error("任务 %s 重试回调失败: %s", execution_id, e)

                self.retry_scheduled.emit(execution_id)
                return "auto_retry"
            else:
                logger.warning(
                    "任务 %s 瞬时错误重试已用尽 (%d 次): %s",
                    execution_id, MAX_AUTO_RETRY, error_msg,
                )
                self.retry_exhausted.emit(execution_id, error_msg)
                return "manual_required"
        else:
            logger.warning(
                "任务 %s 永久错误，需手动重试: %s",
                execution_id, error_msg,
            )
            self.retry_exhausted.emit(execution_id, error_msg)
            return "manual_required"

    def manual_retry(self, execution_id: str) -> None:
        """手动重试 — 重置重试计数并触发重试

        Args:
            execution_id: 要重试的任务标识
        """
        self._retry_counts[execution_id] = 0
        logger.info("任务 %s 手动重试，重试计数已重置", execution_id)

        if self._retry_callback:
            try:
                self._retry_callback(execution_id)
            except Exception as e:
                logger.error("任务 %s 手动重试回调失败: %s", execution_id, e)

        self.retry_scheduled.emit(execution_id)

    def get_retry_count(self, execution_id: str) -> int:
        """获取指定任务的当前重试次数

        Args:
            execution_id: 任务标识

        Returns:
            重试次数
        """
        return self._retry_counts.get(execution_id, 0)

    def _is_transient(self, error_msg: str) -> bool:
        """判断是否为瞬时错误

        通过检查错误消息中是否包含瞬时错误关键词来判断。

        Args:
            error_msg: 错误消息

        Returns:
            True 表示瞬时错误，False 表示永久错误
        """
        lower_msg = error_msg.lower()
        return any(keyword in lower_msg for keyword in TRANSIENT_ERRORS)
