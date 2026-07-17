"""Linux advisory lock held for the complete remote-runner process lifetime."""

from __future__ import annotations

from dataclasses import dataclass, field
import errno
import os
from pathlib import Path
import stat
from typing import Mapping, Protocol

from core.contracts.runner_process_lifetime import (
    RUNNER_PROCESS_LIFETIME_LOCK_FILENAME,
    RUNNER_PROCESS_LIFETIME_LOCK_FD_ENV,
    RUNNER_PROCESS_LIFETIME_LOCK_HELD_EXIT_STATUS,
    RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE_EXIT_STATUS,
)


RUNNER_PROCESS_LIFETIME_LOCK_HELD = "REMOTE_RUNNER_PROCESS_LIFETIME_LOCK_HELD"
RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE = (
    "REMOTE_RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE"
)


class ProcessLifetimeLockConfig(Protocol):
    runtime_state_path: str


class RunnerProcessLifetimeLockError(RuntimeError):
    def __init__(self, *, reason_code: str, path: Path) -> None:
        super().__init__(f"{reason_code}: {path}")
        self.reason_code = reason_code
        self.exit_status = (
            RUNNER_PROCESS_LIFETIME_LOCK_HELD_EXIT_STATUS
            if reason_code == RUNNER_PROCESS_LIFETIME_LOCK_HELD
            else RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE_EXIT_STATUS
        )
        self.path = path


@dataclass(slots=True)
class RunnerProcessLifetimeLock:
    """A held lock FD. The stable lock file itself must never be unlinked."""

    path: Path
    _fd: int
    _released: bool = field(default=False, init=False)

    @property
    def released(self) -> bool:
        return self._released

    def build_exec_environment(
        self,
        environ: Mapping[str, str],
    ) -> dict[str, str]:
        """Expose only this exact FD to the immediate ``execve`` target."""

        if self._released:
            raise RunnerProcessLifetimeLockError(
                reason_code=RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE,
                path=self.path,
            )
        result = dict(environ)
        result[RUNNER_PROCESS_LIFETIME_LOCK_FD_ENV] = str(self._fd)
        _set_lock_fd_inheritable(self._fd, True)
        return result

    def mutation_subprocess_pass_fds(self) -> tuple[int, ...]:
        """Keep the fence held if a launcher-owned mutator outlives its parent."""

        if self._released:
            raise RunnerProcessLifetimeLockError(
                reason_code=RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE,
                path=self.path,
            )
        return (self._fd,)

    def release(self) -> None:
        if self._released:
            return
        fd = self._fd
        self._fd = -1
        self._released = True
        _close_lock_file(fd)


def get_runner_process_lifetime_lock_path(
    cfg: ProcessLifetimeLockConfig,
) -> Path:
    return Path(cfg.runtime_state_path).with_name(RUNNER_PROCESS_LIFETIME_LOCK_FILENAME)


def acquire_runner_process_lifetime_lock(
    cfg: ProcessLifetimeLockConfig,
) -> RunnerProcessLifetimeLock:
    """Acquire the stable, nonblocking Linux flock before runtime mutation."""

    path = get_runner_process_lifetime_lock_path(cfg)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = _open_lock_file(path)
    except OSError as exc:
        raise RunnerProcessLifetimeLockError(
            reason_code=RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE,
            path=path,
        ) from exc
    try:
        if fd < 3:
            raise OSError(errno.EBADF, "runner lifetime lock FD overlaps stdio")
        _try_lock_file(fd)
        _require_lock_fd_matches_path(fd, path)
    except OSError as exc:
        try:
            _close_lock_file(fd)
        except OSError:
            pass
        reason = (
            RUNNER_PROCESS_LIFETIME_LOCK_HELD
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK}
            else RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE
        )
        raise RunnerProcessLifetimeLockError(
            reason_code=reason,
            path=path,
        ) from exc
    return RunnerProcessLifetimeLock(path=path, _fd=fd)


def adopt_runner_process_lifetime_lock(
    cfg: ProcessLifetimeLockConfig,
    *,
    environ: Mapping[str, str] | None = None,
) -> RunnerProcessLifetimeLock:
    """Adopt and verify the exact lock FD inherited from the fixed launcher."""

    path = get_runner_process_lifetime_lock_path(cfg)
    env = os.environ if environ is None else environ
    raw_fd = str(env.get(RUNNER_PROCESS_LIFETIME_LOCK_FD_ENV) or "")
    if (
        not raw_fd.isascii()
        or not raw_fd.isdecimal()
        or raw_fd != str(int(raw_fd or 0))
    ):
        raise RunnerProcessLifetimeLockError(
            reason_code=RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE,
            path=path,
        )
    fd = int(raw_fd)
    if fd < 3:
        raise RunnerProcessLifetimeLockError(
            reason_code=RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE,
            path=path,
        )
    try:
        _require_lock_fd_matches_path(fd, path)
        _try_lock_file(fd)
        _require_lock_fd_matches_path(fd, path)
        _set_lock_fd_inheritable(fd, False)
    except OSError as exc:
        try:
            _close_lock_file(fd)
        except OSError:
            pass
        reason = (
            RUNNER_PROCESS_LIFETIME_LOCK_HELD
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK}
            else RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE
        )
        raise RunnerProcessLifetimeLockError(
            reason_code=reason,
            path=path,
        ) from exc
    if environ is None:
        os.environ.pop(RUNNER_PROCESS_LIFETIME_LOCK_FD_ENV, None)
    return RunnerProcessLifetimeLock(path=path, _fd=fd)


def _open_lock_file(path: Path) -> int:
    flags = os.O_RDWR | os.O_CREAT
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(str(path), flags, 0o600)
    try:
        _require_lock_fd_matches_path(fd, path)
        os.fchmod(fd, 0o600)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _try_lock_file(fd: int) -> None:
    try:
        import fcntl
    except ImportError as exc:  # pragma: no cover - production is Linux only.
        raise OSError(errno.ENOSYS, "Linux flock is unavailable") from exc
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _require_lock_fd_matches_path(fd: int, path: Path) -> None:
    fd_stat = _stat_lock_fd(fd)
    path_stat = _stat_lock_path(path)
    if (
        not stat.S_ISREG(fd_stat.st_mode)
        or not stat.S_ISREG(path_stat.st_mode)
        or (fd_stat.st_dev, fd_stat.st_ino) != (path_stat.st_dev, path_stat.st_ino)
    ):
        raise OSError(
            errno.EINVAL,
            "runner process lifetime lock FD does not match the stable path",
        )


def _stat_lock_fd(fd: int):
    return os.fstat(fd)


def _stat_lock_path(path: Path):
    return os.stat(path, follow_symlinks=False)


def _set_lock_fd_inheritable(fd: int, inheritable: bool) -> None:
    os.set_inheritable(fd, inheritable)


def _close_lock_file(fd: int) -> None:
    os.close(fd)


__all__ = [
    "RUNNER_PROCESS_LIFETIME_LOCK_HELD",
    "RUNNER_PROCESS_LIFETIME_LOCK_UNAVAILABLE",
    "RunnerProcessLifetimeLock",
    "RunnerProcessLifetimeLockError",
    "acquire_runner_process_lifetime_lock",
    "adopt_runner_process_lifetime_lock",
    "get_runner_process_lifetime_lock_path",
]
