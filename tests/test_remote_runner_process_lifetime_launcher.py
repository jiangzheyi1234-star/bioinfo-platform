from __future__ import annotations

import errno
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.remote_runner import runner_lifetime_launcher as launcher
from apps.remote_runner import process_pid_file
from apps.remote_runner.process_owner import RunnerProcessOwnerError
from apps.remote_runner.process_lifetime_lock import (
    RUNNER_PROCESS_LIFETIME_LOCK_HELD,
    RunnerProcessLifetimeLockError,
)
from core.contracts.runner_process_lifetime import (
    RUNNER_PROCESS_LIFETIME_LAUNCHER_MODULE,
    RUNNER_PROCESS_LIFETIME_LOCK_FD_ENV,
    RUNNER_PROCESS_LIFETIME_LOCK_HELD_EXIT_STATUS,
)
from core.contracts.runner_process_owner import (
    RUNNER_PROCESS_OWNER_FINGERPRINT_ENV,
    RUNNER_PROCESS_OWNER_LAUNCH_ID_ENV,
    RUNNER_PROCESS_OWNER_UNAVAILABLE_EXIT_STATUS,
)


def _config(tmp_path: Path):
    release_root = tmp_path / "release"
    (release_root / "remote_runner").mkdir(parents=True)
    return SimpleNamespace(
        service_name="h2ometa-remote",
        version="owner-launcher-test",
        mode="background_process",
        release_dir=str(release_root / "remote_runner"),
        runner_python=str(release_root / "runtime" / "bin" / "python"),
        runtime_state_path=str(tmp_path / "shared" / "runtime" / "runner-state.json"),
    )


def _startup_binding() -> dict[str, str]:
    return {"snapshot": "locked"}


def test_launcher_module_remains_visible_to_transitional_stop_selectors() -> None:
    root = Path(__file__).resolve().parents[1]

    assert RUNNER_PROCESS_LIFETIME_LAUNCHER_MODULE.startswith("remote_runner.run")
    for relative_path in (
        "core/app_runtime/remote_runner_stop.py",
        "core/remote_runner/bootstrap_activation.py",
        "core/remote_runner/bootstrap_bundle.py",
        "core/remote_runner/bootstrap_guard.py",
        "core/remote_runner/token_rotation.py",
        "core/remote_runner/uninstall.py",
    ):
        source = (root / relative_path).read_text(encoding="utf-8")
        assert "[r]emote_runner.run" in source


