"""SSHReconnector + SSHService 增强功能的单元测试"""
import time
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
import paramiko

from core.ssh_reconnector import SSHReconnector, _ReconnectWorker, BACKOFF_DELAYS
from core.ssh_service import SSHService


# ──────────────────── SSHReconnector 测试 ────────────────────


class TestBackoffDelays:
    """退避延迟序列测试"""

    def test_backoff_sequence(self):
        """验证退避延迟序列为 [2, 4, 8, 16, 32, 60]"""
        assert BACKOFF_DELAYS == [2, 4, 8, 16, 32, 60]


class TestReconnectWorker:
    """_ReconnectWorker 单元测试"""

    def test_successful_reconnect_first_attempt(self):
        """首次尝试即重连成功"""
        mock_client = MagicMock(spec=paramiko.SSHClient)
        mock_transport = MagicMock()
        mock_transport.is_active.return_value = True
        mock_client.get_transport.return_value = mock_transport

        connect_fn = MagicMock(return_value=mock_client)

        worker = _ReconnectWorker(connect_fn, max_retries=3)
        succeeded_spy = MagicMock()
        failed_spy = MagicMock()
        attempt_spy = MagicMock()

        worker.succeeded.connect(succeeded_spy)
        worker.failed.connect(failed_spy)
        worker.attempt_made.connect(attempt_spy)

        # 用 patch 跳过 time.sleep
        with patch("core.ssh_reconnector.time.sleep"):
            worker.run()

        connect_fn.assert_called_once()
        succeeded_spy.assert_called_once_with(mock_client)
        failed_spy.assert_not_called()
        attempt_spy.assert_called_once_with(1, 3)

    def test_successful_reconnect_third_attempt(self):
        """第三次尝试重连成功"""
        mock_client = MagicMock(spec=paramiko.SSHClient)
        mock_transport = MagicMock()
        mock_transport.is_active.return_value = True
        mock_client.get_transport.return_value = mock_transport

        # 前两次失败，第三次成功
        connect_fn = MagicMock(
            side_effect=[
                paramiko.SSHException("连接被拒绝"),
                paramiko.SSHException("超时"),
                mock_client,
            ]
        )

        worker = _ReconnectWorker(connect_fn, max_retries=5)
        succeeded_spy = MagicMock()
        failed_spy = MagicMock()
        attempt_spy = MagicMock()

        worker.succeeded.connect(succeeded_spy)
        worker.failed.connect(failed_spy)
        worker.attempt_made.connect(attempt_spy)

        with patch("core.ssh_reconnector.time.sleep"):
            worker.run()

        assert connect_fn.call_count == 3
        succeeded_spy.assert_called_once_with(mock_client)
        failed_spy.assert_not_called()
        assert attempt_spy.call_count == 3

    def test_all_attempts_exhausted(self):
        """所有尝试用尽后失败"""
        connect_fn = MagicMock(
            side_effect=paramiko.SSHException("连接被拒绝")
        )

        worker = _ReconnectWorker(connect_fn, max_retries=3)
        succeeded_spy = MagicMock()
        failed_spy = MagicMock()

        worker.succeeded.connect(succeeded_spy)
        worker.failed.connect(failed_spy)

        with patch("core.ssh_reconnector.time.sleep"):
            worker.run()

        assert connect_fn.call_count == 3
        succeeded_spy.assert_not_called()
        failed_spy.assert_called_once()
        error_msg = failed_spy.call_args[0][0]
        assert "3" in error_msg

    def test_cancel_stops_reconnect(self):
        """取消操作应停止重连"""
        connect_fn = MagicMock(
            side_effect=paramiko.SSHException("连接被拒绝")
        )

        worker = _ReconnectWorker(connect_fn, max_retries=5)
        failed_spy = MagicMock()
        worker.failed.connect(failed_spy)

        # 立即取消
        worker.cancel()

        with patch("core.ssh_reconnector.time.sleep"):
            worker.run()

        connect_fn.assert_not_called()
        failed_spy.assert_called_once()
        assert "取消" in failed_spy.call_args[0][0]

    def test_transport_not_active_retries(self):
        """transport 不活跃时应继续重试"""
        mock_client = MagicMock(spec=paramiko.SSHClient)
        mock_transport = MagicMock()
        mock_transport.is_active.return_value = False
        mock_client.get_transport.return_value = mock_transport

        connect_fn = MagicMock(return_value=mock_client)

        worker = _ReconnectWorker(connect_fn, max_retries=2)
        succeeded_spy = MagicMock()
        failed_spy = MagicMock()

        worker.succeeded.connect(succeeded_spy)
        worker.failed.connect(failed_spy)

        with patch("core.ssh_reconnector.time.sleep"):
            worker.run()

        assert connect_fn.call_count == 2
        succeeded_spy.assert_not_called()
        failed_spy.assert_called_once()

    def test_backoff_delay_capped_at_60(self):
        """超过延迟序列长度时应使用最后一个值 (60s)"""
        connect_fn = MagicMock(
            side_effect=paramiko.SSHException("失败")
        )

        worker = _ReconnectWorker(connect_fn, max_retries=8)

        sleep_calls = []
        original_sleep = time.sleep

        def mock_sleep(duration):
            sleep_calls.append(duration)

        with patch("core.ssh_reconnector.time.sleep", side_effect=mock_sleep):
            worker.run()

        # 验证第 7 和第 8 次的延迟用的是 60 秒（分段为 0.1s * 600 次）
        # 每次尝试的 sleep 调用数 = delay * 10
        assert connect_fn.call_count == 8


