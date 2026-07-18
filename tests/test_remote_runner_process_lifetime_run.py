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
from apps.remote_runner.process_owner import (
    RUNNER_PROCESS_OWNER_UNAVAILABLE,
    RunnerProcessOwnerError,
)
from core.contracts.runner_process_lifetime import (
    RUNNER_PROCESS_LIFETIME_LOCK_FD_ENV,
    RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE_EXIT_STATUS,
)
from core.contracts.runner_process_owner import (
    RUNNER_PROCESS_OWNER_FINGERPRINT_ENV,
    RUNNER_PROCESS_OWNER_LAUNCH_ID_ENV,
    RUNNER_PROCESS_OWNER_UNAVAILABLE_EXIT_STATUS,
)


def _config():
    return SimpleNamespace(
        bind_host="127.0.0.1",
        bind_port=0,
        mode="background_process",
        release_dir="/release/remote_runner",
        runtime_state_path="/shared/runtime/runner-state.json",
        service_name="h2ometa-remote",
        version="owner-run-test",
    )


def _startup_binding() -> dict[str, str]:
    return {"snapshot": "locked"}


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
        "load_remote_runner_startup_snapshot",
        lambda: (cfg, _startup_binding()),
    )
    monkeypatch.setattr(
        remote_run,
        "adopt_runner_process_lifetime_lock",
        lambda _cfg: (_ for _ in ()).throw(lock_error),
    )
    monkeypatch.setattr(
        remote_run,
        "adopt_runner_process_owner",
        lambda *_args, **_kwargs: pytest.fail(
            "owner adoption must follow lock adoption"
        ),
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
        "load_remote_runner_startup_snapshot",
        lambda: (cfg, _startup_binding()),
    )
    monkeypatch.setattr(
        remote_run,
        "adopt_runner_process_lifetime_lock",
        lambda _cfg: (_ for _ in ()).throw(lock_error),
    )
    monkeypatch.setattr(
        remote_run,
        "adopt_runner_process_owner",
        lambda *_args, **_kwargs: pytest.fail(
            "owner adoption must follow lock adoption"
        ),
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


def test_runner_cli_maps_post_exec_snapshot_rejection_and_scrubs_bindings(
    monkeypatch,
    capsys,
) -> None:
    cleanup_paths: list[Path] = []
    inheritable_calls: list[tuple[int, bool]] = []
    monkeypatch.setenv(RUNNER_PROCESS_LIFETIME_LOCK_FD_ENV, "31")
    monkeypatch.setenv(RUNNER_PROCESS_OWNER_LAUNCH_ID_ENV, "1" * 32)
    monkeypatch.setenv(
        RUNNER_PROCESS_OWNER_FINGERPRINT_ENV,
        "sha256:" + "a" * 64,
    )
    monkeypatch.setattr(
        remote_run,
        "load_remote_runner_startup_snapshot",
        lambda: (_ for _ in ()).throw(
            RuntimeError("REMOTE_RUNNER_ARTIFACT_ARCHIVE_SHA256_INVALID")
        ),
    )
    monkeypatch.setattr(
        remote_run,
        "remove_runner_pid_file_path_if_owned",
        lambda path: cleanup_paths.append(path) or True,
    )
    monkeypatch.setattr(
        remote_run.os,
        "set_inheritable",
        lambda fd, value: inheritable_calls.append((fd, value)),
    )
    monkeypatch.setattr(
        remote_run,
        "adopt_runner_process_lifetime_lock",
        lambda _cfg: pytest.fail("lock adoption must follow the snapshot"),
    )

    assert remote_run.cli_main() == RUNNER_PROCESS_OWNER_UNAVAILABLE_EXIT_STATUS
    assert cleanup_paths == [
        Path(remote_run.__file__).resolve().parents[1] / "runner.pid"
    ]
    assert inheritable_calls == [(31, False)]
    assert RUNNER_PROCESS_LIFETIME_LOCK_FD_ENV not in remote_run.os.environ
    assert RUNNER_PROCESS_OWNER_LAUNCH_ID_ENV not in remote_run.os.environ
    assert RUNNER_PROCESS_OWNER_FINGERPRINT_ENV not in remote_run.os.environ
    stderr = capsys.readouterr().err
    assert "REMOTE_RUNNER_STARTUP_SNAPSHOT_REJECTED_AFTER_EXEC" in stderr
    assert "REMOTE_RUNNER_PROCESS_OWNER_UNAVAILABLE" in stderr


def test_post_exec_snapshot_rejection_ignores_oversized_inherited_fd(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv(RUNNER_PROCESS_LIFETIME_LOCK_FD_ENV, "9" * 5000)
    monkeypatch.setenv(RUNNER_PROCESS_OWNER_LAUNCH_ID_ENV, "1" * 32)
    monkeypatch.setenv(
        RUNNER_PROCESS_OWNER_FINGERPRINT_ENV,
        "sha256:" + "a" * 64,
    )
    monkeypatch.setattr(
        remote_run,
        "load_remote_runner_startup_snapshot",
        lambda: (_ for _ in ()).throw(RuntimeError("snapshot rejected")),
    )
    monkeypatch.setattr(
        remote_run,
        "remove_runner_pid_file_path_if_owned",
        lambda _path: True,
    )
    monkeypatch.setattr(
        remote_run.os,
        "set_inheritable",
        lambda *_args: pytest.fail("oversized FD must not reach the OS"),
    )

    assert remote_run.cli_main() == RUNNER_PROCESS_OWNER_UNAVAILABLE_EXIT_STATUS
    assert RUNNER_PROCESS_LIFETIME_LOCK_FD_ENV not in remote_run.os.environ
    assert RUNNER_PROCESS_OWNER_LAUNCH_ID_ENV not in remote_run.os.environ
    assert RUNNER_PROCESS_OWNER_FINGERPRINT_ENV not in remote_run.os.environ
    assert "REMOTE_RUNNER_STARTUP_SNAPSHOT_REJECTED_AFTER_EXEC" in (
        capsys.readouterr().err
    )


def test_runner_cli_maps_owner_adoption_failure_and_releases_lock(
    monkeypatch,
    capsys,
) -> None:
    cfg = _config()
    events: list[str] = []

    class FakeLease:
        def release(self) -> None:
            events.append("release")

    owner_error = RunnerProcessOwnerError(
        path=Path("/shared/runtime/runner-process-owner.json")
    )
    monkeypatch.setattr(
        remote_run,
        "load_remote_runner_startup_snapshot",
        lambda: (cfg, _startup_binding()),
    )
    monkeypatch.setattr(
        remote_run,
        "adopt_runner_process_lifetime_lock",
        lambda _cfg: events.append("lock_adopt") or FakeLease(),
    )
    monkeypatch.setattr(
        remote_run,
        "adopt_runner_process_owner",
        lambda *_args, **_kwargs: events.append("owner_adopt")
        or (_ for _ in ()).throw(owner_error),
    )
    monkeypatch.setattr(
        remote_run,
        "remove_runner_pid_file_if_owned",
        lambda _cfg: events.append("pid_cleanup"),
    )
    monkeypatch.setattr(
        remote_run.socket,
        "socket",
        lambda *_args, **_kwargs: pytest.fail("socket must follow owner adoption"),
    )

    assert remote_run.cli_main() == RUNNER_PROCESS_OWNER_UNAVAILABLE_EXIT_STATUS
    assert events == ["lock_adopt", "owner_adopt", "pid_cleanup", "release"]
    assert RUNNER_PROCESS_OWNER_UNAVAILABLE in capsys.readouterr().err


def test_runner_layout_failure_cleans_up_before_releasing_lock(monkeypatch) -> None:
    cfg = _config()
    events: list[str] = []

    class FakeLease:
        def release(self) -> None:
            events.append("release")

    monkeypatch.setattr(
        remote_run,
        "load_remote_runner_startup_snapshot",
        lambda: events.append("preflight") or (cfg, _startup_binding()),
    )
    monkeypatch.setattr(
        remote_run,
        "adopt_runner_process_lifetime_lock",
        lambda _cfg: events.append("lock_adopt") or FakeLease(),
    )
    monkeypatch.setattr(
        remote_run,
        "adopt_runner_process_owner",
        lambda _cfg, **_kwargs: events.append("owner_adopt") or {"owner": True},
    )
    monkeypatch.setattr(
        "apps.remote_runner.config.bind_remote_runner_config_snapshot",
        lambda _cfg: events.append("bind_snapshot"),
    )
    monkeypatch.setattr(
        "apps.remote_runner.config.bind_remote_runner_startup_binding",
        lambda _binding: None,
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
        "lock_adopt",
        "owner_adopt",
        "bind_snapshot",
        "pid_cleanup",
        "release",
    ]


def test_runner_cleanup_failures_do_not_replace_primary_runtime_failure(
    monkeypatch,
) -> None:
    cfg = _config()

    class FailingLease:
        def release(self) -> None:
            raise OSError("release failed")

    monkeypatch.setattr(
        remote_run,
        "load_remote_runner_startup_snapshot",
        lambda: (cfg, _startup_binding()),
    )
    monkeypatch.setattr(
        remote_run,
        "adopt_runner_process_lifetime_lock",
        lambda _cfg: FailingLease(),
    )
    monkeypatch.setattr(
        remote_run,
        "adopt_runner_process_owner",
        lambda *_args, **_kwargs: {"owner": True},
    )
    monkeypatch.setattr(
        "apps.remote_runner.config.bind_remote_runner_config_snapshot",
        lambda _cfg: None,
    )
    monkeypatch.setattr(
        "apps.remote_runner.config.bind_remote_runner_startup_binding",
        lambda _binding: None,
    )
    monkeypatch.setattr(
        "apps.remote_runner.config.ensure_runtime_layout",
        lambda _cfg: (_ for _ in ()).throw(RuntimeError("layout failed")),
    )
    monkeypatch.setattr(remote_run, "_set_process_name", lambda: None)
    monkeypatch.setattr(
        remote_run,
        "remove_runner_pid_file_if_owned",
        lambda _cfg: (_ for _ in ()).throw(OSError("cleanup failed")),
    )

    with pytest.raises(RuntimeError, match="layout failed"):
        remote_run.main()


def test_runner_serve_failure_closes_socket_before_releasing_lock(monkeypatch) -> None:
    cfg = _config()
    events: list[str] = []
    captured: dict[str, object] = {}
    adopted_owner = {"owner": True}

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
        "load_remote_runner_startup_snapshot",
        lambda: events.append("preflight") or (cfg, _startup_binding()),
    )
    monkeypatch.setattr(
        remote_run,
        "adopt_runner_process_lifetime_lock",
        lambda _cfg: events.append("lock_adopt") or FakeLease(),
    )
    monkeypatch.setattr(
        remote_run,
        "adopt_runner_process_owner",
        lambda _cfg, **_kwargs: events.append("owner_adopt") or adopted_owner,
    )
    monkeypatch.setattr(
        "apps.remote_runner.config.bind_remote_runner_config_snapshot",
        lambda _cfg: events.append("bind_snapshot"),
    )
    monkeypatch.setattr(
        "apps.remote_runner.config.bind_remote_runner_startup_binding",
        lambda _binding: None,
    )
    monkeypatch.setattr(
        "apps.remote_runner.config.ensure_runtime_layout",
        lambda _cfg: events.append("ensure_layout"),
    )
    monkeypatch.setattr(
        "apps.remote_runner.config.write_runtime_state",
        lambda *_args, **kwargs: (
            captured.update(process_owner=kwargs["process_owner"]),
            events.append("runtime_state"),
        ),
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
        "lock_adopt",
        "owner_adopt",
        "bind_snapshot",
        "ensure_layout",
        "socket_create",
        "runtime_state",
        "serve",
        "socket_close",
        "pid_cleanup",
        "release",
    ]
    assert captured["process_owner"] is adopted_owner


def test_runner_cli_returns_zero_after_clean_server_exit(monkeypatch) -> None:
    monkeypatch.setattr(remote_run, "main", lambda: None)

    assert remote_run.cli_main() == 0
