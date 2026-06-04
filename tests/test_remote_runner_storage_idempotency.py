from __future__ import annotations

from pathlib import Path

import pytest

from apps.remote_runner.errors import IdempotencyKeyReusedError
from apps.remote_runner.storage import create_run_record
from tests.helpers.reference_database import make_configured_remote_runner


def _run_spec(run_id: str) -> dict[str, str]:
    return {
        "runId": run_id,
        "projectId": "proj_idem",
        "pipelineId": "pipeline_idem",
        "pipelineVersion": "0.1.0",
        "runSpecVersion": "2026-04-21",
    }


def test_idempotency_key_reuse_with_different_payload_raises_domain_error(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)

    create_run_record(
        cfg,
        server_id="srv_idem",
        request_id="req_idem_first",
        run_spec=_run_spec("run_idem_first"),
        idempotency_key="idem_same",
        payload_hash="payload_hash_first",
    )

    with pytest.raises(IdempotencyKeyReusedError) as raised:
        create_run_record(
            cfg,
            server_id="srv_idem",
            request_id="req_idem_second",
            run_spec=_run_spec("run_idem_second"),
            idempotency_key="idem_same",
            payload_hash="payload_hash_second",
        )

    assert str(raised.value) == "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD"
    assert raised.value.status_code == 422
