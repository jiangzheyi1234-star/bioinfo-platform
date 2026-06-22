from __future__ import annotations

import signal

import pytest


def test_process_runner_terminates_process_group_when_cancelled(monkeypatch) -> None:
    from apps.remote_runner import process_runner

    kill_calls: list[tuple[int, int]] = []
    popen_kwargs: list[dict[str, object]] = []
    process_ref: dict[str, FakeProcess] = {}

    class FakeProcess:
        pid = 4242
        returncode: int | None = None
        poll_count = 0

        def poll(self) -> int | None:
            self.poll_count += 1
            return self.returncode

        def communicate(self, timeout: float | None = None) -> tuple[str, str]:
            return "stdout", "stderr"

    def fake_popen(command, **kwargs):
        popen_kwargs.append(dict(kwargs))
        process = FakeProcess()
        process_ref["process"] = process
        return process

    def fake_killpg(pid: int, sig: int) -> None:
        kill_calls.append((pid, sig))
        process_ref["process"].returncode = -sig

    monkeypatch.setattr(process_runner.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(process_runner.os, "name", "posix")
    monkeypatch.setattr(process_runner.os, "killpg", fake_killpg, raising=False)

    result = process_runner.run_process(
        ["snakemake"],
        env={"PATH": "/tmp/bin"},
        should_cancel=lambda: process_ref.get("process") is not None
        and process_ref["process"].poll_count > 0,
        poll_interval_seconds=0,
    )

    assert popen_kwargs[0]["start_new_session"] is True
    assert kill_calls == [(4242, signal.SIGTERM)]
    assert result.returncode == -signal.SIGTERM
    assert result.stdout == "stdout"
    assert "stderr" in result.stderr
    assert "terminated after stale lease" in result.stderr


def test_process_runner_terminates_process_group_when_poll_callback_fails(monkeypatch) -> None:
    from apps.remote_runner import process_runner

    kill_calls: list[tuple[int, int]] = []
    process_ref: dict[str, FakeProcess] = {}

    class FakeProcess:
        pid = 5252
        returncode: int | None = None

        def poll(self) -> int | None:
            return self.returncode

        def communicate(self, timeout: float | None = None) -> tuple[str, str]:
            return "", ""

    def fake_popen(command, **kwargs):
        process = FakeProcess()
        process_ref["process"] = process
        return process

    def fake_killpg(pid: int, sig: int) -> None:
        kill_calls.append((pid, sig))
        process_ref["process"].returncode = -sig

    monkeypatch.setattr(process_runner.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(process_runner.os, "name", "posix")
    monkeypatch.setattr(process_runner.os, "killpg", fake_killpg, raising=False)

    with pytest.raises(RuntimeError, match="poll failed"):
        process_runner.run_process(
            ["snakemake"],
            env={"PATH": "/tmp/bin"},
            on_poll=lambda: (_ for _ in ()).throw(RuntimeError("poll failed")),
            poll_interval_seconds=0,
        )

    assert kill_calls == [(5252, signal.SIGTERM)]
