"""RetryManager 单元测试"""
from unittest.mock import MagicMock

import pytest

from core.execution.retry_manager import (
    RetryManager,
    TRANSIENT_ERRORS,
    MAX_AUTO_RETRY,
)


class TestTransientErrorDetection:
    """瞬时错误识别测试"""

    def test_ssh_error_is_transient(self):
        """SSH 相关错误应被识别为瞬时错误"""
        rm = RetryManager()
        assert rm._is_transient("SSH connection refused") is True

    def test_timeout_error_is_transient(self):
        """超时错误应被识别为瞬时错误"""
        rm = RetryManager()
        assert rm._is_transient("Connection timed out after 30s") is True

    def test_connection_error_is_transient(self):
        """连接错误应被识别为瞬时错误"""
        rm = RetryManager()
        assert rm._is_transient("Connection reset by peer") is True

    def test_network_error_is_transient(self):
        """网络错误应被识别为瞬时错误"""
        rm = RetryManager()
        assert rm._is_transient("Network is unreachable") is True

    def test_broken_pipe_is_transient(self):
        """Broken pipe 应被识别为瞬时错误"""
        rm = RetryManager()
        assert rm._is_transient("Broken pipe") is True

    def test_transport_error_is_transient(self):
        """Transport 错误应被识别为瞬时错误"""
        rm = RetryManager()
        assert rm._is_transient("Transport not available") is True

    def test_socket_error_is_transient(self):
        """Socket 错误应被识别为瞬时错误"""
        rm = RetryManager()
        assert rm._is_transient("Socket error: connection refused") is True

    def test_case_insensitive(self):
        """错误匹配应不区分大小写"""
        rm = RetryManager()
        assert rm._is_transient("SSH CONNECTION LOST") is True

    def test_permanent_error_not_transient(self):
        """永久错误不应被识别为瞬时错误"""
        rm = RetryManager()
        assert rm._is_transient("File not found: /data/sample.fq") is False
        assert rm._is_transient("Invalid parameter: quality=-1") is False
        assert rm._is_transient("Command not found: fastp") is False

    def test_empty_error_not_transient(self):
        """空错误消息不应被识别为瞬时错误"""
        rm = RetryManager()
        assert rm._is_transient("") is False


class TestOnTaskFailed:
    """on_task_failed() 测试"""

    def test_transient_first_failure_auto_retries(self):
        """瞬时错误首次失败应自动重试"""
        callback = MagicMock()
        rm = RetryManager(retry_callback=callback)

        result = rm.on_task_failed("exec_001", "SSH connection lost")

        assert result == "auto_retry"
        callback.assert_called_once_with("exec_001")

    def test_transient_second_failure_auto_retries(self):
        """瞬时错误第二次失败应自动重试"""
        callback = MagicMock()
        rm = RetryManager(retry_callback=callback)

        rm.on_task_failed("exec_001", "SSH timeout")
        rm.on_task_failed("exec_001", "SSH timeout")

        assert callback.call_count == 2
        assert rm.get_retry_count("exec_001") == 2

    def test_transient_exceeds_max_retry(self):
        """瞬时错误超过最大重试次数应返回 manual_required"""
        callback = MagicMock()
        rm = RetryManager(retry_callback=callback)

        # 重试 MAX_AUTO_RETRY 次
        for _ in range(MAX_AUTO_RETRY):
            rm.on_task_failed("exec_001", "SSH timeout")

        # 再次失败应返回 manual_required
        result = rm.on_task_failed("exec_001", "SSH timeout")

        assert result == "manual_required"
        assert callback.call_count == MAX_AUTO_RETRY  # 第 3 次不调用

    def test_permanent_error_manual_required(self):
        """永久错误应直接返回 manual_required"""
        callback = MagicMock()
        rm = RetryManager(retry_callback=callback)

        result = rm.on_task_failed("exec_001", "File not found")

        assert result == "manual_required"
        callback.assert_not_called()

    def test_retry_scheduled_signal(self):
        """自动重试时应发出 retry_scheduled 信号"""
        rm = RetryManager(retry_callback=MagicMock())
        spy = MagicMock()
        rm.retry_scheduled.connect(spy)

        rm.on_task_failed("exec_001", "Connection timeout")
        spy.assert_called_once_with("exec_001")

    def test_retry_exhausted_signal_on_max_retry(self):
        """重试用尽时应发出 retry_exhausted 信号"""
        rm = RetryManager(retry_callback=MagicMock())
        spy = MagicMock()
        rm.retry_exhausted.connect(spy)

        for _ in range(MAX_AUTO_RETRY):
            rm.on_task_failed("exec_001", "SSH error")

        rm.on_task_failed("exec_001", "SSH error again")
        spy.assert_called_once_with("exec_001", "SSH error again")

    def test_retry_exhausted_signal_on_permanent(self):
        """永久错误应发出 retry_exhausted 信号"""
        rm = RetryManager()
        spy = MagicMock()
        rm.retry_exhausted.connect(spy)

        rm.on_task_failed("exec_001", "Invalid parameters")
        spy.assert_called_once_with("exec_001", "Invalid parameters")

    def test_no_callback_still_works(self):
        """无回调时不应崩溃"""
        rm = RetryManager()  # 无回调
        result = rm.on_task_failed("exec_001", "SSH error")
        assert result == "auto_retry"

    def test_independent_retry_counts(self):
        """不同任务的重试计数应独立"""
        callback = MagicMock()
        rm = RetryManager(retry_callback=callback)

        rm.on_task_failed("exec_001", "SSH error")
        rm.on_task_failed("exec_001", "SSH error")
        rm.on_task_failed("exec_002", "Timeout error")

        assert rm.get_retry_count("exec_001") == 2
        assert rm.get_retry_count("exec_002") == 1


