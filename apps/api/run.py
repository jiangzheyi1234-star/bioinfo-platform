"""Local runner for the FastAPI backend."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    os.environ.setdefault("H2OMETA_UTF8", "1")
    os.environ.setdefault("PYTHONUTF8", "1")
    uvicorn.run(
        "apps.api.main:app",
        host="127.0.0.1",
        port=8765,
        reload=False,
        workers=1,
        log_level="info",
    )


if __name__ == "__main__":
    main()
