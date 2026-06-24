from __future__ import annotations

import json
from typing import Any


def run_job_row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "jobId": row["job_id"],
        "runId": row["run_id"],
        "state": row["state"],
        "queueName": row["queue_name"],
        "priority": int(row["priority"]),
        "availableAt": row["available_at"],
        "waitReason": json_object(row["wait_reason_json"]),
        "attemptCount": int(row["attempt_count"]),
        "maxAttempts": int(row["max_attempts"]),
        "retryPolicy": json_object(row["retry_policy_json"]),
        "timeoutPolicy": json_object(row["timeout_policy_json"]),
        "executionOptions": json_object(row["execution_options_json"]),
        "deadLetteredAt": row["dead_lettered_at"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def json_object(value: str | None) -> dict[str, Any]:
    parsed = json.loads(value or "{}")
    return parsed if isinstance(parsed, dict) else {}