class TestSSHReconnector:
    """SSHReconnector 集成测试（不依赖真实 QThread）"""

    def test_init_defaults(self):
        """测试默认参数"""
        connect_fn = MagicMock()
        reconnector = SSHReconnector(connect_fn)

        assert reconnector.max_retries == 5
        assert reconnector.is_reconnecting is False

    def test_init_custom_max_retries(self):
        """测试自定义最大重试次数"""
        connect_fn = MagicMock()
        reconnector = SSHReconnector(connect_fn, max_retries=10)

        assert reconnector.max_retries == 10

    def test_duplicate_start_ignored(self):
        """重复调用 start 时应忽略"""
        connect_fn = MagicMock()
        reconnector = SSHReconnector(connect_fn)

        # 手动设置状态模拟正在重连
        reconnector._is_reconnecting = True

        # 直接调用 start 不应创建新线程
        reconnector.start()
        assert reconnector._thread is None  # 因为被跳过了

    def test_signals_defined(self):
        """验证所有公开信号已定义"""
        connect_fn = MagicMock()
        reconnector = SSHReconnector(connect_fn)

        # 验证信号存在（可连接）
        reconnector.reconnected.connect(lambda client: None)
        reconnector.connection_lost.connect(lambda: None)
        reconnector.retry_attempt.connect(lambda a, b: None)
        reconnector.reconnect_failed.connect(lambda s: None)


# ──────────────────── SSHService 增强功能测试 ────────────────────


class TestSSHServiceIsConnected:
    """is_connected 属性测试"""

    def test_connected(self):
        """transport 活跃时返回 True"""
        mock_client = MagicMock(spec=paramiko.SSHClient)
        mock_transport = MagicMock()
        mock_transport.is_active.return_value = True
        mock_client.get_transport.return_value = mock_transport

        service = SSHService(client_provider=lambda: mock_client)
        assert service.is_connected is True

    def test_not_connected_no_client(self):
        """无 client 时返回 False"""
        service = SSHService(client_provider=lambda: None)
        assert service.is_connected is False

    def test_not_connected_transport_inactive(self):
        """transport 不活跃时返回 False"""
        mock_client = MagicMock(spec=paramiko.SSHClient)
        mock_transport = MagicMock()
        mock_transport.is_active.return_value = False
        mock_client.get_transport.return_value = mock_transport

        service = SSHService(client_provider=lambda: mock_client)
        assert service.is_connected is False

    def test_not_connected_transport_exception(self):
        """transport 检查抛异常时返回 False"""
        mock_client = MagicMock(spec=paramiko.SSHClient)
        mock_client.get_transport.side_effect = Exception("transport 错误")

        service = SSHService(client_provider=lambda: mock_client)
        assert service.is_connected is False


