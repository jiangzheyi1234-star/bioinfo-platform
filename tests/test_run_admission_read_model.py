from __future__ import annotations

import json

from apps.remote_runner.run_admission_read_model import admission_summary_from_job_row


def test_admission_summary_redacts_raw_wait_reason_details() -> None:
    summary = admission_summary_from_job_row(
        {
            "job_id": "job_demo",
            "state": "queued",
            "queue_name": "default",
            "available_at": "2026-06-24T00:00:00Z",
            "wait_reason_json": json.dumps(
                {
                    "code": "ADMISSION_SLOT_BUSY",
                    "slotId": "worker-slot-secret",
                    "token": "raw-secret",
                }
            ),
            "attempt_count": 0,
            "max_attempts": 3,
            "dead_lettered_at": None,
            "updated_at": "2026-06-24T00:00:01Z",
        }
    )

    assert summary["waitReason"] == {
        "code": "ADMISSION_SLOT_BUSY",
        "slotIdPresent": True,
    }
    assert "worker-slot-secret" not in repr(summary)
    assert "raw-secret" not in repr(summary)


def test_admission_summary_does_not_echo_unknown_wait_reason_code() -> None:
    summary = admission_summary_from_job_row(
        {
            "job_id": "job_demo",
            "state": "queued",
            "queue_name": "default",
            "available_at": "2026-06-24T00:00:00Z",
            "wait_reason_json": json.dumps(
                {
                    "code": "INTERNAL_DATABASE_PASSWORD_ROTATION_WAIT",
                    "detail": "secret-internal-detail",
                }
            ),
            "attempt_count": 0,
            "max_attempts": 3,
            "dead_lettered_at": None,
            "updated_at": "2026-06-24T00:00:01Z",
        }
    )

    assert summary["waitReasonCode"] == "ADMISSION_WAIT_UNSUPPORTED"
    assert summary["waitReason"] == {"code": "ADMISSION_WAIT_UNSUPPORTED"}
    assert "INTERNAL_DATABASE_PASSWORD_ROTATION_WAIT" not in repr(summary)
    assert "secret-internal-detail" not in repr(summary)
