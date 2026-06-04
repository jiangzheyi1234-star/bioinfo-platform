from __future__ import annotations


class RemoteRunnerAuthError(ValueError):
    status_code = 401


class RemoteRunnerNotFoundError(ValueError):
    status_code = 404


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