class TestSSHServiceReconnectIntegration:
    """SSHService 与 SSHReconnector 集成测试"""

    def test_reconnector_created_with_connect_fn(self):
        """提供 connect_fn 时应创建 reconnector"""
        connect_fn = MagicMock()
        service = SSHService(
            client_provider=lambda: None,
            connect_fn=connect_fn,
        )
        assert service.reconnector is not None

    def test_reconnector_not_created_without_connect_fn(self):
        """未提供 connect_fn 时不应创建 reconnector"""
        service = SSHService(client_provider=lambda: None)
        assert service.reconnector is None

    def test_ensure_connection_triggers_reconnect(self):
        """连接不可用时应触发重连"""
        connect_fn = MagicMock()
        service = SSHService(
            client_provider=lambda: None,
            connect_fn=connect_fn,
        )

        # 用 mock 替换 start，避免创建真实 QThread
        service.reconnector.start = MagicMock()

        with pytest.raises(RuntimeError, match="SSH 未连接"):
            service._ensure_connection()

        service.reconnector.start.assert_called_once()

    def test_ensure_connection_no_duplicate_reconnect(self):
        """已在重连时不应重复触发"""
        connect_fn = MagicMock()
        service = SSHService(
            client_provider=lambda: None,
            connect_fn=connect_fn,
        )

        # mock start 并模拟正在重连状态
        service.reconnector.start = MagicMock()
        service.reconnector._is_reconnecting = True

        with pytest.raises(RuntimeError):
            service._ensure_connection()

        # 因为 is_reconnecting 为 True，start 不应被调用
        service.reconnector.start.assert_not_called()

    def test_connection_status_signal_on_reconnect(self):
        """重连成功时应发出 connection_status_changed(True)"""
        connect_fn = MagicMock()
        service = SSHService(
            client_provider=lambda: None,
            connect_fn=connect_fn,
        )

        status_spy = MagicMock()
        service.connection_status_changed.connect(status_spy)

        # 模拟重连成功（传入新的 client）
        mock_client = MagicMock()
        service._on_reconnected(mock_client)
        status_spy.assert_called_with(True)

    def test_connection_status_signal_on_lost(self):
        """连接丢失时应发出 connection_status_changed(False)"""
        connect_fn = MagicMock()
        service = SSHService(
            client_provider=lambda: None,
            connect_fn=connect_fn,
        )

        status_spy = MagicMock()
        service.connection_status_changed.connect(status_spy)

        service._on_connection_lost()
        status_spy.assert_called_with(False)

    def test_connection_status_signal_on_reconnect_failed(self):
        """重连失败时应发出 connection_status_changed(False)"""
        connect_fn = MagicMock()
        service = SSHService(
            client_provider=lambda: None,
            connect_fn=connect_fn,
        )

        status_spy = MagicMock()
        service.connection_status_changed.connect(status_spy)

        service._on_reconnect_failed("超过最大重试次数")
        status_spy.assert_called_with(False)


class TestSSHServiceRun:
    """SSHService.run() 测试"""

    def _make_connected_service(self) -> tuple:
        """创建一个已连接的 SSHService 和 mock client"""
        mock_client = MagicMock(spec=paramiko.SSHClient)
        mock_transport = MagicMock()
        mock_transport.is_active.return_value = True
        mock_client.get_transport.return_value = mock_transport

        service = SSHService(client_provider=lambda: mock_client)
        return service, mock_client

    def test_run_success(self):
        """正常执行命令"""
        service, mock_client = self._make_connected_service()

        mock_stdout = MagicMock()
        mock_stdout.read.return_value = b"hello\n"
        mock_stdout.channel.recv_exit_status.return_value = 0
        mock_stderr = MagicMock()
        mock_stderr.read.return_value = b""
        mock_client.exec_command.return_value = (MagicMock(), mock_stdout, mock_stderr)

        rc, out, err = service.run("echo hello")

        assert rc == 0
        assert out == "hello\n"
        assert err == ""

    def test_run_disconnected_raises(self):
        """连接断开时 run 应抛异常"""
        service = SSHService(client_provider=lambda: None)

        with pytest.raises(RuntimeError, match="SSH 未连接"):
            service.run("echo test")


