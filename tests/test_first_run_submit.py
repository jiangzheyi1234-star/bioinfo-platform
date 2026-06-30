from __future__ import annotations

import asyncio
import copy

import pytest
from fastapi import Response
from pydantic import ValidationError

from apps.api.submission_service import RunSubmission
from apps.api.workflow_first_run_routes import submit_first_run
from apps.api.workflow_first_run_submit_service import WorkflowFirstRunSubmitRequest
from apps.api.workflow_sample_data_service import MOVING_PICTURES_FILES, MOVING_PICTURES_PIPELINE_ID


def test_first_run_submit_prepares_sample_data_and_submits_canonical_run_spec(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_status(*, server_id: str | None = None, run_id: str | None = None, refresh: bool = False):
        assert server_id == "srv_first"
        assert run_id is None
        assert refresh is True
        return {"data": _status(stage="prepare_sample_data")}

    async def fake_prepare(pipeline_id, request):
        assert pipeline_id == MOVING_PICTURES_PIPELINE_ID
        assert request.serverId == "srv_first"
        return {"data": _sample_data_payload()}

    async def fake_submit(request):
        captured["request"] = request
        return RunSubmission(
            payload={
                "data": {
                    "runId": "run_first",
                    "status": "queued",
                    "stage": "submitted",
                    "requestId": "idem_first",
                },
                "location": "/api/v1/runs/run_first",
                "retryAfter": 2,
                "requestId": "idem_first",
            },
            headers={
                "Location": "/api/v1/runs/run_first",
                "Retry-After": "2",
                "X-Request-Id": "idem_first",
            },
        )

    monkeypatch.setattr("apps.api.workflow_first_run_submit_service.build_first_run_status_from_request", fake_status)
    monkeypatch.setattr("apps.api.workflow_first_run_submit_service.prepare_workflow_sample_data_uploads", fake_prepare)
    monkeypatch.setattr("apps.api.workflow_first_run_submit_service.submit_run_from_request", fake_submit)

    response = Response()
    result = asyncio.run(
        submit_first_run(
            WorkflowFirstRunSubmitRequest(
                serverId="srv_first",
                confirmation="submit-first-run",
                idempotencyKey="idem_first",
                actor="tester",
            ),
            response,
        )
    )["data"]

    assert response.headers["location"] == "/api/v1/runs/run_first"
    assert response.headers["retry-after"] == "2"
    assert response.headers["x-request-id"] == "idem_first"
    assert result["schemaVersion"] == "h2ometa.first-run.submit.v1"
    assert result["status"] == "submitted"
    assert result["submittedRun"]["runId"] == "run_first"
    assert result["sampleData"]["prepProof"]["schemaVersion"] == "h2ometa.workflow-sample-data-prep-proof.v1"

    request = captured["request"]
    run_spec = request.runSpec.model_dump(exclude_none=True)
    assert request.serverId == "srv_first"
    assert request.idempotencyKey == "idem_first"
    assert request.requestId == "idem_first"
    assert run_spec == {
        "projectId": "first-run-pilot",
        "pipelineId": MOVING_PICTURES_PIPELINE_ID,
        "inputs": [
            {"uploadId": "upl_metadata", "filename": "sample-metadata.tsv", "role": "metadata"},
            {"uploadId": "upl_barcodes", "filename": "barcodes.fastq.gz", "role": "barcodes"},
            {"uploadId": "upl_sequences", "filename": "sequences.fastq.gz", "role": "sequences"},
        ],
        "params": {},
        "sampleDataPrepProof": _sample_data_payload()["prepProof"],
    }


def test_first_run_submit_blocks_before_sample_prepare_when_status_is_not_submit_ready(monkeypatch) -> None:
    async def fake_status(*, server_id: str | None = None, run_id: str | None = None, refresh: bool = False):
        return {
            "data": _status(
                stage="runner_readiness",
                server_ready=False,
                next_action={
                    "code": "ENSURE_RUNNER",
                    "blockedCode": "FIRST_RUN_RUNNER_NOT_READY",
                    "detail": "runner readiness 未通过",
                    "label": "准备 runner",
                    "target": "#runner-readiness",
                },
            )
        }

    async def fail_prepare(*_args, **_kwargs):
        raise AssertionError("blocked first-run submit must not prepare sample data")

    async def fail_submit(*_args, **_kwargs):
        raise AssertionError("blocked first-run submit must not submit a run")

    monkeypatch.setattr("apps.api.workflow_first_run_submit_service.build_first_run_status_from_request", fake_status)
    monkeypatch.setattr("apps.api.workflow_first_run_submit_service.prepare_workflow_sample_data_uploads", fail_prepare)
    monkeypatch.setattr("apps.api.workflow_first_run_submit_service.submit_run_from_request", fail_submit)

    result = asyncio.run(
        submit_first_run(
            WorkflowFirstRunSubmitRequest(serverId="srv_first", confirmation="submit-first-run"),
            Response(),
        )
    )["data"]

    assert result["status"] == "blocked"
    assert result["nextAction"]["blockedCode"] == "FIRST_RUN_RUNNER_NOT_READY"
    assert result["firstRunStatus"]["stage"] == "runner_readiness"


def test_first_run_submit_blocks_when_submission_does_not_return_run_id(monkeypatch) -> None:
    async def fake_status(*, server_id: str | None = None, run_id: str | None = None, refresh: bool = False):
        return {"data": _status(stage="submit_run")}

    async def fake_prepare(pipeline_id, request):
        return {"data": _sample_data_payload()}

    async def fake_submit(request):
        return RunSubmission(
            payload={"data": {"status": "queued"}},
            headers={
                "Location": "/api/v1/runs/missing",
                "Retry-After": "2",
            },
        )

    monkeypatch.setattr("apps.api.workflow_first_run_submit_service.build_first_run_status_from_request", fake_status)
    monkeypatch.setattr("apps.api.workflow_first_run_submit_service.prepare_workflow_sample_data_uploads", fake_prepare)
    monkeypatch.setattr("apps.api.workflow_first_run_submit_service.submit_run_from_request", fake_submit)

    response = Response()
    result = asyncio.run(
        submit_first_run(
            WorkflowFirstRunSubmitRequest(serverId="srv_first", confirmation="submit-first-run"),
            response,
        )
    )["data"]

    assert result["status"] == "blocked"
    assert result["nextAction"]["code"] == "FIRST_RUN_SUBMISSION_RUN_ID_REQUIRED"
    assert result["sampleData"]["prepProof"]["schemaVersion"] == "h2ometa.workflow-sample-data-prep-proof.v1"
    assert "location" not in response.headers


def test_first_run_submit_request_rejects_client_run_spec() -> None:
    with pytest.raises(ValidationError):
        WorkflowFirstRunSubmitRequest(
            serverId="srv_first",
            confirmation="submit-first-run",
            runSpec={"pipelineId": MOVING_PICTURES_PIPELINE_ID},
        )


@pytest.mark.parametrize(
    ("sample_case", "expected_code"),
    [
        ("missing_role", "FIRST_RUN_SAMPLE_INPUTS_REQUIRED"),
        ("duplicate_role", "FIRST_RUN_SAMPLE_INPUTS_REQUIRED"),
        ("filename_mismatch", "FIRST_RUN_SAMPLE_INPUTS_REQUIRED"),
        ("checksum_failed", "FIRST_RUN_SAMPLE_INPUTS_INTEGRITY_MISMATCH"),
        ("missing_prep_proof", "FIRST_RUN_SAMPLE_PREP_PROOF_REQUIRED"),
    ],
)
def test_first_run_submit_blocks_invalid_official_sample_data(monkeypatch, sample_case: str, expected_code: str) -> None:
    async def fake_status(*, server_id: str | None = None, run_id: str | None = None, refresh: bool = False):
        return {"data": _status(stage="prepare_sample_data")}

    async def fake_prepare(pipeline_id, request):
        return {"data": _invalid_sample_data_payload(sample_case)}

    async def fail_submit(*_args, **_kwargs):
        raise AssertionError("invalid first-run sample data must not submit a run")

    monkeypatch.setattr("apps.api.workflow_first_run_submit_service.build_first_run_status_from_request", fake_status)
    monkeypatch.setattr("apps.api.workflow_first_run_submit_service.prepare_workflow_sample_data_uploads", fake_prepare)
    monkeypatch.setattr("apps.api.workflow_first_run_submit_service.submit_run_from_request", fail_submit)

    result = asyncio.run(
        submit_first_run(
            WorkflowFirstRunSubmitRequest(serverId="srv_first", confirmation="submit-first-run"),
            Response(),
        )
    )["data"]

    assert result["status"] == "blocked"
    assert result["nextAction"]["code"] == expected_code
    assert result["sampleData"]["pipelineId"] == MOVING_PICTURES_PIPELINE_ID


def _status(
    *,
    stage: str,
    server_ready: bool = True,
    next_action: dict | None = None,
) -> dict:
    return {
        "schemaVersion": "h2ometa.first-run.status.v1",
        "serverId": "srv_first",
        "status": "blocked",
        "stage": stage,
        "nextAction": next_action
        or {
            "code": "SUBMIT_RUN",
            "detail": "官方 Moving Pictures 16S 样例数据已就绪，提交首跑运行。",
            "label": "提交运行",
            "target": "#sample-data",
        },
        "evidence": {
            "server": {"ready": server_ready},
            "execution": {"ready": server_ready},
            "workflow": {"ready": server_ready, "pipelineId": MOVING_PICTURES_PIPELINE_ID},
            "sampleCache": {"status": "ready"},
        },
    }


def _invalid_sample_data_payload(sample_case: str) -> dict:
    payload = copy.deepcopy(_sample_data_payload())
    items = payload["items"]
    if sample_case == "missing_role":
        payload["items"] = [item for item in items if item["role"] != "sequences"]
    elif sample_case == "duplicate_role":
        duplicate = copy.deepcopy(items[0])
        duplicate["uploadId"] = "upl_metadata_duplicate"
        payload["items"] = [*items, duplicate]
    elif sample_case == "filename_mismatch":
        items[0]["filename"] = "unexpected-metadata.tsv"
    elif sample_case == "checksum_failed":
        items[0]["integrityStatus"] = "failed"
    elif sample_case == "missing_prep_proof":
        payload.pop("prepProof", None)
    else:
        raise AssertionError(f"unknown sample case {sample_case}")
    return payload


def _sample_data_payload() -> dict:
    items = []
    for sample in MOVING_PICTURES_FILES:
        upload_id = f"upl_{sample.role}"
        prep_proof = {
            "schemaVersion": "h2ometa.workflow-sample-data-prep-proof.v1",
            "role": sample.role,
            "filename": sample.filename,
            "sourceUrl": sample.url,
            "sha256": sample.expected_sha256,
            "expectedSha256": sample.expected_sha256,
            "expectedSizeBytes": sample.expected_size_bytes,
            "cacheStatus": "hit",
            "downloadStatus": "skipped-cache-hit",
        }
        items.append(
            {
                "uploadId": upload_id,
                "filename": sample.filename,
                "role": sample.role,
                "sha256": sample.expected_sha256,
                "expectedSha256": sample.expected_sha256,
                "expectedSizeBytes": sample.expected_size_bytes,
                "integrityStatus": "passed",
                "prepProof": prep_proof,
            }
        )
    return {
        "pipelineId": MOVING_PICTURES_PIPELINE_ID,
        "source": "QIIME 2 Moving Pictures tutorial",
        "items": items,
        "prepProof": {
            "schemaVersion": "h2ometa.workflow-sample-data-prep-proof.v1",
            "source": "QIIME 2 Moving Pictures tutorial",
            "cachePolicy": "verified-sha256-local-cache",
            "items": [item["prepProof"] for item in items],
        },
    }
