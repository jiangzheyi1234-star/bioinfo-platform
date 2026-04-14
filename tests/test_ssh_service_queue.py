from __future__ import annotations

import threading
import time

from core.remote.ssh_service import SSHService


class _FakeClient:
    pass


class _FakeTerminalChannel:
    def __init__(self, payloads: list[bytes] | None = None):
        self._payloads = list(payloads or [])
        self.closed = False
        self.sent: list[str] = []

    def recv_ready(self):
        return bool(self._payloads)

    def recv(self, _size: int):
        if self._payloads:
            return self._payloads.pop(0)
        return b""

    def recv_stderr_ready(self):
        return False

    def recv_stderr(self, _size: int):
        return b""

    def exit_status_ready(self):
        return self.closed and not self._payloads

    def send(self, data: str):
        self.sent.append(data)
        return len(data)

    def close(self):
        self.closed = True


class _FakeShellClient:
    def __init__(self, channel: _FakeTerminalChannel):
        self._channel = channel

    def invoke_shell(self, width: int = 120, height: int = 28):
        assert width == 120
        assert height == 28
        return self._channel


def test_ssh_service_run_is_serialized() -> None:
    service = SSHService(initial_client=_FakeClient())
    lock = threading.Lock()
    max_active = 0
    active = 0
    seen: list[str] = []

    def fake_exec(cmd: str, timeout: int):
        nonlocal active, max_active
        with lock:
            active += 1
            if active > max_active:
                max_active = active
        time.sleep(0.01)
        seen.append(cmd)
        with lock:
            active -= 1
        return (0, cmd, "")

    service._execute_command = fake_exec  # type: ignore[method-assign]

    threads = []
    for i in range(20):
        t = threading.Thread(target=lambda x=i: service.run(f"cmd_{x}", timeout=5))
        t.start()
        threads.append(t)
    for t in threads:
        t.join()

    service.close()
    assert len(seen) == 20
    assert max_active == 1


def test_ssh_service_priority_preemption() -> None:
    service = SSHService(initial_client=_FakeClient())
    executed: list[str] = []

    def fake_exec(cmd: str, timeout: int):
        executed.append(cmd)
        time.sleep(0.03)
        return (0, cmd, "")

    service._execute_command = fake_exec  # type: ignore[method-assign]

    t1 = threading.Thread(target=lambda: service.run("cat /tmp/status.txt", timeout=5))
    t2 = threading.Thread(target=lambda: service.run("cat /tmp/status.txt", timeout=5))
    t3 = threading.Thread(target=lambda: service.run("test -d /tmp", timeout=5))

    t1.start()
    time.sleep(0.005)
    t2.start()
    time.sleep(0.005)
    t3.start()
    t1.join()
    t2.join()
    t3.join()

    service.close()
    assert executed[:3] == ["cat /tmp/status.txt", "test -d /tmp", "cat /tmp/status.txt"]


def test_execute_command_reads_streams_before_exit_status() -> None:
    calls: list[str] = []

    class _FakeChannel:
        def recv_exit_status(self):
            calls.append("exit")
            assert calls == ["stdout", "stderr", "exit"]
            return 0

    class _FakeStream:
        def __init__(self, name: str, payload: str):
            self._name = name
            self._payload = payload
            self.channel = _FakeChannel()

        def read(self):
            calls.append(self._name)
            return self._payload.encode("utf-8")

    class _FakeExecClient:
        def exec_command(self, cmd: str, timeout: int = 10):
            return None, _FakeStream("stdout", "ok"), _FakeStream("stderr", "")

    service = SSHService(initial_client=_FakeClient())
    service._ensure_connection = lambda: _FakeExecClient()  # type: ignore[method-assign]

    rc, out, err = service._execute_command("echo test", 5)
    service.close()

    assert rc == 0
    assert out == "ok"
    assert err == ""


def test_open_terminal_session_reads_output_and_accepts_input() -> None:
    channel = _FakeTerminalChannel([b"hello\\n", b"world\\n"])
    service = SSHService(initial_client=_FakeClient())
    service._ensure_connection = lambda: _FakeShellClient(channel)  # type: ignore[method-assign]

    session = service.open_terminal_session(cols=120, rows=28)
    time.sleep(0.2)
    session.send("pwd\\n")
    snapshot = session.snapshot(cursor=0)

    session.close(message="done", connected=False)
    service.close()

    assert snapshot["output"] == "hello\\nworld\\n"
    assert snapshot["connected"] is True
    assert snapshot["input_enabled"] is True
    assert channel.sent == ["pwd\\n"]


def test_terminal_session_close_marks_history_but_disables_input() -> None:
    channel = _FakeTerminalChannel([b"prompt$ "])
    service = SSHService(initial_client=_FakeClient())
    service._ensure_connection = lambda: _FakeShellClient(channel)  # type: ignore[method-assign]

    session = service.open_terminal_session()
    time.sleep(0.1)
    session.close(message="SSH 已断开，终端会话已结束", connected=False)
    snapshot = session.snapshot(cursor=0)
    service.close()

    assert "prompt$ " in snapshot["output"]
    assert snapshot["closed"] is True
    assert snapshot["connected"] is False
    assert snapshot["input_enabled"] is False
    assert snapshot["message"] == "SSH 已断开，终端会话已结束"
