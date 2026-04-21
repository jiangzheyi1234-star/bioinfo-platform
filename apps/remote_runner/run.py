from __future__ import annotations

import uvicorn

from .config import load_remote_runner_config
from .main import app


def main() -> None:
    cfg = load_remote_runner_config()
    uvicorn.run(
        app,
        host=cfg.bind_host,
        port=cfg.bind_port,
        reload=False,
        workers=1,
        log_level="info",
    )


if __name__ == "__main__":
    main()
