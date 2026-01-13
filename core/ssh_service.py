from typing import Optional, Tuple, Callable
import paramiko

class SSHService:
    def __init__(self, client_provider: Callable[[], Optional[paramiko.SSHClient]]):
        """
        client_provider: 返回当前活跃的 paramiko.SSHClient（或 None）
        """
        self._client_provider = client_provider

    def _client(self) -> Optional[paramiko.SSHClient]:
        return self._client_provider()

    def run(self, cmd: str, timeout: int = 10) -> Tuple[int, str, str]:
        """
        执行远程命令，返回 (exit_code, stdout, stderr)
        """
        client = self._client()
        if not client:
            raise RuntimeError("SSH 未连接")
        stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
        rc = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="ignore")
        err = stderr.read().decode("utf-8", errors="ignore")
        return rc, out, err

    def sftp(self) -> paramiko.SFTPClient:
        """
        获取 SFTP 客户端
        """
        client = self._client()
        if not client:
            raise RuntimeError("SSH 未连接")
        return client.open_sftp()

    def upload(self, local_path: str, remote_path: str) -> None:
        with self.sftp() as s:
            s.put(local_path, remote_path)

    def download(self, remote_path: str, local_path: str) -> None:
        with self.sftp() as s:
            s.get(remote_path, local_path)

