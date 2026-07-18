"""Atomic creation of one Agent-authorized WorkflowRun and immutable receipt."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from core.contracts.agent_control_plane_namespace import (
    AGENT_CONTROL_PLANE_SERVER_ID,
)
from core.contracts.agent_fastq_qc_execution import (
    AGENT_FASTQ_QC_EXECUTION_POLICY_ID,
    agent_fastq_qc_execution_hash,
    agent_workflow_run_spec_hash,
    build_agent_fastq_qc_execution,
)
from core.contracts.agent_run_authorization import (
    AGENT_RUN_AUTHORIZATION_RESULT_CONTRACT_VERSION,
    AgentRunAuthorizationReceipt,
    AgentRunAuthorizationRequest,
    AgentRunAuthorizationResult,
    agent_run_authorization_command_hash,
    agent_run_authorization_receipt_hash,
    agent_run_authorization_run_idempotency_key,
)

from .agent_fastq_qc_execution_candidate import AgentFastqQcExecutionCandidate
from .agent_run_authorization_authority import (
    PreparedAgentRunAuthorizationAuthority,
    build_agent_run_authorization_preview_payload,
    prepare_agent_run_authorization_authority,
    read_agent_run_authorization_authority_for_connection,
    require_agent_run_authorization_authority_unchanged,
    require_fresh_agent_run_authorization_admission,
)
from .agent_run_authorization_origin import (
    require_agent_run_authorization_origin_for_connection,
)
from .agent_run_authorization_storage import (
    AgentRunAuthorizationStorageConflictError,
    insert_agent_run_authorization_for_connection,
    resolve_agent_run_authorization_replay_for_connection,
)
from .config import RemoteRunnerConfig
from .errors import WorkflowDesignRevisionConflictError
from .execution_query_storage import fetch_run_for_connection
from .storage_core import get_connection, now_iso
from .workflow_run_storage import create_run_record_for_connection


_PREVIEW_MISMATCH = "AGENT_RUN_AUTHORIZATION_PREVIEW_MISMATCH"
_CANDIDATE_INTEGRITY_MISMATCH = "AGENT_RUN_AUTHORIZATION_CANDIDATE_INTEGRITY_MISMATCH"
_INTERNAL_IDEMPOTENCY_COLLISION = (
    "AGENT_RUN_AUTHORIZATION_INTERNAL_IDEMPOTENCY_COLLISION"
)


def authorize_agent_workflow_run(
    cfg: RemoteRunnerConfig,
    session_id: str,
    request: AgentRunAuthorizationRequest | Mapping[str, object],
    *,
    actor: str,
) -> dict[str, Any]:
    """Authorize, create, bind, and verify exactly one Agent-owned run."""

    normalized_request = _normalize_request(request)
    command_hash = agent_run_authorization_command_hash(
        session_id,
        actor,
        normalized_request,
    )
    replay = _read_exact_replay(
        cfg,
        session_id=session_id,
        request=normalized_request,
        actor=actor,
        command_hash=command_hash,
    )
    if replay is not None:
        return replay

    prepared = prepare_agent_run_authorization_authority(
        cfg,
        session_id,
        actor=actor,
    )
    candidate, prepared_preview = _verified_candidate_and_preview(prepared)
    _require_request_matches_preview(normalized_request, prepared_preview)

    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            existing = resolve_agent_run_authorization_replay_for_connection(
                connection,
                session_id=session_id,
                idempotency_key=normalized_request.idempotencyKey,
                actor=actor,
                command_hash=command_hash,
            )
            if existing is not None:
                result = _build_replay_result(
                    connection,
                    receipt_payload=existing,
                    session_id=session_id,
                    request=normalized_request,
                    actor=actor,
                    command_hash=command_hash,
                )
                connection.rollback()
                return result

            current = read_agent_run_authorization_authority_for_connection(
                connection,
                session_id,
            )
            require_agent_run_authorization_authority_unchanged(
                prepared.snapshot,
                current,
            )
            require_fresh_agent_run_authorization_admission(current, actor=actor)
            candidate, current_preview = _verified_candidate_and_preview(
                PreparedAgentRunAuthorizationAuthority(
                    snapshot=current,
                    candidate=candidate,
                    preview=prepared_preview,
                )
            )
            _require_request_matches_preview(normalized_request, current_preview)

            authorization_id = _new_authorization_id()
            run_id = _new_run_id()
            created_at = _created_at()
            internal_key = agent_run_authorization_run_idempotency_key(
                session_id,
                authorization_id,
                command_hash,
            )
            _require_internal_idempotency_absent(connection, internal_key)
            run_create = create_run_record_for_connection(
                connection,
                server_id=AGENT_CONTROL_PLANE_SERVER_ID,
                actor=actor,
                request_id=normalized_request.requestId,
                run_spec=deepcopy(candidate.run_spec),
                idempotency_key=internal_key,
                payload_hash=candidate.run_spec_hash,
                run_id=run_id,
                submitted_at=created_at,
            )
            if not run_create.created:
                raise AgentRunAuthorizationStorageConflictError(
                    _INTERNAL_IDEMPOTENCY_COLLISION
                )

            receipt = _build_receipt(
                session_id=session_id,
                request=normalized_request,
                actor=actor,
                command_hash=command_hash,
                authorization_id=authorization_id,
                run_id=run_id,
                created_at=created_at,
                snapshot=current,
                candidate=candidate,
                preview=current_preview,
            )
            insert_agent_run_authorization_for_connection(connection, receipt)
            require_agent_run_authorization_origin_for_connection(
                connection,
                authorization_id,
            )
            run = fetch_run_for_connection(connection, run_id)
            if run is None:
                raise RuntimeError("AGENT_RUN_AUTHORIZATION_CREATED_RUN_MISSING")
            result = _build_result(
                receipt=receipt,
                run=run,
                idempotency_replay=False,
            )
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise


def _normalize_request(
    request: AgentRunAuthorizationRequest | Mapping[str, object],
) -> AgentRunAuthorizationRequest:
    payload = (
        request.runtime_payload()
        if isinstance(request, AgentRunAuthorizationRequest)
        else deepcopy(dict(request))
    )
    return AgentRunAuthorizationRequest.model_validate(payload)


def _read_exact_replay(
    cfg: RemoteRunnerConfig,
    *,
    session_id: str,
    request: AgentRunAuthorizationRequest,
    actor: str,
    command_hash: str,
) -> dict[str, Any] | None:
    with get_connection(cfg) as connection:
        connection.execute("BEGIN")
        try:
            existing = resolve_agent_run_authorization_replay_for_connection(
                connection,
                session_id=session_id,
                idempotency_key=request.idempotencyKey,
                actor=actor,
                command_hash=command_hash,
            )
            if existing is None:
                return None
            return _build_replay_result(
                connection,
                receipt_payload=existing,
                session_id=session_id,
                request=request,
                actor=actor,
                command_hash=command_hash,
            )
        finally:
            connection.rollback()


def _build_replay_result(
    connection: Any,
    *,
    receipt_payload: Mapping[str, object],
    session_id: str,
    request: AgentRunAuthorizationRequest,
    actor: str,
    command_hash: str,
) -> dict[str, Any]:
    receipt = AgentRunAuthorizationReceipt.model_validate(receipt_payload)
    _require_exact_replay(
        receipt,
        session_id=session_id,
        request=request,
        actor=actor,
        command_hash=command_hash,
    )
    require_agent_run_authorization_origin_for_connection(
        connection,
        receipt.authorizationId,
    )
    run = fetch_run_for_connection(connection, receipt.runId)
    if run is None:
        raise RuntimeError("AGENT_RUN_AUTHORIZATION_REPLAY_RUN_MISSING")
    return _build_result(receipt=receipt, run=run, idempotency_replay=True)


def _require_exact_replay(
    receipt: AgentRunAuthorizationReceipt,
    *,
    session_id: str,
    request: AgentRunAuthorizationRequest,
    actor: str,
    command_hash: str,
) -> None:
    expected = {
        "sessionId": session_id,
        "actor": actor,
        "commandHash": command_hash,
        "expectedStateVersion": request.expectedStateVersion,
        "planRevisionId": request.expectedPlanRevisionId,
        "planGeneration": request.expectedPlanGeneration,
        "planHash": request.expectedPlanHash,
        "workflowRevisionId": request.expectedWorkflowRevisionId,
        "previewHash": request.expectedPreviewHash,
        "inputManifestDigest": request.expectedInputManifestDigest,
        "runSpecHash": request.expectedRunSpecHash,
        "executionPolicyHash": request.expectedExecutionPolicyHash,
        "runtimeProofHash": request.expectedRuntimeProofHash,
        "confirmation": request.confirmation,
        "requestId": request.requestId,
        "idempotencyKey": request.idempotencyKey,
    }
    actual = {key: getattr(receipt, key) for key in expected}
    if not _strict_json_equal(actual, expected):
        raise AgentRunAuthorizationStorageConflictError(
            "AGENT_RUN_AUTHORIZATION_IDEMPOTENCY_CONFLICT"
        )


def _verified_candidate_and_preview(
    prepared: PreparedAgentRunAuthorizationAuthority,
) -> tuple[AgentFastqQcExecutionCandidate, dict[str, Any]]:
    candidate = deepcopy(prepared.candidate)
    try:
        expected_policy = build_agent_fastq_qc_execution().runtime_payload()
        run_spec_hash = agent_workflow_run_spec_hash(candidate.run_spec)
        execution = candidate.run_spec["execution"]
        run_execution_hash = agent_fastq_qc_execution_hash(execution)
        policy_hash = agent_fastq_qc_execution_hash(candidate.execution_policy)
        rebuilt_preview = build_agent_run_authorization_preview_payload(
            prepared.snapshot,
            candidate,
        )
        final_run_spec_hash = agent_workflow_run_spec_hash(candidate.run_spec)
        final_execution = candidate.run_spec["execution"]
        final_run_execution_hash = agent_fastq_qc_execution_hash(final_execution)
        final_policy_hash = agent_fastq_qc_execution_hash(candidate.execution_policy)
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(_CANDIDATE_INTEGRITY_MISMATCH) from exc
    if not all(
        (
            candidate.execution_policy_id == AGENT_FASTQ_QC_EXECUTION_POLICY_ID,
            run_spec_hash == candidate.run_spec_hash,
            run_execution_hash == candidate.execution_policy_hash,
            policy_hash == candidate.execution_policy_hash,
            _strict_json_equal(execution, expected_policy),
            _strict_json_equal(candidate.execution_policy, expected_policy),
            _strict_json_equal(rebuilt_preview, prepared.preview),
            final_run_spec_hash == candidate.run_spec_hash,
            final_run_execution_hash == candidate.execution_policy_hash,
            final_policy_hash == candidate.execution_policy_hash,
            _strict_json_equal(final_execution, expected_policy),
        )
    ):
        raise RuntimeError(_CANDIDATE_INTEGRITY_MISMATCH)
    return candidate, rebuilt_preview


def _require_request_matches_preview(
    request: AgentRunAuthorizationRequest,
    preview: Mapping[str, object],
) -> None:
    expected = {
        "stateVersion": request.expectedStateVersion,
        "planRevisionId": request.expectedPlanRevisionId,
        "planGeneration": request.expectedPlanGeneration,
        "planHash": request.expectedPlanHash,
        "workflowRevisionId": request.expectedWorkflowRevisionId,
        "previewHash": request.expectedPreviewHash,
        "inputManifestDigest": request.expectedInputManifestDigest,
        "runSpecHash": request.expectedRunSpecHash,
        "executionPolicyHash": request.expectedExecutionPolicyHash,
        "runtimeProofHash": request.expectedRuntimeProofHash,
    }
    actual = {key: preview.get(key) for key in expected}
    if not _strict_json_equal(actual, expected):
        raise WorkflowDesignRevisionConflictError(_PREVIEW_MISMATCH)


def _build_receipt(
    *,
    session_id: str,
    request: AgentRunAuthorizationRequest,
    actor: str,
    command_hash: str,
    authorization_id: str,
    run_id: str,
    created_at: str,
    snapshot: Any,
    candidate: AgentFastqQcExecutionCandidate,
    preview: Mapping[str, object],
) -> AgentRunAuthorizationReceipt:
    payload: dict[str, object] = {
        "authorizationId": authorization_id,
        "contractVersion": "agent-run-authorization.v1",
        "sessionId": session_id,
        "previewHash": preview["previewHash"],
        "planRevisionId": snapshot.plan["planRevisionId"],
        "planGeneration": snapshot.plan["planGeneration"],
        "planHash": snapshot.plan["planHash"],
        "workflowRevisionId": snapshot.workflow_revision["workflowRevisionId"],
        "expectedStateVersion": snapshot.session["stateVersion"],
        "inputManifestDigest": candidate.input_manifest_digest,
        "runSpecHash": candidate.run_spec_hash,
        "executionPolicyId": candidate.execution_policy_id,
        "executionPolicyHash": candidate.execution_policy_hash,
        "runtimeLockHash": candidate.runtime_lock_hash,
        "runtimeProofHash": candidate.runtime_proof_hash,
        "effectBudgetHash": preview["effectBudgetHash"],
        "runId": run_id,
        "scope": "submit_workflow_run",
        "confirmation": request.confirmation,
        "actor": actor,
        "requestId": request.requestId,
        "idempotencyKey": request.idempotencyKey,
        "commandHash": command_hash,
        "createdAt": created_at,
    }
    payload["receiptHash"] = agent_run_authorization_receipt_hash(payload)
    return AgentRunAuthorizationReceipt.model_validate(payload)


def _require_internal_idempotency_absent(connection: Any, key: str) -> None:
    row = connection.execute(
        """
        SELECT 1 FROM idempotency
        WHERE server_id = ? AND idempotency_key = ? LIMIT 1
        """,
        (AGENT_CONTROL_PLANE_SERVER_ID, key),
    ).fetchone()
    if row is not None:
        raise AgentRunAuthorizationStorageConflictError(_INTERNAL_IDEMPOTENCY_COLLISION)


def _build_result(
    *,
    receipt: AgentRunAuthorizationReceipt,
    run: Mapping[str, object],
    idempotency_replay: bool,
) -> dict[str, Any]:
    payload = {
        "contractVersion": AGENT_RUN_AUTHORIZATION_RESULT_CONTRACT_VERSION,
        "authorization": receipt.runtime_payload(),
        "run": {
            key: run[key]
            for key in (
                "runId",
                "requestId",
                "status",
                "stage",
                "stateVersion",
                "message",
                "submittedAt",
                "lastUpdatedAt",
            )
        },
        "idempotencyReplay": idempotency_replay,
    }
    return AgentRunAuthorizationResult.model_validate(payload).runtime_payload()


def _new_authorization_id() -> str:
    return f"agrauth_{uuid.uuid4().hex}"


def _new_run_id() -> str:
    return f"run_{uuid.uuid4().hex[:12]}"


def _created_at() -> str:
    return now_iso()


def _strict_json_equal(left: Any, right: Any) -> bool:
    try:
        return json.dumps(
            left,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ) == json.dumps(
            right,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        return False


__all__ = ["authorize_agent_workflow_run"]