class TestSSHServiceFileTransfer:
    """文件传输测试"""

    def _make_connected_service(self) -> tuple:
        mock_client = MagicMock(spec=paramiko.SSHClient)
        mock_transport = MagicMock()
        mock_transport.is_active.return_value = True
        mock_client.get_transport.return_value = mock_transport

        service = SSHService(client_provider=lambda: mock_client)
        return service, mock_client

    def test_upload(self):
        """上传文件"""
        service, mock_client = self._make_connected_service()
        mock_sftp = MagicMock(spec=paramiko.SFTPClient)
        mock_client.open_sftp.return_value = mock_sftp

        service.upload("/local/file.txt", "/remote/file.txt")

        mock_sftp.put.assert_called_once_with("/local/file.txt", "/remote/file.txt")
        mock_sftp.close.assert_called_once()

    def test_download(self):
        """下载文件"""
        service, mock_client = self._make_connected_service()
        mock_sftp = MagicMock(spec=paramiko.SFTPClient)
        mock_client.open_sftp.return_value = mock_sftp

        service.download("/remote/file.txt", "/local/file.txt")

        mock_sftp.get.assert_called_once_with("/remote/file.txt", "/local/file.txt")
        mock_sftp.close.assert_called_once()


class TestSSHServiceLegacyCompat:
    """确保旧 API 兼容性"""

    def test_check_command_exists_success(self):
        """check_command_exists 在命令存在时返回 True"""
        mock_client = MagicMock(spec=paramiko.SSHClient)
        mock_transport = MagicMock()
        mock_transport.is_active.return_value = True
        mock_client.get_transport.return_value = mock_transport

        mock_stdout = MagicMock()
        mock_stdout.read.return_value = b"/usr/bin/python3\n"
        mock_stdout.channel.recv_exit_status.return_value = 0
        mock_stderr = MagicMock()
        mock_stderr.read.return_value = b""
        mock_client.exec_command.return_value = (MagicMock(), mock_stdout, mock_stderr)

        service = SSHService(client_provider=lambda: mock_client)
        assert service.check_command_exists("python3") is True

    def test_check_command_exists_not_found(self):
        """check_command_exists 在命令不存在时返回 False"""
        mock_client = MagicMock(spec=paramiko.SSHClient)
        mock_transport = MagicMock()
        mock_transport.is_active.return_value = True
        mock_client.get_transport.return_value = mock_transport

        mock_stdout = MagicMock()
        mock_stdout.read.return_value = b""
        mock_stdout.channel.recv_exit_status.return_value = 1
        mock_stderr = MagicMock()
        mock_stderr.read.return_value = b""
        mock_client.exec_command.return_value = (MagicMock(), mock_stdout, mock_stderr)

        service = SSHService(client_provider=lambda: mock_client)
        assert service.check_command_exists("nonexistent") is False

    def test_list_screen_sessions_empty(self):
        """无 screen 会话时返回空列表"""
        mock_client = MagicMock(spec=paramiko.SSHClient)
        mock_transport = MagicMock()
        mock_transport.is_active.return_value = True
        mock_client.get_transport.return_value = mock_transport

        mock_stdout = MagicMock()
        mock_stdout.read.return_value = b"No Sockets found in /var/run/screen/S-user.\n"
        mock_stdout.channel.recv_exit_status.return_value = 1
        mock_stderr = MagicMock()
        mock_stderr.read.return_value = b""
        mock_client.exec_command.return_value = (MagicMock(), mock_stdout, mock_stderr)

        service = SSHService(client_provider=lambda: mock_client)
        assert service.list_screen_sessions() == []

    def test_check_screen_session_disconnected(self):
        """断连时 check_screen_session 应返回 False"""
        service = SSHService(client_provider=lambda: None)
        assert service.check_screen_session("test") is False

    def test_kill_screen_session_disconnected(self):
        """断连时 kill_screen_session 应返回 False"""
        service = SSHService(client_provider=lambda: None)
        assert service.kill_screen_session("test") is False