class TestManualRetry:
    """manual_retry() 测试"""

    def test_resets_retry_count(self):
        """手动重试应重置重试计数"""
        callback = MagicMock()
        rm = RetryManager(retry_callback=callback)

        # 用完自动重试
        for _ in range(MAX_AUTO_RETRY):
            rm.on_task_failed("exec_001", "SSH error")

        assert rm.get_retry_count("exec_001") == MAX_AUTO_RETRY

        # 手动重试
        rm.manual_retry("exec_001")
        assert rm.get_retry_count("exec_001") == 0
        assert callback.call_count == MAX_AUTO_RETRY + 1  # 包括手动重试

    def test_manual_retry_emits_signal(self):
        """手动重试应发出 retry_scheduled 信号"""
        rm = RetryManager(retry_callback=MagicMock())
        spy = MagicMock()
        rm.retry_scheduled.connect(spy)

        rm.manual_retry("exec_001")
        spy.assert_called_once_with("exec_001")

    def test_manual_retry_allows_auto_retry_again(self):
        """手动重试后应重新允许自动重试"""
        callback = MagicMock()
        rm = RetryManager(retry_callback=callback)

        # 用完自动重试
        for _ in range(MAX_AUTO_RETRY):
            rm.on_task_failed("exec_001", "SSH error")

        # 超出时返回 manual
        result = rm.on_task_failed("exec_001", "SSH error")
        assert result == "manual_required"

        # 手动重试重置后可再次自动重试
        rm.manual_retry("exec_001")
        result = rm.on_task_failed("exec_001", "SSH error")
        assert result == "auto_retry"

    def test_manual_retry_no_callback_no_crash(self):
        """无回调时手动重试不应崩溃"""
        rm = RetryManager()
        rm.manual_retry("exec_001")  # 不应抛异常


class TestGetRetryCount:
    """get_retry_count() 测试"""

    def test_unknown_task_returns_zero(self):
        """未知任务返回 0"""
        rm = RetryManager()
        assert rm.get_retry_count("unknown") == 0

    def test_tracks_count_correctly(self):
        """正确跟踪重试次数"""
        rm = RetryManager(retry_callback=MagicMock())
        rm.on_task_failed("exec_001", "SSH error")
        assert rm.get_retry_count("exec_001") == 1

        rm.on_task_failed("exec_001", "SSH error")
        assert rm.get_retry_count("exec_001") == 2


class TestConstants:
    """常量测试"""

    def test_max_auto_retry_is_2(self):
        """最大自动重试次数应为 2"""
        assert MAX_AUTO_RETRY == 2

    def test_transient_errors_list(self):
        """瞬时错误关键词列表应包含预期项"""
        assert "ssh" in TRANSIENT_ERRORS
        assert "timeout" in TRANSIENT_ERRORS
        assert "connection" in TRANSIENT_ERRORS


class TestCallbackError:
    """回调异常处理测试"""

    def test_callback_error_does_not_crash(self):
        """回调抛异常不应阻塞 RetryManager"""
        def bad_callback(eid):
            raise ValueError("回调出错")

        rm = RetryManager(retry_callback=bad_callback)
        result = rm.on_task_failed("exec_001", "SSH error")

        # 仍然返回正确结果
        assert result == "auto_retry"
