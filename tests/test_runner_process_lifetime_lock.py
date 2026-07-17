from __future__ import annotations

import errno
import os
from pathlib import Path
import stat
import subprocess
import sys
import textwrap
import time
from types import SimpleNamespace

import pytest

from apps.remote_runner import process_lifetime_lock as lifetime_lock
from core.contracts.runner_process_lifetime import (
    RUNNER_PROCESS_LIFETIME_LOCK_FD_ENV,
    RUNNER_PROCESS_LIFETIME_LOCK_HELD_EXIT_STATUS,
    RUNNER_PROCESS_LIFETIME_LOCK_PROFILE,
    RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE_EXIT_STATUS,
)


def _config(path: Path):
    return SimpleNamespace(
        runtime_state_path=str(path / "runtime" / "runner-state.json")
    )


def test_invalid_runtime_state_path_maps_all_lock_boundaries_to_exit_74(
    tmp_path: Path,
    monkeypatch,
) -> None:
    invalid_cfg = SimpleNamespace(runtime_state_path="")

    with pytest.raises(lifetime_lock.RunnerProcessLifetimeLockError) as acquire_exc:
        lifetime_lock.acquire_runner_process_lifetime_lock(invalid_cfg)
    assert (
        acquire_exc.value.exit_status
        == RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE_EXIT_STATUS
    )

    closed: list[int] = []
    monkeypatch.setattr(lifetime_lock, "_close_lock_file", closed.append)
    with pytest.raises(lifetime_lock.RunnerProcessLifetimeLockError) as adopt_exc:
        lifetime_lock.adopt_runner_process_lifetime_lock(
            invalid_cfg,
            environ={RUNNER_PROCESS_LIFETIME_LOCK_FD_ENV: "23"},
        )
    assert adopt_exc.value.exit_status == RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE_EXIT_STATUS
    assert closed == [23]

    lease = lifetime_lock.RunnerProcessLifetimeLock(
        path=tmp_path / "runner.lock",
        _fd=31,
    )
    with pytest.raises(lifetime_lock.RunnerProcessLifetimeLockError) as match_exc:
        lease.require_matches_config(invalid_cfg)
    assert match_exc.value.exit_status == RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE_EXIT_STATUS


def test_huge_inherited_lock_fd_is_mapped_without_integer_escape(tmp_path: Path) -> None:
    huge_fd = "9" * 100_000

    with pytest.raises(lifetime_lock.RunnerProcessLifetimeLockError) as exc_info:
        lifetime_lock.adopt_runner_process_lifetime_lock(
            _config(tmp_path),
            environ={RUNNER_PROCESS_LIFETIME_LOCK_FD_ENV: huge_fd},
        )

    assert exc_info.value.exit_status == RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE_EXIT_STATUS


def test_noncanonical_inherited_fd_is_rejected_without_closing_that_fd(
    tmp_path: Path,
    monkeypatch,
) -> None:
    closed: list[int] = []
    monkeypatch.setattr(lifetime_lock, "_close_lock_file", closed.append)

    with pytest.raises(lifetime_lock.RunnerProcessLifetimeLockError) as exc_info:
        lifetime_lock.adopt_runner_process_lifetime_lock(
            _config(tmp_path),
            environ={RUNNER_PROCESS_LIFETIME_LOCK_FD_ENV: "03"},
        )

    assert exc_info.value.exit_status == RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE_EXIT_STATUS
    assert closed == []


def test_missing_or_explosive_runtime_state_attribute_maps_to_exit_74() -> None:
    class ExplosiveConfig:
        @property
        def runtime_state_path(self):
            raise RuntimeError("explosive config getter")

    for cfg in (SimpleNamespace(), ExplosiveConfig()):
        with pytest.raises(lifetime_lock.RunnerProcessLifetimeLockError) as exc_info:
            lifetime_lock.acquire_runner_process_lifetime_lock(cfg)
        assert (
            exc_info.value.exit_status
            == RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE_EXIT_STATUS
        )


