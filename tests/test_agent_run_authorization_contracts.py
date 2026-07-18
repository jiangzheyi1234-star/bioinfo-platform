from __future__ import annotations

import copy
import re
from typing import Any

import pytest
from pydantic import ValidationError

from core.contracts.agent_run_authorization import (
    AGENT_RUN_AUTHORIZATION_RUN_IDEMPOTENCY_DOMAIN,
    AgentRunAuthorizationRead,
    AgentRunAuthorizationReceipt,
    AgentRunAuthorizationRequest,
    agent_run_authorization_command_hash,
    agent_run_authorization_receipt_hash,
    agent_run_authorization_run_idempotency_key,
)
from core.contracts.agent_contract_hash import agent_contract_hash


def _request_payload() -> dict[str, Any]:
    return {
        "expectedStateVersion": 5,
        "expectedPlanRevisionId": "agp_1",
        "expectedPlanGeneration": 1,
        "expectedPlanHash": "1" * 64,
        "expectedWorkflowRevisionId": "wfr_1",
        "expectedPreviewHash": "2" * 64,
        "expectedInputManifestDigest": "sha256:" + "3" * 64,
        "expectedRunSpecHash": "4" * 64,
        "expectedExecutionPolicyHash": "5" * 64,
        "expectedRuntimeProofHash": "6" * 64,
        "confirmation": "authorize-workflow-run",
        "requestId": "req_authorize_1",
        "idempotencyKey": "idem_authorize_1",
    }


def _receipt_payload() -> dict[str, Any]:
    request = AgentRunAuthorizationRequest.model_validate(_request_payload())
    payload: dict[str, Any] = {
        "authorizationId": "agra_1",
        "contractVersion": "agent-run-authorization.v1",
        "sessionId": "ags_authorize_1",
        "previewHash": request.expectedPreviewHash,
        "planRevisionId": request.expectedPlanRevisionId,
        "planGeneration": request.expectedPlanGeneration,
        "planHash": request.expectedPlanHash,
        "workflowRevisionId": request.expectedWorkflowRevisionId,
        "expectedStateVersion": request.expectedStateVersion,
        "inputManifestDigest": request.expectedInputManifestDigest,
        "runSpecHash": request.expectedRunSpecHash,
        "executionPolicyId": "agent-fastq-qc-execution.v1",
        "executionPolicyHash": request.expectedExecutionPolicyHash,
        "runtimeLockHash": "7" * 64,
        "runtimeProofHash": request.expectedRuntimeProofHash,
        "effectBudgetHash": "8" * 64,
        "runId": "run_agent_1",
        "scope": "submit_workflow_run",
        "confirmation": request.confirmation,
        "actor": "runner-user",
        "requestId": request.requestId,
        "idempotencyKey": request.idempotencyKey,
        "commandHash": agent_run_authorization_command_hash(
            "ags_authorize_1",
            "runner-user",
            request,
        ),
        "createdAt": "2026-07-18T12:30:00Z",
    }
    payload["receiptHash"] = agent_run_authorization_receipt_hash(payload)
    return payload


def test_run_authorization_contracts_have_exact_runtime_payloads_and_hashes() -> None:
    request = AgentRunAuthorizationRequest.model_validate(_request_payload())
    receipt = AgentRunAuthorizationReceipt.model_validate(_receipt_payload())

    assert request.runtime_payload() == _request_payload()
    assert receipt.runtime_payload() == _receipt_payload()
    for field in (
        "previewHash",
        "planHash",
        "runSpecHash",
        "executionPolicyHash",
        "runtimeLockHash",
        "runtimeProofHash",
        "effectBudgetHash",
        "commandHash",
        "receiptHash",
    ):
        assert re.fullmatch(r"[0-9a-f]{64}", str(receipt.runtime_payload()[field]))
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", receipt.inputManifestDigest)

    absent = AgentRunAuthorizationRead.model_validate(
        {
            "contractVersion": "agent-run-authorization-read.v1",
            "sessionId": receipt.sessionId,
            "state": "absent",
        }
    )
    present = AgentRunAuthorizationRead.model_validate(
        {
            "contractVersion": "agent-run-authorization-read.v1",
            "sessionId": receipt.sessionId,
            "state": "present",
            "receipt": receipt.runtime_payload(),
        }
    )
    assert absent.runtime_payload() == {
        "contractVersion": "agent-run-authorization-read.v1",
        "sessionId": receipt.sessionId,
        "state": "absent",
    }
    assert present.runtime_payload()["receipt"] == receipt.runtime_payload()


