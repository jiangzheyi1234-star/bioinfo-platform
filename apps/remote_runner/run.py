from __future__ import annotations

import ctypes
import logging
import os
from pathlib import Path
import socket
import sys

from core.contracts.runner_process_lifetime import (
    RUNNER_PROCESS_LIFETIME_LOCK_FD_ENV,
)
from core.contracts.runner_process_owner import (
    RUNNER_PROCESS_OWNER_FINGERPRINT_ENV,
    RUNNER_PROCESS_OWNER_LAUNCH_ID_ENV,
)

from .process_lifetime_lock import (
    RunnerProcessLifetimeLockError,
    adopt_runner_process_lifetime_lock,
)
from .process_owner import RunnerProcessOwnerError, adopt_runner_process_owner
from .process_pid_file import (
    RUNNER_PID_FILENAME,
    remove_runner_pid_file_if_owned,
    remove_runner_pid_file_path_if_owned,
)
from .runner_protocol_startup import REMOTE_CONFIG_ENV, load_remote_runner_startup_snapshot


LOGGER = logging.getLogger("h2ometa.remote_runner")
_MAX_INHERITED_FILE_DESCRIPTOR = (1 << 31) - 1


def _set_process_name(name: str = "h2ometa-remote") -> None:
    libc = ctypes.CDLL(None)
    encoded = name.encode("utf-8")[:15]
    result = libc.prctl(15, ctypes.c_char_p(encoded), 0, 0, 0)
    if result != 0:
        raise RuntimeError("REMOTE_RUNNER_PROCESS_NAME_FAILED")


def main() -> None:
    cfg, startup_binding = _load_startup_snapshot_for_owner_adoption()
    lifetime_lock = None
    try:
        lifetime_lock = adopt_runner_process_lifetime_lock(cfg)
        process_owner = adopt_runner_process_owner(
            cfg,
            startup_binding=startup_binding,
            lifetime_lock=lifetime_lock,
        )
    except (RunnerProcessLifetimeLockError, RunnerProcessOwnerError) as exc:
        try:
            remove_runner_pid_file_if_owned(cfg)
        except (OSError, UnicodeError, ValueError) as cleanup_exc:
            exc.add_note(
                "REMOTE_RUNNER_PID_CLEANUP_FAILED_AFTER_LOCK_ADOPTION: "
                f"{type(cleanup_exc).__name__}"
            )
        if lifetime_lock is not None:
            try:
                lifetime_lock.release()
            except OSError as release_exc:
                exc.add_note(
                    "REMOTE_RUNNER_LOCK_RELEASE_FAILED_AFTER_OWNER_ADOPTION: "
                    f"{type(release_exc).__name__}"
                )
        raise
    sock = None
    try:
        import uvicorn

        from core.logging_config import configure_structured_logging

        from .config import (
            bind_remote_runner_config_snapshot,
            ensure_runtime_layout,
            write_runtime_state,
        )

        bind_remote_runner_config_snapshot(cfg)
        configure_structured_logging()
        _set_process_name()
        ensure_runtime_layout(cfg)
        from .main import app

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((cfg.bind_host, int(cfg.bind_port)))
        sock.listen(2048)
        assigned_host, assigned_port = sock.getsockname()
        write_runtime_state(
            cfg,
            bind_host=str(assigned_host),
            bind_port=int(assigned_port),
            process_owner=process_owner,
        )
        LOGGER.info(
            "remote_runner_starting",
            extra={"host": str(assigned_host), "port": int(assigned_port)},
        )
        config = uvicorn.Config(
            app,
            fd=sock.fileno(),
            reload=False,
            workers=1,
            log_level="info",
            log_config=None,
        )
        server = uvicorn.Server(config)
        server.run(sockets=[sock])
    finally:
        _cleanup_runner_process(
            cfg=cfg,
            lifetime_lock=lifetime_lock,
            sock=sock,
        )


def _load_startup_snapshot_for_owner_adoption():
    try:
        return load_remote_runner_startup_snapshot()
    except (OSError, RuntimeError, UnicodeError, ValueError, TypeError) as exc:
        raw_config_path = str(os.environ.get(REMOTE_CONFIG_ENV) or "").strip()
        error = RunnerProcessOwnerError(
            path=Path(raw_config_path or "<remote-runner-startup-snapshot>")
        )
        error.add_note(
            "REMOTE_RUNNER_STARTUP_SNAPSHOT_REJECTED_AFTER_EXEC: "
            f"{type(exc).__name__}: {exc}"
        )
        try:
            remove_runner_pid_file_path_if_owned(
                Path(__file__).resolve().parents[1] / RUNNER_PID_FILENAME
            )
        except (OSError, UnicodeError, ValueError) as cleanup_exc:
            error.add_note(
                "REMOTE_RUNNER_PID_CLEANUP_FAILED_AFTER_STARTUP_SNAPSHOT_REJECTION: "
                f"{type(cleanup_exc).__name__}"
            )
        _scrub_inherited_runner_binding_environment(error)
        raise error from exc


def _scrub_inherited_runner_binding_environment(
    error: RunnerProcessOwnerError,
) -> None:
    raw_fd = str(os.environ.pop(RUNNER_PROCESS_LIFETIME_LOCK_FD_ENV, "") or "")
    os.environ.pop(RUNNER_PROCESS_OWNER_LAUNCH_ID_ENV, None)
    os.environ.pop(RUNNER_PROCESS_OWNER_FINGERPRINT_ENV, None)
    if (
        not raw_fd.isascii()
        or not raw_fd.isdecimal()
        or (len(raw_fd) > 1 and raw_fd.startswith("0"))
        or len(raw_fd) > 10
    ):
        return
    fd = int(raw_fd)
    if fd < 3 or fd > _MAX_INHERITED_FILE_DESCRIPTOR:
        return
    try:
        os.set_inheritable(fd, False)
    except OSError as exc:
        error.add_note(
            "REMOTE_RUNNER_LOCK_FD_SCRUB_FAILED_AFTER_STARTUP_SNAPSHOT_REJECTION: "
            f"{type(exc).__name__}"
        )


def _cleanup_runner_process(*, cfg, lifetime_lock, sock) -> None:
    cleanup_actions = (
        (
            "socket",
            lambda: sock.close() if sock is not None else None,
            (OSError,),
        ),
        (
            "pid_file",
            lambda: remove_runner_pid_file_if_owned(cfg),
            (OSError, UnicodeError, ValueError),
        ),
        ("lifetime_lock", lifetime_lock.release, (OSError,)),
    )
    for resource, action, expected_errors in cleanup_actions:
        try:
            action()
        except expected_errors as exc:
            LOGGER.warning(
                "remote_runner_cleanup_failed",
                extra={
                    "resource": resource,
                    "errorType": type(exc).__name__,
                },
            )


def cli_main() -> int:
    """Map lifetime-fence failures to systemd restart-prevention statuses."""

    try:
        main()
    except (RunnerProcessLifetimeLockError, RunnerProcessOwnerError) as exc:
        for note in getattr(exc, "__notes__", ()):
            print(note, file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return exc.exit_status
    return 0


if __name__ == "__main__":
    raise SystemExit(cli_main())
