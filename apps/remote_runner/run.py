from __future__ import annotations

import ctypes
import logging
import socket
import sys

from .process_lifetime_lock import (
    RunnerProcessLifetimeLockError,
    adopt_runner_process_lifetime_lock,
)
from .process_pid_file import remove_runner_pid_file_if_owned
from .runner_protocol_startup import load_remote_runner_config_from_startup_preflight


LOGGER = logging.getLogger("h2ometa.remote_runner")


def _set_process_name(name: str = "h2ometa-remote") -> None:
    libc = ctypes.CDLL(None)
    encoded = name.encode("utf-8")[:15]
    result = libc.prctl(15, ctypes.c_char_p(encoded), 0, 0, 0)
    if result != 0:
        raise RuntimeError("REMOTE_RUNNER_PROCESS_NAME_FAILED")


def main() -> None:
    cfg = load_remote_runner_config_from_startup_preflight()
    try:
        lifetime_lock = adopt_runner_process_lifetime_lock(cfg)
    except RunnerProcessLifetimeLockError as exc:
        try:
            remove_runner_pid_file_if_owned(cfg)
        except (OSError, UnicodeError, ValueError) as cleanup_exc:
            exc.add_note(
                "REMOTE_RUNNER_PID_CLEANUP_FAILED_AFTER_LOCK_ADOPTION: "
                f"{type(cleanup_exc).__name__}"
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
        try:
            if sock is not None:
                sock.close()
        finally:
            try:
                remove_runner_pid_file_if_owned(cfg)
            finally:
                lifetime_lock.release()


def cli_main() -> int:
    """Map lifetime-fence failures to systemd restart-prevention statuses."""

    try:
        main()
    except RunnerProcessLifetimeLockError as exc:
        for note in getattr(exc, "__notes__", ()):
            print(note, file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return exc.exit_status
    return 0


if __name__ == "__main__":
    raise SystemExit(cli_main())