@pytest.mark.parametrize(
    "field",
    [
        "actor",
        "serverId",
        "reason",
        "runId",
        "runSpec",
        "graph",
        "upload",
        "uploadBinding",
        "execution",
        "toolParameters",
        "file",
    ],
)
def test_run_authorization_request_rejects_caller_authored_effect_fields(
    field: str,
) -> None:
    payload = _request_payload()
    payload[field] = {"unexpected": True}

    with pytest.raises(ValidationError) as exc_info:
        AgentRunAuthorizationRequest.model_validate(payload)

    assert any(
        error["type"] == "extra_forbidden" and error["loc"] == (field,)
        for error in exc_info.value.errors()
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("expectedStateVersion", "5"),
        ("expectedStateVersion", True),
        ("expectedPlanGeneration", "1"),
        ("expectedPlanGeneration", True),
    ],
)
def test_run_authorization_request_rejects_integer_coercion(
    field: str,
    value: object,
) -> None:
    payload = _request_payload()
    payload[field] = value
    with pytest.raises(ValidationError):
        AgentRunAuthorizationRequest.model_validate(payload)


def test_run_authorization_request_rejects_unsafe_integer_and_secret_like_value() -> (
    None
):
    unsafe = _request_payload()
    unsafe["expectedPlanGeneration"] = 9_007_199_254_740_993
    with pytest.raises(ValidationError, match="JSON_INTEGER_OUT_OF_SAFE_RANGE"):
        AgentRunAuthorizationRequest.model_validate(unsafe)

    secret = _request_payload()
    secret["requestId"] = "sk-abcdefghijklmnopqrstuvwxyz"
    with pytest.raises(
        ValidationError, match="AGENT_SESSION_SECRET_LIKE_VALUE_FORBIDDEN"
    ):
        AgentRunAuthorizationRequest.model_validate(secret)

    with pytest.raises(ValueError, match="AGENT_SESSION_SECRET_LIKE_VALUE_FORBIDDEN"):
        agent_run_authorization_command_hash(
            "ags_authorize_1",
            "sk-abcdefghijklmnopqrstuvwxyz",
            _request_payload(),
        )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("expectedPlanHash", "sha256:" + "1" * 64),
        ("expectedPreviewHash", "preview"),
        ("expectedInputManifestDigest", "3" * 64),
        ("expectedRunSpecHash", "sha256:" + "4" * 64),
        ("expectedExecutionPolicyHash", "g" * 64),
        ("expectedRuntimeProofHash", "6" * 63),
        ("confirmation", "submit-workflow-run"),
    ],
)
def test_run_authorization_request_rejects_noncanonical_hashes_and_confirmation(
    field: str,
    replacement: object,
) -> None:
    payload = _request_payload()
    payload[field] = replacement
    with pytest.raises(ValidationError):
        AgentRunAuthorizationRequest.model_validate(payload)


def test_run_authorization_command_hash_binds_session_actor_and_every_request() -> None:
    request = _request_payload()
    original = agent_run_authorization_command_hash(
        "ags_authorize_1",
        "runner-user",
        request,
    )
    assert re.fullmatch(r"[0-9a-f]{64}", original)
    assert original != agent_run_authorization_command_hash(
        "ags_authorize_2",
        "runner-user",
        request,
    )
    assert original != agent_run_authorization_command_hash(
        "ags_authorize_1",
        "other-runner-user",
        request,
    )

    changed = copy.deepcopy(request)
    changed["expectedRuntimeProofHash"] = "9" * 64
    assert original != agent_run_authorization_command_hash(
        "ags_authorize_1",
        "runner-user",
        changed,
    )


def test_run_authorization_run_idempotency_key_is_exact_and_deterministic() -> None:
    expected_digest = agent_contract_hash(
        "agent-run-authorization-run-idempotency.v1",
        {
            "sessionId": "ags_authorize_1",
            "authorizationId": "agra_1",
            "commandHash": "a" * 64,
        },
    )

    first = agent_run_authorization_run_idempotency_key(
        "ags_authorize_1",
        "agra_1",
        "a" * 64,
    )
    second = agent_run_authorization_run_idempotency_key(
        "ags_authorize_1",
        "agra_1",
        "a" * 64,
    )

    assert AGENT_RUN_AUTHORIZATION_RUN_IDEMPOTENCY_DOMAIN == (
        "agent-run-authorization-run-idempotency.v1"
    )
    assert first == f"agrunidem_v1_{expected_digest}"
    assert second == first
    assert re.fullmatch(r"agrunidem_v1_[0-9a-f]{64}", first)


@pytest.mark.parametrize(
    ("session_id", "authorization_id", "command_hash"),
    [
        ("ags_authorize_2", "agra_1", "a" * 64),
        ("ags_authorize_1", "agra_2", "a" * 64),
        ("ags_authorize_1", "agra_1", "b" * 64),
    ],
)
def test_run_authorization_run_idempotency_key_binds_every_field(
    session_id: str,
    authorization_id: str,
    command_hash: str,
) -> None:
    original = agent_run_authorization_run_idempotency_key(
        "ags_authorize_1",
        "agra_1",
        "a" * 64,
    )

    assert original != agent_run_authorization_run_idempotency_key(
        session_id,
        authorization_id,
        command_hash,
    )


