from __future__ import annotations


class RemoteRunnerAuthError(ValueError):
    status_code = 401


class RemoteRunnerAuthorizationError(ValueError):
    status_code = 403


class RemoteRunnerNotFoundError(ValueError):
    status_code = 404


class RemoteRunnerOperationBlockedError(ValueError):
    status_code = 409

    def __init__(self, code: str, payload: dict | None = None) -> None:
        super().__init__(code)
        self.payload = payload if payload is not None else {"code": code}


class RemoteRunnerReadinessError(ValueError):
    status_code = 503


class WorkflowDesignRevisionConflictError(ValueError):
    status_code = 409


class WorkflowToolNotReadyError(ValueError):
    status_code = 409


class IdempotencyKeyReusedError(ValueError):
    status_code = 422


class UploadTooLargeError(ValueError):
    status_code = 413