def _exec_lock_helper_source() -> str:
    return textwrap.dedent(
        """
        import os
        from pathlib import Path
        import sys
        import time
        from types import SimpleNamespace

        repo_root, state_path, ready_path, release_path = sys.argv[1:]
        sys.path.insert(0, repo_root)
        from apps.remote_runner.process_lifetime_lock import (
            acquire_runner_process_lifetime_lock,
            adopt_runner_process_lifetime_lock,
        )
        from core.contracts.runner_process_lifetime import (
            RUNNER_PROCESS_LIFETIME_LOCK_FD_ENV,
        )

        cfg = SimpleNamespace(runtime_state_path=state_path)
        if os.environ.get("H2OMETA_LOCK_EXEC_TEST_PHASE") == "adopt":
            lease = adopt_runner_process_lifetime_lock(cfg)
            assert RUNNER_PROCESS_LIFETIME_LOCK_FD_ENV not in os.environ
            assert not os.get_inheritable(lease._fd)
            Path(ready_path).write_text("adopted\\n", encoding="utf-8")
            deadline = time.monotonic() + 10
            while not Path(release_path).exists():
                if time.monotonic() >= deadline:
                    raise RuntimeError("parent did not release child")
                time.sleep(0.02)
            lease.release()
        else:
            lease = acquire_runner_process_lifetime_lock(cfg)
            environment = lease.build_exec_environment(os.environ)
            environment["H2OMETA_LOCK_EXEC_TEST_PHASE"] = "adopt"
            executable = sys.executable
            os.execve(
                executable,
                [
                    executable,
                    str(Path(__file__).resolve()),
                    repo_root,
                    state_path,
                    ready_path,
                    release_path,
                ],
                environment,
            )
        """
    )


def _mutation_child_source() -> str:
    return textwrap.dedent(
        """
        from pathlib import Path
        import sys
        import time

        ready, release = sys.argv[1:]
        Path(ready).write_text("ready\\n", encoding="utf-8")
        deadline = time.monotonic() + 10
        while not Path(release).exists():
            if time.monotonic() >= deadline:
                raise RuntimeError("mutation child release timed out")
            time.sleep(0.02)
        """
    )


def _mutation_parent_helper_source(child_code: str) -> str:
    return textwrap.dedent(
        f"""
        from pathlib import Path
        import subprocess
        import sys
        import time
        from types import SimpleNamespace

        repo_root, state_path, child_ready, release_child = sys.argv[1:]
        sys.path.insert(0, repo_root)
        from apps.remote_runner.process_lifetime_lock import (
            acquire_runner_process_lifetime_lock,
        )

        lease = acquire_runner_process_lifetime_lock(
            SimpleNamespace(runtime_state_path=state_path)
        )
        child_code = {child_code!r}
        subprocess.Popen(
            [sys.executable, "-c", child_code, child_ready, release_child],
            close_fds=True,
            pass_fds=lease.mutation_subprocess_pass_fds(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 10
        while not Path(child_ready).exists():
            if time.monotonic() >= deadline:
                raise RuntimeError("mutation child did not start")
            time.sleep(0.02)
        time.sleep(30)
        """
    )


def test_linux_subprocess_helper_sources_compile_cross_platform() -> None:
    child_source = _mutation_child_source()
    compile(_exec_lock_helper_source(), "flock_exec_helper.py", "exec")
    compile(child_source, "mutation_child.py", "exec")
    compile(
        _mutation_parent_helper_source(child_source),
        "mutation_parent.py",
        "exec",
    )


def test_cooperating_lock_fences_same_path_but_not_distinct_paths(
    tmp_path: Path,
    monkeypatch,
) -> None:
    next_fd = 100
    fd_paths: dict[int, Path] = {}
    locked_fds: set[int] = set()
    held_paths: set[Path] = set()

    def fake_open(path: Path) -> int:
        nonlocal next_fd
        next_fd += 1
        fd_paths[next_fd] = path
        return next_fd

    def fake_lock(fd: int) -> None:
        path = fd_paths[fd]
        if path in held_paths and fd not in locked_fds:
            raise BlockingIOError(errno.EAGAIN, "held")
        held_paths.add(path)
        locked_fds.add(fd)

    def fake_close(fd: int) -> None:
        if fd in locked_fds:
            locked_fds.remove(fd)
            held_paths.remove(fd_paths[fd])

    monkeypatch.setattr(lifetime_lock, "_open_lock_file", fake_open)
    monkeypatch.setattr(lifetime_lock, "_try_lock_file", fake_lock)
    monkeypatch.setattr(
        lifetime_lock, "_require_lock_fd_matches_path", lambda *_args: None
    )
    monkeypatch.setattr(lifetime_lock, "_close_lock_file", fake_close)

    first_cfg = _config(tmp_path / "first")
    other_cfg = _config(tmp_path / "other")
    first = lifetime_lock.acquire_runner_process_lifetime_lock(first_cfg)
    with pytest.raises(lifetime_lock.RunnerProcessLifetimeLockError) as exc_info:
        lifetime_lock.acquire_runner_process_lifetime_lock(first_cfg)
    assert exc_info.value.reason_code == lifetime_lock.RUNNER_PROCESS_LIFETIME_LOCK_HELD
    assert exc_info.value.exit_status == RUNNER_PROCESS_LIFETIME_LOCK_HELD_EXIT_STATUS

    other = lifetime_lock.acquire_runner_process_lifetime_lock(other_cfg)
    first.release()
    replacement = lifetime_lock.acquire_runner_process_lifetime_lock(first_cfg)

    replacement.release()
    other.release()
    assert not held_paths