@pytest.mark.parametrize(
    ("session_id", "authorization_id", "command_hash", "code"),
    [
        ("", "agra_1", "a" * 64, "SESSION_ID_REQUIRED"),
        (" \t", "agra_1", "a" * 64, "SESSION_ID_REQUIRED"),
        ("ags_authorize_1", "", "a" * 64, "AUTHORIZATION_ID_REQUIRED"),
        ("ags_authorize_1", "\n", "a" * 64, "AUTHORIZATION_ID_REQUIRED"),
        ("ags_authorize_1", "agra_1", "", "COMMAND_HASH_INVALID"),
        ("ags_authorize_1", "agra_1", "A" * 64, "COMMAND_HASH_INVALID"),
        ("ags_authorize_1", "agra_1", "sha256:" + "a" * 64, "COMMAND_HASH_INVALID"),
        ("ags_authorize_1", "agra_1", "a" * 63, "COMMAND_HASH_INVALID"),
        ("ags_authorize_1", "agra_1", "g" * 64, "COMMAND_HASH_INVALID"),
    ],
)
def test_run_authorization_run_idempotency_key_rejects_invalid_inputs(
    session_id: str,
    authorization_id: str,
    command_hash: str,
    code: str,
) -> None:
    with pytest.raises(ValueError, match=code):
        agent_run_authorization_run_idempotency_key(
            session_id,
            authorization_id,
            command_hash,
        )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("authorizationId", "agra_2"),
        ("sessionId", "ags_authorize_2"),
        ("previewHash", "a" * 64),
        ("planRevisionId", "agp_2"),
        ("planGeneration", 2),
        ("planHash", "b" * 64),
        ("workflowRevisionId", "wfr_2"),
        ("expectedStateVersion", 6),
        ("inputManifestDigest", "sha256:" + "c" * 64),
        ("runSpecHash", "d" * 64),
        ("executionPolicyId", "agent-fastq-qc-execution.v2"),
        ("executionPolicyHash", "e" * 64),
        ("runtimeLockHash", "f" * 64),
        ("runtimeProofHash", "a" * 64),
        ("effectBudgetHash", "b" * 64),
        ("runId", "run_agent_2"),
        ("actor", "other-runner-user"),
        ("requestId", "req_authorize_2"),
        ("idempotencyKey", "idem_authorize_2"),
        ("commandHash", "c" * 64),
        ("createdAt", "2026-07-18T12:30:01Z"),
    ],
)
def test_run_authorization_receipt_rejects_single_field_tampering(
    field: str,
    replacement: object,
) -> None:
    payload = copy.deepcopy(_receipt_payload())
    payload[field] = replacement

    with pytest.raises(
        ValidationError, match="AGENT_RUN_AUTHORIZATION_RECEIPT_HASH_MISMATCH"
    ):
        AgentRunAuthorizationReceipt.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("scope", "submit_arbitrary_effect"),
        ("confirmation", "approve-workflow-run"),
        ("receiptHash", "sha256:" + "a" * 64),
        ("inputManifestDigest", "a" * 64),
        ("runtimeLockHash", "sha256:" + "a" * 64),
    ],
)
def test_run_authorization_receipt_rejects_fixed_or_malformed_fields(
    field: str,
    replacement: object,
) -> None:
    payload = _receipt_payload()
    payload[field] = replacement
    with pytest.raises(ValidationError):
        AgentRunAuthorizationReceipt.model_validate(payload)


def test_run_authorization_read_rejects_inconsistent_state_identity_and_extras() -> (
    None
):
    receipt = _receipt_payload()
    with pytest.raises(ValidationError, match="ABSENT_HAS_RECEIPT"):
        AgentRunAuthorizationRead.model_validate(
            {
                "contractVersion": "agent-run-authorization-read.v1",
                "sessionId": receipt["sessionId"],
                "state": "absent",
                "receipt": receipt,
            }
        )
    with pytest.raises(ValidationError, match="PRESENT_REQUIRES_RECEIPT"):
        AgentRunAuthorizationRead.model_validate(
            {
                "contractVersion": "agent-run-authorization-read.v1",
                "sessionId": receipt["sessionId"],
                "state": "present",
            }
        )
    with pytest.raises(ValidationError, match="SESSION_ID_MISMATCH"):
        AgentRunAuthorizationRead.model_validate(
            {
                "contractVersion": "agent-run-authorization-read.v1",
                "sessionId": "ags_authorize_other",
                "state": "present",
                "receipt": receipt,
            }
        )
    with pytest.raises(ValidationError) as extra:
        AgentRunAuthorizationRead.model_validate(
            {
                "contractVersion": "agent-run-authorization-read.v1",
                "sessionId": receipt["sessionId"],
                "state": "absent",
                "run": None,
            }
        )
    assert extra.value.errors()[0]["type"] == "extra_forbidden"
