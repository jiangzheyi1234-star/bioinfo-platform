from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.remote_runner.client import RemoteRunnerClientError, RemoteRunnerConflictError
from core.remote_runner.manager import RemoteRunnerManagerError

from .errors import RuntimeConflictError, RuntimeServiceError


def call_remote_runner(func: Callable[..., Any], /, **kwargs: Any) -> Any:
    try:
        return func(**kwargs)
    except RuntimeServiceError:
        raise
    except RemoteRunnerConflictError as exc:
        raise RuntimeConflictError(str(exc), payload=exc.payload) from exc
    except RemoteRunnerClientError as exc:
        detail = str(exc) or "remote runner operation failed"
        raise RuntimeServiceError(detail, status_code=exc.status_code, detail=exc.detail) from exc
    except RemoteRunnerManagerError as exc:
        detail = str(exc) or "remote runner operation failed"
        raise RuntimeServiceError(detail, status_code=exc.status_code, detail=exc.detail) from exc
    except RuntimeError as exc:
        raise RuntimeServiceError(str(exc) or "remote runner operation failed") from exc
