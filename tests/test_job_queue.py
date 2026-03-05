"""JobQueue 单元测试"""
from unittest.mock import MagicMock

import pytest

from core.job_queue import JobQueue, QueuedJob


class TestJobQueueInit:
    """初始化测试"""

    def test_default_max_concurrent(self):
        """默认最大并发数为 3"""
        queue = JobQueue()
        assert queue.max_concurrent == 3

    def test_custom_max_concurrent(self):
        """自定义最大并发数"""
        queue = JobQueue(max_concurrent=5)
        assert queue.max_concurrent == 5

    def test_initial_status(self):
        """初始状态为空"""
        queue = JobQueue()
        status = queue.get_status()
        assert status == {"running": 0, "pending": 0, "max": 3}


class TestJobQueueSubmit:
    """submit() 测试"""

    def test_submit_within_limit_starts_immediately(self):
        """并发数未满时应立即执行"""
        queue = JobQueue(max_concurrent=2)
        result = queue.submit("exec_001", "echo hello")
        assert result == "started"
        assert queue.get_status()["running"] == 1

    def test_submit_at_limit_queues(self):
        """达到并发上限时应排队"""
        queue = JobQueue(max_concurrent=1)
        queue.submit("exec_001", "cmd1")
        result = queue.submit("exec_002", "cmd2")
        assert result == "queued"
        assert queue.get_status()["running"] == 1
        assert queue.get_status()["pending"] == 1

    def test_submit_emits_job_started(self):
        """立即执行时应发出 job_started 信号"""
        queue = JobQueue(max_concurrent=2)
        spy = MagicMock()
        queue.job_started.connect(spy)

        queue.submit("exec_001", "cmd1")
        spy.assert_called_once_with("exec_001")

    def test_submit_queued_emits_queue_updated(self):
        """排队时应发出 queue_updated 信号"""
        queue = JobQueue(max_concurrent=1)
        queue.submit("exec_001", "cmd1")

        spy = MagicMock()
        queue.queue_updated.connect(spy)

        queue.submit("exec_002", "cmd2")
        spy.assert_called_with(1)

    def test_submit_calls_callback_on_start(self):
        """立即执行时应调用 callback_on_start"""
        queue = JobQueue(max_concurrent=2)
        callback = MagicMock()

        queue.submit("exec_001", "cmd1", callback_on_start=callback)
        callback.assert_called_once_with("exec_001")

    def test_submit_queued_does_not_call_callback(self):
        """排队时不应调用 callback_on_start"""
        queue = JobQueue(max_concurrent=1)
        queue.submit("exec_001", "cmd1")

        callback = MagicMock()
        queue.submit("exec_002", "cmd2", callback_on_start=callback)
        callback.assert_not_called()

    def test_submit_multiple_fills_queue(self):
        """提交多个任务验证状态正确"""
        queue = JobQueue(max_concurrent=2)
        queue.submit("exec_001", "cmd1")
        queue.submit("exec_002", "cmd2")
        queue.submit("exec_003", "cmd3")
        queue.submit("exec_004", "cmd4")

        status = queue.get_status()
        assert status["running"] == 2
        assert status["pending"] == 2

    def test_submit_with_metadata(self):
        """提交任务携带 metadata"""
        queue = JobQueue(max_concurrent=2)
        result = queue.submit("exec_001", "cmd1", metadata={"tool": "fastp"})
        assert result == "started"


