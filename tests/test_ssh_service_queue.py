from __future__ import annotations

import threading
import time

from core.remote.ssh_service import SSHService


class _FakeClient:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _FakeTerminalChannel:
    def __init__(self, payloads: list[bytes] | None = None):
        self._payloads = list(payloads or [])
        self.closed = False
        self.sent: list[str] = []
        self.resizes: list[tuple[int, int]] = []

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

    def settimeout(self, _timeout: float):
        return None

    def get_pty(self, term: str = "xterm-256color", width: int = 120, height: int = 28):
        assert term == "xterm-256color"
        assert width >= 40
        assert height >= 12

    def invoke_shell(self):
        return self

    def exit_status_ready(self):
        return self.closed and not self._payloads

    def send(self, data: str):
        self.sent.append(data)
        return len(data)

    def resize_pty(self, width: int, height: int):
        self.resizes.append((width, height))

    def close(self):
        self.closed = True


class _FakeShellClient:
    def __init__(self, channel: _FakeTerminalChannel):
        self._transport = _FakeTransport(channel)

    def get_transport(self):
        return self._transport


class _FakeInteractiveChannel(_FakeTerminalChannel):
    def __init__(self):
        super().__init__([])
        self._buffer = ""

    def get_pty(self, term: str = "xterm-256color", width: int = 120, height: int = 28):
        assert term == "xterm-256color"
        assert width == 120
        assert height == 28

    def invoke_shell(self):
        return self

    def settimeout(self, _timeout: float):
        return None

    def send(self, data: str):
        self.sent.append(data)
        self._buffer += data
        begin_match = None
        rc_match = None
        end_match = None
        import re

        begin_match = re.search(r"printf '%s\\n' '(__OMX_BEGIN_[^']+__)'", data)
        rc_match = re.search(r"printf '%s%s\\n' '(__OMX_RC_[^']+__)'", data)
        end_match = re.search(r"printf '%s\\n' '(__OMX_END_[^']+__)'", data)
        if begin_match and rc_match and end_match:
            payload = (
                f"{begin_match.group(1)}\n"
                "hello from interactive shell\n"
                f"{rc_match.group(1)}0\n"
                f"{end_match.group(1)}\n"
            )
            self._payloads.append(payload.encode("utf-8"))
        return len(data)


class _FakeTransport:
    def __init__(self, channel):
        self._channel = channel

    def is_active(self):
        return True

    def open_session(self, timeout: int = 10):
        assert timeout == 10
        return self._channel


class _FakeInteractiveClient:
    def __init__(self, channel):
        self._transport = _FakeTransport(channel)

    def get_transport(self):
        return self._transport


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
        def __init__(self):
            self._stdout_pending = True
            self._stderr_pending = True

        def recv_ready(self):
            return self._stdout_pending

        def recv(self, _size: int):
            self._stdout_pending = False
            calls.append("stdout")
            return b"ok"

        def recv_stderr_ready(self):
            return self._stderr_pending

        def recv_stderr(self, _size: int):
            self._stderr_pending = False
            calls.append("stderr")
            return b""

        def exit_status_ready(self):
            return not self._stdout_pending and not self._stderr_pending

        def recv_exit_status(self):
            calls.append("exit")
            assert calls == ["stdout", "stderr", "exit"]
            return 0

    class _FakeStream:
        def __init__(self, name: str, payload: str):
            self._name = name
            self._payload = payload
            self.channel = _FakeChannel()

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
    session.resize(cols=132, rows=36)
    snapshot = session.snapshot(cursor=0)
    waited, version = session.wait_for_update(cursor=len("hello\\nworld\\n"), version=-1, timeout=0.0)

    session.close(message="done", connected=False)
    service.close()

    assert snapshot["output"] == "hello\\nworld\\n"
    assert snapshot["connected"] is True
    assert snapshot["input_enabled"] is True
    assert channel.sent == ["pwd\\n"]
    assert channel.resizes == [(132, 36)]
    assert waited["cursor"] == len("hello\\nworld\\n")
    assert version >= 1


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


def test_run_interactive_executes_via_invoke_shell_and_parses_markers() -> None:
    channel = _FakeInteractiveChannel()
    service = SSHService(initial_client=_FakeClient())
    service._ensure_connection = lambda: _FakeInteractiveClient(channel)  # type: ignore[method-assign]

    rc, out, err = service.run_interactive("echo hello", timeout=5)
    service.close()

    assert rc == 0
    assert "hello from interactive shell" in out
    assert err == ""
    assert any("stty -echo" in sent for sent in channel.sent)