def test_launcher_locks_before_runtime_prepare_and_pid_publication(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _config(tmp_path)
    events: list[object] = []

    class FakeLease:
        def require_matches_config(self, _cfg):
            events.append("lock_match")

        def mutation_subprocess_pass_fds(self):
            events.append("prepare_fd")
            return (31,)

        def build_exec_environment(self, environment):
            events.append("inherit")
            return {**environment, RUNNER_PROCESS_LIFETIME_LOCK_FD_ENV: "31"}

        def release(self):
            events.append("release")

    preflight_count = 0

    def load_config():
        nonlocal preflight_count
        preflight_count += 1
        events.append("preflight")
        return cfg, _startup_binding()

    def acquire(_cfg):
        events.append("acquire")
        return FakeLease()

    def fail_exec(_cfg, environment):
        events.append(("exec", environment[RUNNER_PROCESS_LIFETIME_LOCK_FD_ENV]))
        raise OSError(errno.ENOENT, "exec failed")

    monkeypatch.setattr(
        launcher, "load_remote_runner_startup_snapshot", load_config
    )
    monkeypatch.setattr(launcher, "acquire_runner_process_lifetime_lock", acquire)
    monkeypatch.setattr(
        launcher,
        "publish_runner_process_owner",
        lambda _cfg, **_kwargs: events.append("owner") or {"launchId": "1" * 32},
    )
    monkeypatch.setattr(
        launcher,
        "build_runner_process_owner_exec_environment",
        lambda _owner, environment: events.append("owner_env")
        or {
            **environment,
            RUNNER_PROCESS_OWNER_LAUNCH_ID_ENV: "1" * 32,
            RUNNER_PROCESS_OWNER_FINGERPRINT_ENV: "sha256:" + "a" * 64,
        },
    )
    monkeypatch.setattr(
        launcher, "_build_runtime_environment", lambda _cfg, _env: {"PATH": "/bin"}
    )
    monkeypatch.setattr(
        launcher,
        "_prepare_bundled_runtime",
        lambda _cfg, _env, *, lock_pass_fds: events.append(
            ("prepare", lock_pass_fds)
        ),
    )
    monkeypatch.setattr(
        launcher, "write_runner_pid_file_atomic", lambda _cfg: events.append("pid")
    )
    monkeypatch.setattr(
        launcher,
        "remove_runner_pid_file_if_owned",
        lambda _cfg: events.append("pid_cleanup"),
    )
    monkeypatch.setattr(launcher, "_exec_remote_runner", fail_exec)

    with pytest.raises(OSError, match="exec failed"):
        launcher.launch_remote_runner()

    assert events == [
        "preflight",
        "acquire",
        "preflight",
        "lock_match",
        "owner",
        "pid",
        "prepare_fd",
        ("prepare", (31,)),
        "inherit",
        "owner_env",
        ("exec", "31"),
        "pid_cleanup",
        "release",
    ]


def test_lock_contention_exits_without_runtime_mutation(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    cfg = _config(tmp_path)
    lock_path = Path(cfg.runtime_state_path).with_name("runner.lock")
    monkeypatch.setattr(
        launcher, "load_remote_runner_startup_snapshot", lambda: (cfg, _startup_binding())
    )
    monkeypatch.setattr(
        launcher,
        "acquire_runner_process_lifetime_lock",
        lambda _cfg: (_ for _ in ()).throw(
            RunnerProcessLifetimeLockError(
                reason_code=RUNNER_PROCESS_LIFETIME_LOCK_HELD,
                path=lock_path,
            )
        ),
    )
    monkeypatch.setattr(
        launcher,
        "_prepare_bundled_runtime",
        lambda *_args: pytest.fail("runtime mutation must not run after contention"),
    )
    monkeypatch.setattr(
        launcher,
        "write_runner_pid_file_atomic",
        lambda *_args: pytest.fail("PID publication must not run after contention"),
    )
    monkeypatch.setattr(
        launcher,
        "publish_runner_process_owner",
        lambda *_args, **_kwargs: pytest.fail(
            "owner publication must not run after contention"
        ),
    )

    assert launcher.main() == RUNNER_PROCESS_LIFETIME_LOCK_HELD_EXIT_STATUS
    assert RUNNER_PROCESS_LIFETIME_LOCK_HELD in capsys.readouterr().err


def test_provisional_snapshot_failure_prevents_restart_before_lock(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        launcher,
        "load_remote_runner_startup_snapshot",
        lambda: (_ for _ in ()).throw(RuntimeError("REMOTE_RUNNER_CONFIG_INVALID")),
    )
    monkeypatch.setattr(
        launcher,
        "acquire_runner_process_lifetime_lock",
        lambda _cfg: pytest.fail("lock must follow a valid provisional snapshot"),
    )

    assert launcher.main() == RUNNER_PROCESS_OWNER_UNAVAILABLE_EXIT_STATUS
    assert "REMOTE_RUNNER_PROCESS_OWNER_UNAVAILABLE" in capsys.readouterr().err


def test_locked_snapshot_failure_cleans_pid_hint_and_releases_lock(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    cfg = _config(tmp_path)
    events: list[str] = []
    reads = 0

    class FakeLease:
        def release(self) -> None:
            events.append("release")

    def load_snapshot():
        nonlocal reads
        reads += 1
        if reads == 1:
            return cfg, _startup_binding()
        raise RuntimeError("REMOTE_RUNNER_ARTIFACT_MANIFEST_INVALID")

    monkeypatch.setattr(launcher, "load_remote_runner_startup_snapshot", load_snapshot)
    monkeypatch.setattr(
        launcher,
        "acquire_runner_process_lifetime_lock",
        lambda _cfg: events.append("acquire") or FakeLease(),
    )
    monkeypatch.setattr(
        launcher,
        "remove_runner_pid_file_if_owned",
        lambda _cfg: events.append("pid_cleanup"),
    )
    monkeypatch.setattr(
        launcher,
        "publish_runner_process_owner",
        lambda *_args, **_kwargs: pytest.fail("owner must follow locked snapshot"),
    )

    assert launcher.main() == RUNNER_PROCESS_OWNER_UNAVAILABLE_EXIT_STATUS
    assert events == ["acquire", "pid_cleanup", "release"]
    assert "REMOTE_RUNNER_PROCESS_OWNER_UNAVAILABLE" in capsys.readouterr().err


def test_locked_snapshot_failure_preserves_exit_75_when_cleanup_also_fails(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    cfg = _config(tmp_path)
    reads = 0

    class FailingReleaseLease:
        def release(self) -> None:
            raise OSError("release failed")

    def load_snapshot():
        nonlocal reads
        reads += 1
        if reads == 1:
            return cfg, _startup_binding()
        raise RuntimeError("REMOTE_RUNNER_ARTIFACT_MANIFEST_INVALID")

    monkeypatch.setattr(launcher, "load_remote_runner_startup_snapshot", load_snapshot)
    monkeypatch.setattr(
        launcher,
        "acquire_runner_process_lifetime_lock",
        lambda _cfg: FailingReleaseLease(),
    )
    monkeypatch.setattr(
        launcher,
        "remove_runner_pid_file_if_owned",
        lambda _cfg: (_ for _ in ()).throw(
            UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid")
        ),
    )

    assert launcher.main() == RUNNER_PROCESS_OWNER_UNAVAILABLE_EXIT_STATUS
    stderr = capsys.readouterr().err
    assert "REMOTE_RUNNER_PID_CLEANUP_FAILED_AFTER_LAUNCHER_ERROR" in stderr
    assert "REMOTE_RUNNER_LOCK_RELEASE_FAILED_AFTER_LAUNCHER_ERROR" in stderr
    assert "REMOTE_RUNNER_PROCESS_OWNER_UNAVAILABLE" in stderr


def test_prepare_failure_sees_published_pid_and_releases_lock(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _config(tmp_path)
    events: list[str] = []

    class FakeLease:
        def require_matches_config(self, _cfg):
            events.append("lock_match")

        def mutation_subprocess_pass_fds(self):
            return (31,)

        def release(self):
            events.append("release")

    monkeypatch.setattr(
        launcher,
        "load_remote_runner_startup_snapshot",
        lambda: (cfg, _startup_binding()),
    )
    monkeypatch.setattr(
        launcher,
        "acquire_runner_process_lifetime_lock",
        lambda _cfg: events.append("acquire") or FakeLease(),
    )
    monkeypatch.setattr(
        launcher,
        "write_runner_pid_file_atomic",
        lambda _cfg: events.append("pid"),
    )
    monkeypatch.setattr(
        launcher,
        "publish_runner_process_owner",
        lambda _cfg, **_kwargs: events.append("owner") or {"launchId": "1" * 32},
    )
    monkeypatch.setattr(
        launcher,
        "_prepare_bundled_runtime",
        lambda _cfg, _env, *, lock_pass_fds: (
            events.append("prepare")
            or (_ for _ in ()).throw(RuntimeError("prepare failed"))
        ),
    )
    monkeypatch.setattr(
        launcher,
        "remove_runner_pid_file_if_owned",
        lambda _cfg: events.append("pid_cleanup"),
    )
    monkeypatch.setattr(
        launcher,
        "_exec_remote_runner",
        lambda *_args: pytest.fail("exec must follow successful preparation"),
    )

    with pytest.raises(RuntimeError, match="prepare failed"):
        launcher.launch_remote_runner()

    assert events == [
        "acquire",
        "lock_match",
        "owner",
        "pid",
        "prepare",
        "pid_cleanup",
        "release",
    ]


def test_partial_pid_publication_failure_runs_owner_cleanup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _config(tmp_path)
    events: list[str] = []

    class FakeLease:
        def require_matches_config(self, _cfg):
            pass

        def release(self):
            events.append("release")

    fsync_calls = 0

    def fail_first_directory_fsync(_path: Path) -> None:
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls == 1:
            events.append("pid_committed")
            raise OSError(errno.EIO, "directory fsync failed")

    def cleanup_pid(_cfg) -> bool:
        events.append("pid_cleanup")
        return process_pid_file.remove_runner_pid_file_if_owned(cfg)

    def publish_pid(_cfg) -> Path:
        return process_pid_file.write_runner_pid_file_atomic(cfg)

    monkeypatch.setattr(
        launcher,
        "load_remote_runner_startup_snapshot",
        lambda: (cfg, _startup_binding()),
    )
    monkeypatch.setattr(
        launcher,
        "acquire_runner_process_lifetime_lock",
        lambda _cfg: FakeLease(),
    )
    monkeypatch.setattr(
        process_pid_file,
        "_fsync_directory",
        fail_first_directory_fsync,
    )
    monkeypatch.setattr(launcher, "write_runner_pid_file_atomic", publish_pid)
    monkeypatch.setattr(
        launcher,
        "publish_runner_process_owner",
        lambda _cfg, **_kwargs: {"launchId": "1" * 32},
    )
    monkeypatch.setattr(
        launcher,
        "remove_runner_pid_file_if_owned",
        cleanup_pid,
    )
    monkeypatch.setattr(
        launcher,
        "_prepare_bundled_runtime",
        lambda *_args, **_kwargs: pytest.fail("prepare must follow PID publication"),
    )

    with pytest.raises(OSError, match="directory fsync failed"):
        launcher.launch_remote_runner()

    assert events == ["pid_committed", "pid_cleanup", "release"]
    assert not process_pid_file.get_runner_pid_file_path(cfg).exists()


def test_owner_publication_failure_is_restart_preventing_and_precedes_pid(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    cfg = _config(tmp_path)
    events: list[str] = []

    class FakeLease:
        def require_matches_config(self, _cfg) -> None:
            events.append("lock_match")

        def release(self) -> None:
            events.append("release")

    owner_error = RunnerProcessOwnerError(
        path=Path(cfg.runtime_state_path).with_name("runner-process-owner.json")
    )
    monkeypatch.setattr(
        launcher,
        "load_remote_runner_startup_snapshot",
        lambda: (cfg, _startup_binding()),
    )
    monkeypatch.setattr(
        launcher,
        "acquire_runner_process_lifetime_lock",
        lambda _cfg: events.append("acquire") or FakeLease(),
    )
    monkeypatch.setattr(
        launcher,
        "publish_runner_process_owner",
        lambda _cfg, **_kwargs: events.append("owner")
        or (_ for _ in ()).throw(owner_error),
    )
    monkeypatch.setattr(
        launcher,
        "remove_runner_pid_file_if_owned",
        lambda _cfg: events.append("pid_cleanup"),
    )
    monkeypatch.setattr(
        launcher,
        "write_runner_pid_file_atomic",
        lambda _cfg: pytest.fail("PID must follow owner publication"),
    )
    monkeypatch.setattr(
        launcher,
        "_prepare_bundled_runtime",
        lambda *_args, **_kwargs: pytest.fail("prepare must follow owner publication"),
    )

    assert launcher.main() == RUNNER_PROCESS_OWNER_UNAVAILABLE_EXIT_STATUS
    assert events == ["acquire", "lock_match", "owner", "pid_cleanup", "release"]
    assert "REMOTE_RUNNER_PROCESS_OWNER_UNAVAILABLE" in capsys.readouterr().err


def test_prepare_bundled_runtime_runs_conda_unpack_then_writes_marker(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _config(tmp_path)
    runner_python = Path(cfg.runner_python)
    runner_python.parent.mkdir(parents=True)
    runner_python.write_text("python", encoding="utf-8")
    conda_unpack = runner_python.with_name("conda-unpack")
    conda_unpack.write_text("unpack", encoding="utf-8")
    calls: list[object] = []
    monkeypatch.setattr(
        launcher.os,
        "access",
        lambda path, mode: path == conda_unpack and mode == os.X_OK,
    )
    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    launcher._prepare_bundled_runtime(
        cfg,
        {"PATH": "/tools"},
        lock_pass_fds=(31,),
    )

    marker = runner_python.parent.parent / ".h2ometa-conda-unpacked"
    assert marker.is_file()
    assert calls[0][0] == ([str(runner_python), str(conda_unpack)],)
    assert calls[0][1]["check"] is True
    assert calls[0][1]["env"] == {"PATH": "/tools"}
    assert calls[0][1]["pass_fds"] == (31,)

    launcher._prepare_bundled_runtime(
        cfg,
        {"PATH": "/tools"},
        lock_pass_fds=(31,),
    )
    assert len(calls) == 1


def test_runtime_environment_prepends_shared_tools_bin(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    tools_bin = Path(cfg.runtime_state_path).parent.parent / "tools" / "bin"
    tools_bin.mkdir(parents=True)

    result = launcher._build_runtime_environment(
        cfg, {"PATH": "/usr/bin", "KEEP": "yes"}
    )

    assert result["PATH"] == f"{tools_bin}{os.pathsep}/usr/bin"
    assert result["KEEP"] == "yes"


def test_pid_file_is_atomic_diagnostic_and_cleanup_is_owner_conditional(
    tmp_path: Path,
) -> None:
    cfg = _config(tmp_path)
    path = process_pid_file.write_runner_pid_file_atomic(cfg, pid=321)

    assert path.read_text(encoding="utf-8") == "321\n"
    assert not process_pid_file.remove_runner_pid_file_if_owned(cfg, pid=322)
    assert path.is_file()
    assert process_pid_file.remove_runner_pid_file_if_owned(cfg, pid=321)
    assert not path.exists()
    assert not list(path.parent.glob(f".{path.name}.*.tmp"))


def test_pid_writer_exposes_post_replace_fsync_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _config(tmp_path)
    monkeypatch.setattr(
        process_pid_file,
        "_fsync_directory",
        lambda _path: (_ for _ in ()).throw(OSError(errno.EIO, "fsync failed")),
    )

    with pytest.raises(OSError, match="fsync failed"):
        process_pid_file.write_runner_pid_file_atomic(cfg, pid=321)

    path = process_pid_file.get_runner_pid_file_path(cfg)
    assert path.read_text(encoding="utf-8") == "321\n"