def test_non_contention_lock_error_fails_closed_as_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    closed: list[int] = []
    monkeypatch.setattr(lifetime_lock, "_open_lock_file", lambda _path: 41)
    monkeypatch.setattr(
        lifetime_lock,
        "_try_lock_file",
        lambda _fd: (_ for _ in ()).throw(OSError(errno.EIO, "broken")),
    )
    monkeypatch.setattr(lifetime_lock, "_close_lock_file", closed.append)

    with pytest.raises(lifetime_lock.RunnerProcessLifetimeLockError) as exc_info:
        lifetime_lock.acquire_runner_process_lifetime_lock(_config(tmp_path))

    assert (
        exc_info.value.reason_code
        == lifetime_lock.RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE
    )
    assert (
        exc_info.value.exit_status
        == RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE_EXIT_STATUS
    )
    assert closed == [41]


def test_lock_rejects_stdio_fd_and_closes_it(
    tmp_path: Path,
    monkeypatch,
) -> None:
    closed: list[int] = []
    monkeypatch.setattr(lifetime_lock, "_open_lock_file", lambda _path: 2)
    monkeypatch.setattr(
        lifetime_lock,
        "_try_lock_file",
        lambda _fd: pytest.fail("stdio FD must be rejected before flock"),
    )
    monkeypatch.setattr(lifetime_lock, "_close_lock_file", closed.append)

    with pytest.raises(lifetime_lock.RunnerProcessLifetimeLockError) as exc_info:
        lifetime_lock.acquire_runner_process_lifetime_lock(_config(tmp_path))

    assert (
        exc_info.value.reason_code
        == lifetime_lock.RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE
    )
    assert closed == [2]


@pytest.mark.parametrize("error_number", [errno.EACCES, errno.ENOENT])
def test_lock_open_errors_are_unavailable_not_contention(
    tmp_path: Path,
    monkeypatch,
    error_number: int,
) -> None:
    monkeypatch.setattr(
        lifetime_lock,
        "_open_lock_file",
        lambda _path: (_ for _ in ()).throw(OSError(error_number, "open failed")),
    )

    with pytest.raises(lifetime_lock.RunnerProcessLifetimeLockError) as exc_info:
        lifetime_lock.acquire_runner_process_lifetime_lock(_config(tmp_path))

    assert (
        exc_info.value.reason_code
        == lifetime_lock.RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE
    )
    assert (
        exc_info.value.exit_status
        == RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE_EXIT_STATUS
    )


@pytest.mark.parametrize(
    ("fd_mode", "path_mode", "fd_identity", "path_identity"),
    [
        (stat.S_IFIFO | 0o600, stat.S_IFREG | 0o600, (1, 2), (1, 2)),
        (stat.S_IFREG | 0o600, stat.S_IFLNK | 0o777, (1, 2), (1, 2)),
        (stat.S_IFREG | 0o600, stat.S_IFREG | 0o600, (1, 2), (1, 3)),
    ],
)
def test_lock_fd_requires_regular_matching_stable_path(
    tmp_path: Path,
    monkeypatch,
    fd_mode: int,
    path_mode: int,
    fd_identity: tuple[int, int],
    path_identity: tuple[int, int],
) -> None:
    fd_stat = SimpleNamespace(
        st_mode=fd_mode,
        st_dev=fd_identity[0],
        st_ino=fd_identity[1],
    )
    path_stat = SimpleNamespace(
        st_mode=path_mode,
        st_dev=path_identity[0],
        st_ino=path_identity[1],
    )
    monkeypatch.setattr(lifetime_lock, "_stat_lock_fd", lambda _fd: fd_stat)
    monkeypatch.setattr(lifetime_lock, "_stat_lock_path", lambda _path: path_stat)

    with pytest.raises(OSError) as exc_info:
        lifetime_lock._require_lock_fd_matches_path(17, tmp_path / "runner.lock")

    assert exc_info.value.errno == errno.EINVAL