class TestJobQueueOnJobFinished:
    """on_job_finished() 测试"""

    def test_finish_starts_next_pending(self):
        """完成任务后应启动下一个排队任务"""
        queue = JobQueue(max_concurrent=1)
        queue.submit("exec_001", "cmd1")
        queue.submit("exec_002", "cmd2")

        spy = MagicMock()
        queue.job_started.connect(spy)

        queue.on_job_finished("exec_001")

        spy.assert_called_with("exec_002")
        status = queue.get_status()
        assert status["running"] == 1
        assert status["pending"] == 0

    def test_finish_all_emits_queue_empty(self):
        """所有任务完成后应发出 queue_empty 信号"""
        queue = JobQueue(max_concurrent=2)
        queue.submit("exec_001", "cmd1")

        spy = MagicMock()
        queue.queue_empty.connect(spy)

        queue.on_job_finished("exec_001")
        spy.assert_called_once()

    def test_finish_unknown_job_no_crash(self):
        """通知未知任务完成不应崩溃"""
        queue = JobQueue(max_concurrent=2)
        queue.on_job_finished("nonexistent")  # 不应抛异常

    def test_finish_starts_pending_with_callback(self):
        """排队任务开始时应调用其 callback"""
        queue = JobQueue(max_concurrent=1)
        queue.submit("exec_001", "cmd1")

        callback = MagicMock()
        queue.submit("exec_002", "cmd2", callback_on_start=callback)

        queue.on_job_finished("exec_001")
        callback.assert_called_once_with("exec_002")

    def test_fifo_order(self):
        """排队任务应按 FIFO 顺序启动"""
        queue = JobQueue(max_concurrent=1)
        queue.submit("exec_001", "cmd1")
        queue.submit("exec_002", "cmd2")
        queue.submit("exec_003", "cmd3")

        started = []
        queue.job_started.connect(lambda eid: started.append(eid))

        queue.on_job_finished("exec_001")
        queue.on_job_finished("exec_002")

        assert started == ["exec_002", "exec_003"]

    def test_finish_emits_queue_updated(self):
        """从队列启动任务时应发出 queue_updated"""
        queue = JobQueue(max_concurrent=1)
        queue.submit("exec_001", "cmd1")
        queue.submit("exec_002", "cmd2")
        queue.submit("exec_003", "cmd3")

        spy = MagicMock()
        queue.queue_updated.connect(spy)

        queue.on_job_finished("exec_001")
        # 从 pending=2 → pending=1
        spy.assert_called_with(1)


class TestJobQueueUpdateMaxConcurrent:
    """update_max_concurrent() 测试"""

    def test_increase_starts_pending(self):
        """增大并发数应立即启动排队任务"""
        queue = JobQueue(max_concurrent=1)
        queue.submit("exec_001", "cmd1")
        queue.submit("exec_002", "cmd2")
        queue.submit("exec_003", "cmd3")

        spy = MagicMock()
        queue.job_started.connect(spy)

        queue.update_max_concurrent(3)

        # exec_002 和 exec_003 应该被启动
        assert spy.call_count == 2
        status = queue.get_status()
        assert status["running"] == 3
        assert status["pending"] == 0

    def test_decrease_no_kill(self):
        """减小并发数不应终止已运行的任务"""
        queue = JobQueue(max_concurrent=3)
        queue.submit("exec_001", "cmd1")
        queue.submit("exec_002", "cmd2")
        queue.submit("exec_003", "cmd3")

        queue.update_max_concurrent(1)

        status = queue.get_status()
        assert status["running"] == 3  # 已运行的不受影响
        assert status["max"] == 1

    def test_set_below_one_ignored(self):
        """设置小于 1 的值应被忽略"""
        queue = JobQueue(max_concurrent=3)
        queue.update_max_concurrent(0)
        assert queue.max_concurrent == 3

        queue.update_max_concurrent(-1)
        assert queue.max_concurrent == 3

    def test_same_value_no_change(self):
        """设置相同值不应触发多余操作"""
        queue = JobQueue(max_concurrent=3)
        queue.update_max_concurrent(3)
        assert queue.max_concurrent == 3


class TestJobQueueCallbackError:
    """回调异常处理测试"""

    def test_callback_error_does_not_crash(self):
        """callback 抛异常不应阻塞队列"""
        queue = JobQueue(max_concurrent=2)

        def bad_callback(eid):
            raise ValueError("回调出错")

        # 不应抛异常
        queue.submit("exec_001", "cmd1", callback_on_start=bad_callback)

        # 任务仍然被标记为运行中
        assert queue.get_status()["running"] == 1
