from __future__ import annotations

import ctypes
import socket

import uvicorn

from .config import load_remote_runner_config, write_runtime_state
from .main import app


def _set_process_name(name: str = "h2ometa-remote") -> None:
    libc = ctypes.CDLL(None)
    encoded = name.encode("utf-8")[:15]
    result = libc.prctl(15, ctypes.c_char_p(encoded), 0, 0, 0)
    if result != 0:
        raise RuntimeError("REMOTE_RUNNER_PROCESS_NAME_FAILED")


def main() -> None:
    _set_process_name()
    cfg = load_remote_runner_config()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((cfg.bind_host, int(cfg.bind_port)))
    sock.listen(2048)
    assigned_host, assigned_port = sock.getsockname()
    write_runtime_state(cfg, bind_host=str(assigned_host), bind_port=int(assigned_port))
    config = uvicorn.Config(app, fd=sock.fileno(), reload=False, workers=1, log_level="info")
    server = uvicorn.Server(config)
    server.run(sockets=[sock])


if __name__ == "__main__":
    main()
