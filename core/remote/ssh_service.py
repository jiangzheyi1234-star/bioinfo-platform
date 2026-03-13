"""SSH 服务封装

提供远程命令执行、文件传输等功能。
集成 SSHReconnector 实现连接丢失时的自动重连。
"""
import logging
from typing import Optional, Tuple, Callable, List

import paramiko
from PyQt6.QtCore import QObject, pyqtSignal

from core.remote.ssh_reconnector import SSHReconnector

logger = logging.getLogger(__name__)


class SSHService(QObject):
    """SSH 服务封装

    封装 paramiko.SSHClient，提供命令执行、文件传输等功能。
    集成 SSHReconnector，在连接丢失时自动触发重连。

    Signals:
        connection_status_changed(bool): 连接状态变化 (True=已连接, False=断开)
    """

    connection_status_changed = pyqtSignal(bool)

    def __init__(
        self,
        client_provider: Callable[[], Optional[paramiko.SSHClient]],
        connect_fn: Optional[Callable[[], paramiko.SSHClient]] = None,
        max_retries: int = 5,
        parent: Optional[QObject] = None,
    ):
        """
        Args:
            client_provider: 返回当前活跃的 paramiko.SSHClient（或 None）
            connect_fn: 重连函数，调用后返回新的 SSHClient。
                        若为 None，则不启用自动重连。
            max_retries: SSHReconnector 最大重试次数，默认 5
            parent: 父 QObject
        """
        super().__init__(parent)
        self._client_provider = client_provider
        self._connect_fn = connect_fn
        self._reconnected_client: Optional[paramiko.SSHClient] = None

        # 初始化重连器（仅在提供 connect_fn 时）
        self._reconnector: Optional[SSHReconnector] = None
        if connect_fn:
            self._reconnector = SSHReconnector(
                connect_fn=connect_fn,
                max_retries=max_retries,
                parent=self,
            )
            self._reconnector.reconnected.connect(self._on_reconnected)
            self._reconnector.connection_lost.connect(self._on_connection_lost)
            self._reconnector.reconnect_failed.connect(self._on_reconnect_failed)

    @property
    def reconnector(self) -> Optional[SSHReconnector]:
        """获取重连器实例（可用于外部连接信号）"""
        return self._reconnector

    @property
    def is_connected(self) -> bool:
        """检查 SSH 连接是否可用"""
        client = self._client_provider()
        if not client:
            return False
        return self._check_transport(client)

    def _client(self) -> Optional[paramiko.SSHClient]:
        # 优先使用重连后的客户端
        if self._reconnected_client is not None:
            if self._check_transport(self._reconnected_client):
                return self._reconnected_client
            self._reconnected_client = None
        return self._client_provider()

    def _check_transport(self, client: paramiko.SSHClient) -> bool:
        """检查 SSH 连接是否仍然活跃"""
        try:
            transport = client.get_transport()
            if transport and transport.is_active():
                transport.send_ignore()
                return True
            return False
        except Exception:
            return False

    def _ensure_connection(self) -> paramiko.SSHClient:
        """确保 SSH 连接可用，连接丢失时触发重连"""
        client = self._client()
        if client and self._check_transport(client):
            return client

        # 连接不可用，触发重连
        if self._reconnector and not self._reconnector.is_reconnecting:
            logger.warning("SSH 连接不可用，触发自动重连")
            self._reconnector.start()

        raise RuntimeError("SSH 未连接")

    def _on_reconnected(self, client: paramiko.SSHClient) -> None:
        """重连成功回调，存储新客户端"""
        logger.info("SSH 连接已恢复")
        self._reconnected_client = client
        self.connection_status_changed.emit(True)

    def _on_connection_lost(self) -> None:
        """连接丢失回调"""
        logger.warning("SSH 连接已丢失")
        self.connection_status_changed.emit(False)

    def _on_reconnect_failed(self, error: str) -> None:
        """重连失败回调"""
        logger.error("SSH 重连最终失败: %s", error)
        self.connection_status_changed.emit(False)

    def run(self, cmd: str, timeout: int = 10) -> Tuple[int, str, str]:
        """执行远程命令

        Args:
            cmd: 要执行的命令
            timeout: 超时时间（秒）

        Returns:
            (exit_code, stdout, stderr) 元组
        """
        client = self._ensure_connection()
        stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
        rc = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="ignore")
        err = stderr.read().decode("utf-8", errors="ignore")
        return rc, out, err

    def run_async(self, cmd: str) -> None:
        """执行远程命令但不等待结果（用于启动后台任务）"""
        client = self._ensure_connection()
        client.exec_command(cmd, timeout=5)

    def sftp(self) -> paramiko.SFTPClient:
        """获取 SFTP 客户端"""
        client = self._ensure_connection()
        return client.open_sftp()

    def upload(self, local_path: str, remote_path: str) -> None:
        """上传本地文件到远端

        Args:
            local_path: 本地文件路径
            remote_path: 远端文件路径
        """
        sftp_client = self.sftp()
        try:
            sftp_client.put(local_path, remote_path)
        finally:
            sftp_client.close()

    def download(self, remote_path: str, local_path: str) -> None:
        """从远端下载文件到本地

        Args:
            remote_path: 远端文件路径
            local_path: 本地文件路径
        """
        sftp_client = self.sftp()
        try:
            sftp_client.get(remote_path, local_path)
        finally:
            sftp_client.close()

    def check_command_exists(self, command: str) -> bool:
        """检查远端是否存在某个命令"""
        try:
            rc, out, _ = self.run(f"command -v {command}", timeout=10)
            return rc == 0 and out.strip() != ""
        except Exception:
            return False

    def check_screen_session(self, session_name: str) -> bool:
        """检查指定的 screen 会话是否存在"""
        try:
            rc, out, _ = self.run(f"screen -ls | grep -q {session_name}", timeout=10)
            return rc == 0
        except Exception:
            return False

    def kill_screen_session(self, session_name: str) -> bool:
        """终止指定的 screen 会话"""
        try:
            rc, _, _ = self.run(f"screen -S {session_name} -X quit", timeout=10)
            return rc == 0
        except Exception:
            return False

    def list_screen_sessions(self) -> List[str]:
        """列出所有 screen 会话"""
        try:
            rc, out, _ = self.run("screen -ls", timeout=10)
            sessions = []
            for line in out.split('\n'):
                if '\t' in line and ('Detached' in line or 'Attached' in line):
                    parts = line.strip().split('\t')
                    if parts:
                        session_id = parts[0].split('.')[1] if '.' in parts[0] else parts[0]
                        sessions.append(session_id)
            return sessions
        except Exception:
            return []
