from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from apps.remote_runner import run as remote_run
from apps.remote_runner.process_lifetime_lock import (
    RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE,
    RunnerProcessLifetimeLockError,
)
from core.contracts.runner_process_lifetime import (
    RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE_EXIT_STATUS,
)


def _config():
    return SimpleNamespace(
        bind_host="127.0.0.1",
        bind_port=0,
        release_dir="/release/remote_runner",
        runtime_state_path="/shared/runtime/runner-state.json",
    )


def test_runner_cli_maps_adopt_failure_and_cleans_diagnostic_pid(
    monkeypatch,
    capsys,
) -> None:
    cfg = _config()
    lock_error = RunnerProcessLifetimeLockError(
        reason_code=RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE,
        path=Path("/shared/runtime/runner.lock"),
    )
    monkeypatch.setattr(
        remote_run,
        "load_remote_runner_config_from_startup_preflight",
        lambda: cfg,
    )
    monkeypatch.setattr(
        remote_run,
        "adopt_runner_process_lifetime_lock",
        lambda _cfg: (_ for _ in ()).throw(lock_error),
    )
    monkeypatch.setattr(
        remote_run,
        "remove_runner_pid_file_if_owned",
        lambda _cfg: cleanup_events.append("pid_cleanup"),
    )
    monkeypatch.setattr(
        remote_run.socket,
        "socket",
        lambda *_args, **_kwargs: pytest.fail("socket mutation must not run"),
    )

    cleanup_events: list[str] = []

    assert remote_run.cli_main() == RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE_EXIT_STATUS
    assert cleanup_events == ["pid_cleanup"]
    assert RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE in capsys.readouterr().err


def test_runner_cli_preserves_lock_error_when_pid_cleanup_fails(
    monkeypatch,
    capsys,
) -> None:
    cfg = _config()
    lock_error = RunnerProcessLifetimeLockError(
        reason_code=RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE,
        path=Path("/shared/runtime/runner.lock"),
    )
    monkeypatch.setattr(
        remote_run,
        "load_remote_runner_config_from_startup_preflight",
        lambda: cfg,
    )
    monkeypatch.setattr(
        remote_run,
        "adopt_runner_process_lifetime_lock",
        lambda _cfg: (_ for _ in ()).throw(lock_error),
    )
    monkeypatch.setattr(
        remote_run,
        "remove_runner_pid_file_if_owned",
        lambda _cfg: (_ for _ in ()).throw(OSError("cleanup failed")),
    )

    assert remote_run.cli_main() == RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE_EXIT_STATUS
    stderr = capsys.readouterr().err
    assert "REMOTE_RUNNER_PID_CLEANUP_FAILED_AFTER_LOCK_ADOPTION: OSError" in stderr
    assert RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE in stderr


def test_runner_layout_failure_cleans_up_before_releasing_lock(monkeypatch) -> None:
    cfg = _config()
    events: list[str] = []

    class FakeLease:
        def release(self) -> None:
            events.append("release")

    monkeypatch.setattr(
        remote_run,
        "load_remote_runner_config_from_startup_preflight",
        lambda: events.append("preflight") or cfg,
    )
    monkeypatch.setattr(
        remote_run,
        "adopt_runner_process_lifetime_lock",
        lambda _cfg: events.append("adopt") or FakeLease(),
    )
    monkeypatch.setattr(
        "apps.remote_runner.config.bind_remote_runner_config_snapshot",
        lambda _cfg: events.append("bind_snapshot"),
    )
    monkeypatch.setattr(
        "apps.remote_runner.config.ensure_runtime_layout",
        lambda _cfg: (_ for _ in ()).throw(RuntimeError("layout failed")),
    )
    monkeypatch.setattr(remote_run, "_set_process_name", lambda: None)
    monkeypatch.setattr(
        remote_run,
        "remove_runner_pid_file_if_owned",
        lambda _cfg: events.append("pid_cleanup"),
    )
    monkeypatch.setattr(
        remote_run.socket,
        "socket",
        lambda *_args, **_kwargs: pytest.fail("socket must follow layout"),
    )

    with pytest.raises(RuntimeError, match="layout failed"):
        remote_run.main()

    assert events == [
        "preflight",
        "adopt",
        "bind_snapshot",
        "pid_cleanup",
        "release",
    ]


def test_runner_serve_failure_closes_socket_before_releasing_lock(monkeypatch) -> None:
    cfg = _config()
    events: list[str] = []

    class FakeLease:
        def release(self) -> None:
            events.append("release")

    class FakeSocket:
        def setsockopt(self, *_args) -> None:
            pass

        def bind(self, _address) -> None:
            pass

        def listen(self, _backlog) -> None:
            pass

        def getsockname(self):
            return ("127.0.0.1", 43210)

        def fileno(self) -> int:
            return 17

        def close(self) -> None:
            events.append("socket_close")

    class FailingServer:
        def __init__(self, _config) -> None:
            pass

        def run(self, *, sockets) -> None:
            assert sockets == [fake_socket]
            events.append("serve")
            raise RuntimeError("serve failed")

    fake_socket = FakeSocket()
    monkeypatch.setitem(
        sys.modules,
        "apps.remote_runner.main",
        SimpleNamespace(app=object()),
    )
    monkeypatch.setattr(
        remote_run,
        "load_remote_runner_config_from_startup_preflight",
        lambda: events.append("preflight") or cfg,
    )
    monkeypatch.setattr(
        remote_run,
        "adopt_runner_process_lifetime_lock",
        lambda _cfg: events.append("adopt") or FakeLease(),
    )
    monkeypatch.setattr(
        "apps.remote_runner.config.bind_remote_runner_config_snapshot",
        lambda _cfg: events.append("bind_snapshot"),
    )
    monkeypatch.setattr(
        "apps.remote_runner.config.ensure_runtime_layout",
        lambda _cfg: events.append("ensure_layout"),
    )
    monkeypatch.setattr(
        "apps.remote_runner.config.write_runtime_state",
        lambda *_args, **_kwargs: events.append("runtime_state"),
    )
    monkeypatch.setattr(remote_run, "_set_process_name", lambda: None)
    monkeypatch.setattr(
        remote_run,
        "remove_runner_pid_file_if_owned",
        lambda _cfg: events.append("pid_cleanup"),
    )
    monkeypatch.setattr(
        remote_run.socket,
        "socket",
        lambda *_args, **_kwargs: events.append("socket_create") or fake_socket,
    )
    monkeypatch.setattr("uvicorn.Config", lambda *_args, **_kwargs: object())
    monkeypatch.setattr("uvicorn.Server", FailingServer)

    with pytest.raises(RuntimeError, match="serve failed"):
        remote_run.main()

    assert events == [
        "preflight",
        "adopt",
        "bind_snapshot",
        "ensure_layout",
        "socket_create",
        "runtime_state",
        "serve",
        "socket_close",
        "pid_cleanup",
        "release",
    ]


def test_runner_cli_returns_zero_after_clean_server_exit(monkeypatch) -> None:
    monkeypatch.setattr(remote_run, "main", lambda: None)

    assert remote_run.cli_main() == 0
