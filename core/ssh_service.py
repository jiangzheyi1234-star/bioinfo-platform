from typing import Optional, Tuple, Callable
import paramiko
import time

class SSHService:
    def __init__(self, client_provider: Callable[[], Optional[paramiko.SSHClient]]):
        """
        client_provider: 返回当前活跃的 paramiko.SSHClient（或 None）
        """
        self._client_provider = client_provider
        self._reconnect_attempts = 3
        self._reconnect_delay = 2

    def _client(self) -> Optional[paramiko.SSHClient]:
        return self._client_provider()

    def _ensure_connection(self) -> paramiko.SSHClient:
        """确保 SSH 连接可用，必要时尝试重连"""
        client = self._client()
        if client and self._is_connected(client):
            return client
        raise RuntimeError("SSH 未连接")

    def _is_connected(self, client: paramiko.SSHClient) -> bool:
        """检查 SSH 连接是否仍然活跃"""
        try:
            transport = client.get_transport()
            if transport and transport.is_active():
                # 发送心跳检测
                transport.send_ignore()
                return True
            return False
        except:
            return False

    def run(self, cmd: str, timeout: int = 10) -> Tuple[int, str, str]:
        """
        执行远程命令，返回 (exit_code, stdout, stderr)
        """
        client = self._ensure_connection()
        stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
        rc = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="ignore")
        err = stderr.read().decode("utf-8", errors="ignore")
        return rc, out, err

    def run_async(self, cmd: str) -> None:
        """
        执行远程命令但不等待结果（用于启动后台任务）
        """
        client = self._ensure_connection()
        client.exec_command(cmd, timeout=5)
        # 不等待返回，立即返回

    def sftp(self) -> paramiko.SFTPClient:
        """
        获取 SFTP 客户端
        """
        client = self._ensure_connection()
        return client.open_sftp()

    def upload(self, local_path: str, remote_path: str) -> None:
        sftp_client = self.sftp()
        try:
            sftp_client.put(local_path, remote_path)
        finally:
            sftp_client.close()

    def download(self, remote_path: str, local_path: str) -> None:
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
        except:
            return False

    def check_screen_session(self, session_name: str) -> bool:
        """检查指定的 screen 会话是否存在"""
        try:
            rc, out, _ = self.run(f"screen -ls | grep -q {session_name}", timeout=10)
            return rc == 0
        except:
            return False

    def kill_screen_session(self, session_name: str) -> bool:
        """终止指定的 screen 会话"""
        try:
            rc, _, _ = self.run(f"screen -S {session_name} -X quit", timeout=10)
            return rc == 0
        except:
            return False

    def list_screen_sessions(self) -> list:
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
        except:
            return []

