"""JobQueue 单元测试"""
from unittest.mock import MagicMock

import pytest

from core.execution.job_queue import JobQueue, QueuedJob


class TestJobQueueInit:
    """初始化测试"""

    def test_initial_status(self):
        """初始状态为空"""
        queue = JobQueue()
        status = queue.get_status()
        assert status == {"running": 0, "pending": 0}


class TestJobQueueSubmit:
    """submit() 测试"""

    def test_submit_starts_immediately(self):
        """任务提交后立即执行"""
        queue = JobQueue()
        result = queue.submit("exec_001", "echo hello")
        assert result == "started"
        assert queue.get_status()["running"] == 1

    def test_submit_emits_job_started(self):
        """提交任务应发出 job_started 信号"""
        queue = JobQueue()
        spy = MagicMock()
        queue.job_started.connect(spy)

        queue.submit("exec_001", "cmd1")
        spy.assert_called_once_with("exec_001")

    def test_submit_calls_callback_on_start(self):
        """提交任务应调用 callback_on_start"""
        queue = JobQueue()
        callback = MagicMock()

        queue.submit("exec_001", "cmd1", callback_on_start=callback)
        callback.assert_called_once_with("exec_001")

    def test_submit_multiple_tasks(self):
        """提交多个任务都应立即执行"""
        queue = JobQueue()
        queue.submit("exec_001", "cmd1")
        queue.submit("exec_002", "cmd2")
        queue.submit("exec_003", "cmd3")

        status = queue.get_status()
        assert status["running"] == 3
        assert status["pending"] == 0

    def test_submit_with_metadata(self):
        """提交任务携带 metadata"""
        queue = JobQueue()
        result = queue.submit("exec_001", "cmd1", metadata={"tool": "fastp"})
        assert result == "started"


class TestJobQueueOnJobFinished:
    """on_job_finished() 测试"""

    def test_finish_removes_from_running(self):
        """完成任务应从运行列表移除"""
        queue = JobQueue()
        queue.submit("exec_001", "cmd1")
        queue.on_job_finished("exec_001")

        status = queue.get_status()
        assert status["running"] == 0

    def test_finish_all_emits_queue_empty(self):
        """所有任务完成后应发出 queue_empty 信号"""
        queue = JobQueue()
        queue.submit("exec_001", "cmd1")

        spy = MagicMock()
        queue.queue_empty.connect(spy)

        queue.on_job_finished("exec_001")
        spy.assert_called_once()

    def test_finish_unknown_job_no_crash(self):
        """通知未知任务完成不应崩溃"""
        queue = JobQueue()
        queue.on_job_finished("nonexistent")  # 不应抛异常


class TestJobQueueCallbackError:
    """回调异常处理测试"""

    def test_callback_error_does_not_crash(self):
        """callback 抛异常不应阻塞队列"""
        queue = JobQueue()

        def bad_callback(eid):
            raise ValueError("回调出错")

        # 不应抛异常
        queue.submit("exec_001", "cmd1", callback_on_start=bad_callback)

        # 任务仍然被标记为运行中
        assert queue.get_status()["running"] == 1