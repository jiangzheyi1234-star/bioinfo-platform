"""Local runner for the FastAPI backend."""

from __future__ import annotations

import logging
import os

import uvicorn

from core.logging_config import configure_structured_logging


LOGGER = logging.getLogger("h2ometa.local_api")


def main() -> None:
    os.environ.setdefault("H2OMETA_UTF8", "1")
    os.environ.setdefault("PYTHONUTF8", "1")
    configure_structured_logging()
    LOGGER.info("local_api_starting", extra={"host": "127.0.0.1", "port": 8765})
    uvicorn.run(
        "apps.api.main:app",
        host="127.0.0.1",
        port=8765,
        reload=False,
        workers=1,
        log_level="info",
        log_config=None,
        access_log=(
            os.environ.get("H2OMETA_API_ACCESS_LOG", "").lower()
            in {"1", "true", "yes", "on"}
        ),
    )


if __name__ == "__main__":
    main()
