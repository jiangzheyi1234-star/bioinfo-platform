from __future__ import annotations

import threading
import time

from core.remote.ssh_service import SSHService


class _FakeClient:
    pass


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