def test_exec_environment_exposes_only_held_fd_and_release_is_idempotent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    inheritable: list[tuple[int, bool]] = []
    closed: list[int] = []
    monkeypatch.setattr(
        lifetime_lock,
        "_set_lock_fd_inheritable",
        lambda fd, value: inheritable.append((fd, value)),
    )
    monkeypatch.setattr(lifetime_lock, "_close_lock_file", closed.append)
    lease = lifetime_lock.RunnerProcessLifetimeLock(
        path=tmp_path / "runner.lock", _fd=19
    )

    environment = lease.build_exec_environment({"PATH": "/bin"})

    assert environment == {"PATH": "/bin", RUNNER_PROCESS_LIFETIME_LOCK_FD_ENV: "19"}
    assert inheritable == [(19, True)]
    assert lease.mutation_subprocess_pass_fds() == (19,)
    lease.release()
    lease.release()
    assert closed == [19]
    with pytest.raises(lifetime_lock.RunnerProcessLifetimeLockError):
        lease.build_exec_environment({})
    with pytest.raises(lifetime_lock.RunnerProcessLifetimeLockError):
        lease.mutation_subprocess_pass_fds()


def test_lease_describes_exact_inode_and_rejects_config_path_drift(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _config(tmp_path)
    path = lifetime_lock.get_runner_process_lifetime_lock_path(cfg)
    checked: list[tuple[int, Path]] = []
    monkeypatch.setattr(
        lifetime_lock,
        "_require_lock_fd_matches_path",
        lambda fd, target: checked.append((fd, target)),
    )
    monkeypatch.setattr(
        lifetime_lock,
        "_stat_lock_fd",
        lambda _fd: SimpleNamespace(st_dev=17, st_ino=901),
    )
    monkeypatch.setattr(lifetime_lock, "_close_lock_file", lambda _fd: None)
    lease = lifetime_lock.RunnerProcessLifetimeLock(path=path, _fd=19)

    assert lease.describe_identity() == {
        "device": 17,
        "inode": 901,
        "path": path.absolute().as_posix(),
        "profile": RUNNER_PROCESS_LIFETIME_LOCK_PROFILE,
    }
    lease.require_matches_config(cfg)
    assert checked == [(19, path), (19, path)]

    with pytest.raises(lifetime_lock.RunnerProcessLifetimeLockError) as exc_info:
        lease.require_matches_config(_config(tmp_path / "other"))
    assert (
        exc_info.value.reason_code
        == lifetime_lock.RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE
    )
    lease.release()
    with pytest.raises(lifetime_lock.RunnerProcessLifetimeLockError):
        lease.describe_identity()


@pytest.mark.parametrize("raw_fd", ["", "0", "2", "+3", "03", " 3", "3 ", "three"])
def test_adopt_rejects_missing_or_noncanonical_fd(
    tmp_path: Path,
    raw_fd: str,
) -> None:
    with pytest.raises(lifetime_lock.RunnerProcessLifetimeLockError) as exc_info:
        lifetime_lock.adopt_runner_process_lifetime_lock(
            _config(tmp_path),
            environ={RUNNER_PROCESS_LIFETIME_LOCK_FD_ENV: raw_fd},
        )

    assert (
        exc_info.value.reason_code
        == lifetime_lock.RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE
    )


def test_adopt_exact_fd_validates_path_relocks_and_disables_inheritance(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[object] = []
    cfg = _config(tmp_path)
    monkeypatch.setattr(
        lifetime_lock,
        "_require_lock_fd_matches_path",
        lambda fd, path: calls.append(("match", fd, path)),
    )
    monkeypatch.setattr(
        lifetime_lock, "_try_lock_file", lambda fd: calls.append(("lock", fd))
    )
    monkeypatch.setattr(
        lifetime_lock,
        "_set_lock_fd_inheritable",
        lambda fd, value: calls.append(("inheritable", fd, value)),
    )
    monkeypatch.setattr(
        lifetime_lock, "_close_lock_file", lambda fd: calls.append(("close", fd))
    )
    monkeypatch.setenv(RUNNER_PROCESS_LIFETIME_LOCK_FD_ENV, "17")

    lease = lifetime_lock.adopt_runner_process_lifetime_lock(cfg)

    assert RUNNER_PROCESS_LIFETIME_LOCK_FD_ENV not in os.environ
    assert calls[:3] == [
        ("match", 17, lifetime_lock.get_runner_process_lifetime_lock_path(cfg)),
        ("lock", 17),
        ("match", 17, lifetime_lock.get_runner_process_lifetime_lock_path(cfg)),
    ]
    assert calls[3] == ("inheritable", 17, False)
    lease.release()
    assert calls[-1] == ("close", 17)


def test_adopt_closes_mismatched_inherited_fd(
    tmp_path: Path,
    monkeypatch,
) -> None:
    closed: list[int] = []
    monkeypatch.setattr(
        lifetime_lock,
        "_require_lock_fd_matches_path",
        lambda *_args: (_ for _ in ()).throw(OSError(errno.EINVAL, "mismatch")),
    )
    monkeypatch.setattr(lifetime_lock, "_close_lock_file", closed.append)

    with pytest.raises(lifetime_lock.RunnerProcessLifetimeLockError):
        lifetime_lock.adopt_runner_process_lifetime_lock(
            _config(tmp_path),
            environ={RUNNER_PROCESS_LIFETIME_LOCK_FD_ENV: "23"},
        )

    assert closed == [23]


@pytest.mark.skipif(sys.platform != "linux", reason="real flock proof is Linux only")
def test_real_flock_keeps_stable_inode_and_releases_on_close(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    first = lifetime_lock.acquire_runner_process_lifetime_lock(cfg)
    path = lifetime_lock.get_runner_process_lifetime_lock_path(cfg)
    identity = first.describe_identity()
    first.require_matches_config(cfg)

    assert identity == {
        "device": path.stat().st_dev,
        "inode": path.stat().st_ino,
        "path": path.absolute().as_posix(),
        "profile": RUNNER_PROCESS_LIFETIME_LOCK_PROFILE,
    }

    with pytest.raises(lifetime_lock.RunnerProcessLifetimeLockError) as exc_info:
        lifetime_lock.acquire_runner_process_lifetime_lock(cfg)
    assert exc_info.value.reason_code == lifetime_lock.RUNNER_PROCESS_LIFETIME_LOCK_HELD

    first.release()
    assert path.is_file()
    replacement = lifetime_lock.acquire_runner_process_lifetime_lock(cfg)
    replacement.release()
    assert path.is_file()


@pytest.mark.skipif(sys.platform != "linux", reason="requires Linux flock/exec semantics")
def test_real_flock_survives_exec_adoption_and_process_exit(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    state_path = Path(cfg.runtime_state_path)
    ready_path = tmp_path / "child-ready"
    release_path = tmp_path / "release-child"
    helper_path = tmp_path / "flock_exec_helper.py"
    repo_root = Path(__file__).resolve().parents[1]
    helper_path.write_text(
        _exec_lock_helper_source(),
        encoding="utf-8",
    )
    environment = dict(os.environ)
    environment.pop(RUNNER_PROCESS_LIFETIME_LOCK_FD_ENV, None)
    environment.pop("H2OMETA_LOCK_EXEC_TEST_PHASE", None)
    process = subprocess.Popen(
        [
            sys.executable,
            str(helper_path),
            str(repo_root),
            str(state_path),
            str(ready_path),
            str(release_path),
        ],
        env=environment,
        stderr=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not ready_path.exists() and process.poll() is None:
            if time.monotonic() >= deadline:
                break
            time.sleep(0.02)
        assert ready_path.read_text(encoding="utf-8") == "adopted\n"
        lock_path = lifetime_lock.get_runner_process_lifetime_lock_path(cfg)
        inode = lock_path.stat().st_ino
        with pytest.raises(lifetime_lock.RunnerProcessLifetimeLockError) as exc_info:
            lifetime_lock.acquire_runner_process_lifetime_lock(cfg)
        assert (
            exc_info.value.reason_code
            == lifetime_lock.RUNNER_PROCESS_LIFETIME_LOCK_HELD
        )
        release_path.write_text("release\n", encoding="utf-8")
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, f"stdout={stdout!r} stderr={stderr!r}"

        replacement = lifetime_lock.acquire_runner_process_lifetime_lock(cfg)
        replacement.release()
        assert lock_path.stat().st_ino == inode
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


@pytest.mark.skipif(sys.platform != "linux", reason="requires Linux inherited flock")
def test_mutation_child_keeps_flock_after_launcher_death(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    state_path = Path(cfg.runtime_state_path)
    child_ready = tmp_path / "mutation-child-ready"
    release_child = tmp_path / "release-mutation-child"
    helper_path = tmp_path / "mutation_parent.py"
    repo_root = Path(__file__).resolve().parents[1]
    helper_path.write_text(
        _mutation_parent_helper_source(_mutation_child_source()),
        encoding="utf-8",
    )
    parent = subprocess.Popen(
        [
            sys.executable,
            str(helper_path),
            str(repo_root),
            str(state_path),
            str(child_ready),
            str(release_child),
        ],
        stderr=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not child_ready.exists() and parent.poll() is None:
            if time.monotonic() >= deadline:
                break
            time.sleep(0.02)
        assert child_ready.read_text(encoding="utf-8") == "ready\n"
        parent.kill()
        stdout, stderr = parent.communicate(timeout=5)
        assert parent.returncode is not None, f"stdout={stdout!r} stderr={stderr!r}"

        with pytest.raises(lifetime_lock.RunnerProcessLifetimeLockError) as exc_info:
            lifetime_lock.acquire_runner_process_lifetime_lock(cfg)
        assert (
            exc_info.value.reason_code
            == lifetime_lock.RUNNER_PROCESS_LIFETIME_LOCK_HELD
        )

        release_child.write_text("release\n", encoding="utf-8")
        deadline = time.monotonic() + 10
        while True:
            try:
                replacement = lifetime_lock.acquire_runner_process_lifetime_lock(cfg)
                break
            except lifetime_lock.RunnerProcessLifetimeLockError as exc:
                if (
                    exc.reason_code != lifetime_lock.RUNNER_PROCESS_LIFETIME_LOCK_HELD
                    or time.monotonic() >= deadline
                ):
                    raise
                time.sleep(0.02)
        replacement.release()
    finally:
        release_child.write_text("release\n", encoding="utf-8")
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=5)
        deadline = time.monotonic() + 10
        while True:
            try:
                cleanup_lease = lifetime_lock.acquire_runner_process_lifetime_lock(cfg)
                cleanup_lease.release()
                break
            except lifetime_lock.RunnerProcessLifetimeLockError as exc:
                if (
                    exc.reason_code != lifetime_lock.RUNNER_PROCESS_LIFETIME_LOCK_HELD
                    or time.monotonic() >= deadline
                ):
                    raise
                time.sleep(0.02)


@pytest.mark.skipif(sys.platform != "linux", reason="requires Linux O_NOFOLLOW")
def test_real_lock_rejects_symlink_and_nonregular_path(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    lock_path = lifetime_lock.get_runner_process_lifetime_lock_path(cfg)
    lock_path.parent.mkdir(parents=True)
    target = tmp_path / "target"
    target.write_text("unchanged", encoding="utf-8")
    lock_path.symlink_to(target)

    with pytest.raises(lifetime_lock.RunnerProcessLifetimeLockError) as exc_info:
        lifetime_lock.acquire_runner_process_lifetime_lock(cfg)
    assert (
        exc_info.value.reason_code
        == lifetime_lock.RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE
    )
    assert target.read_text(encoding="utf-8") == "unchanged"

    lock_path.unlink()
    os.mkfifo(lock_path, 0o600)
    with pytest.raises(lifetime_lock.RunnerProcessLifetimeLockError) as exc_info:
        lifetime_lock.acquire_runner_process_lifetime_lock(cfg)
    assert (
        exc_info.value.reason_code
        == lifetime_lock.RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE
    )
