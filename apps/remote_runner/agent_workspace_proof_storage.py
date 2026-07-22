"""Connection-scoped append-only storage for Agent workspace proofs."""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from collections.abc import Mapping
from typing import Any

from core.contracts.agent_workspace_proof import (
    AgentWorkspaceProofV1,
    agent_workspace_manifest_hash,
    agent_workspace_proof_hash,
    agent_workspace_proof_id,
)

from .agent_run_authorization_storage import (
    AgentRunAuthorizationStorageConflictError,
    fetch_agent_run_authorization_by_id_for_connection,
)
from .errors import WorkflowDesignRevisionConflictError
from .execution_resume_claim_preflight import (
    run_resume_execution_options_requested,
    validate_run_resume_claim_preflight,
)
from .execution_lease_time import execution_lease_expiry_is_future
from .workflow_revision_storage import fetch_workflow_revision_for_connection


_AUTHORITY_FACT_FIELDS = (
    "runId",
    "authorizationId",
    "workflowRevisionId",
    "workflowRevisionContentHash",
    "workflowRevisionManifestHash",
    "runSpecHash",
    "inputSnapshotHash",
    "toolAssetsHash",
    "runtimeLockHash",
    "runtimeProofHash",
)
_NEXT_BOUNDARIES = {
    "pre_dry_run": frozenset({"pre_run", "terminal"}),
    "pre_run": frozenset({"terminal"}),
    "terminal": frozenset(),
}


class AgentWorkspaceProofStorageConflictError(WorkflowDesignRevisionConflictError):
    """Raised when append-only workspace proof storage is inconsistent."""


def fetch_agent_workspace_proof_by_id_for_connection(
    connection: sqlite3.Connection,
    workspace_proof_id: str,
) -> dict[str, Any] | None:
    row = connection.execute(
        "SELECT * FROM agent_workspace_proofs WHERE workspace_proof_id = ?",
        (workspace_proof_id,),
    ).fetchone()
    return None if row is None else agent_workspace_proof_row_to_dict(row)


def fetch_latest_agent_workspace_proof_for_attempt_for_connection(
    connection: sqlite3.Connection,
    attempt_id: str,
    *,
    lease_generation: int | None = None,
) -> dict[str, Any] | None:
    """Fetch the newest proof owned by an attempt, never one that names it as source."""

    if lease_generation is None:
        row = connection.execute(
            """
            SELECT * FROM agent_workspace_proofs
            WHERE attempt_id = ?
            ORDER BY lease_generation DESC, process_ordinal DESC
            LIMIT 1
            """,
            (attempt_id,),
        ).fetchone()
    else:
        row = connection.execute(
            """
            SELECT * FROM agent_workspace_proofs
            WHERE attempt_id = ? AND lease_generation = ?
            ORDER BY process_ordinal DESC
            LIMIT 1
            """,
            (attempt_id, lease_generation),
        ).fetchone()
    return None if row is None else agent_workspace_proof_row_to_dict(row)


def fetch_terminal_agent_workspace_proof_for_attempt_for_connection(
    connection: sqlite3.Connection,
    attempt_id: str,
    *,
    lease_generation: int | None = None,
) -> dict[str, Any] | None:
    """Fetch the terminal proof owned by an attempt and optional lease generation."""

    if lease_generation is None:
        row = connection.execute(
            """
            SELECT * FROM agent_workspace_proofs
            WHERE attempt_id = ? AND process_boundary = 'terminal'
            ORDER BY lease_generation DESC, process_ordinal DESC
            LIMIT 1
            """,
            (attempt_id,),
        ).fetchone()
    else:
        row = connection.execute(
            """
            SELECT * FROM agent_workspace_proofs
            WHERE attempt_id = ? AND lease_generation = ?
              AND process_boundary = 'terminal'
            ORDER BY process_ordinal DESC
            LIMIT 1
            """,
            (attempt_id, lease_generation),
        ).fetchone()
    return None if row is None else agent_workspace_proof_row_to_dict(row)


def resolve_agent_workspace_proof_replay_for_connection(
    connection: sqlite3.Connection,
    proof: AgentWorkspaceProofV1 | Mapping[str, object],
) -> dict[str, Any] | None:
    """Resolve an exact attempt/lease/ordinal replay or reject a collision."""

    normalized = _normalize_and_verify_proof(proof)
    existing = _fetch_by_ordinal_for_connection(
        connection,
        attempt_id=normalized.attemptId,
        lease_generation=normalized.leaseGeneration,
        process_ordinal=normalized.processOrdinal,
    )
    if existing is None:
        return None
    return _require_exact_replay(existing, normalized)


def insert_agent_workspace_proof_for_connection(
    connection: sqlite3.Connection,
    proof: AgentWorkspaceProofV1 | Mapping[str, object],
) -> dict[str, Any]:
    """Insert a verified proof into the caller's existing writer transaction."""

    if not connection.in_transaction:
        raise RuntimeError("AGENT_WORKSPACE_PROOF_WRITER_TRANSACTION_REQUIRED")
    normalized = _normalize_and_verify_proof(proof)
    existing = _fetch_by_ordinal_for_connection(
        connection,
        attempt_id=normalized.attemptId,
        lease_generation=normalized.leaseGeneration,
        process_ordinal=normalized.processOrdinal,
    )
    replay: dict[str, Any] | None = None
    if existing is not None:
        replay = _require_exact_replay(existing, normalized)

    _require_insert_authority_and_chain(
        connection,
        normalized,
        exact_replay=replay is not None,
    )
    if replay is not None:
        return replay
    payload = normalized.runtime_payload()
    try:
        connection.execute(
            """
            INSERT INTO agent_workspace_proofs (
                workspace_proof_id, contract_version, run_id, authorization_id,
                attempt_id, lease_generation, source_attempt_id,
                process_boundary, process_ordinal, workflow_revision_id,
                workflow_revision_content_hash, workflow_revision_manifest_hash,
                run_spec_hash, input_snapshot_hash, tool_assets_hash,
                runtime_lock_hash, runtime_proof_hash, immutable_manifest_json,
                immutable_manifest_hash, snakemake_manifest_json,
                snakemake_manifest_hash, previous_proof_hash, event_id,
                created_at, proof_hash
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?
            )
            """,
            (
                normalized.workspaceProofId,
                normalized.contractVersion,
                normalized.runId,
                normalized.authorizationId,
                normalized.attemptId,
                normalized.leaseGeneration,
                normalized.sourceAttemptId or None,
                normalized.processBoundary,
                normalized.processOrdinal,
                normalized.workflowRevisionId,
                normalized.workflowRevisionContentHash,
                normalized.workflowRevisionManifestHash,
                normalized.runSpecHash,
                normalized.inputSnapshotHash,
                normalized.toolAssetsHash,
                normalized.runtimeLockHash,
                normalized.runtimeProofHash,
                _stable_json(payload["immutableManifest"]),
                normalized.immutableManifestHash,
                _stable_json(payload["snakemakeManifest"]),
                normalized.snakemakeManifestHash,
                normalized.previousProofHash,
                normalized.eventId,
                normalized.createdAt,
                normalized.proofHash,
            ),
        )
    except sqlite3.IntegrityError as exc:
        collision = _fetch_unique_collision_for_connection(connection, normalized)
        if collision is not None:
            return _require_exact_replay(
                collision,
                normalized,
                conflict_code="AGENT_WORKSPACE_PROOF_UNIQUE_CONFLICT",
            )
        raise AgentWorkspaceProofStorageConflictError(
            "AGENT_WORKSPACE_PROOF_STORAGE_CONFLICT"
        ) from exc
    return payload


def agent_workspace_proof_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Parse and cryptographically revalidate an immutable proof row."""

    try:
        immutable_manifest = _parse_manifest_json(row["immutable_manifest_json"])
        snakemake_manifest = _parse_manifest_json(row["snakemake_manifest_json"])
        payload: dict[str, object] = {
            "workspaceProofId": row["workspace_proof_id"],
            "contractVersion": row["contract_version"],
            "runId": row["run_id"],
            "authorizationId": row["authorization_id"],
            "attemptId": row["attempt_id"],
            "leaseGeneration": int(row["lease_generation"]),
            "sourceAttemptId": row["source_attempt_id"] or "",
            "processBoundary": row["process_boundary"],
            "processOrdinal": int(row["process_ordinal"]),
            "workflowRevisionId": row["workflow_revision_id"],
            "workflowRevisionContentHash": row["workflow_revision_content_hash"],
            "workflowRevisionManifestHash": row["workflow_revision_manifest_hash"],
            "runSpecHash": row["run_spec_hash"],
            "inputSnapshotHash": row["input_snapshot_hash"],
            "toolAssetsHash": row["tool_assets_hash"],
            "runtimeLockHash": row["runtime_lock_hash"],
            "runtimeProofHash": row["runtime_proof_hash"],
            "immutableManifest": immutable_manifest,
            "immutableManifestHash": row["immutable_manifest_hash"],
            "snakemakeManifest": snakemake_manifest,
            "snakemakeManifestHash": row["snakemake_manifest_hash"],
            "previousProofHash": row["previous_proof_hash"],
            "eventId": row["event_id"],
            "createdAt": row["created_at"],
            "proofHash": row["proof_hash"],
        }
        normalized = AgentWorkspaceProofV1.model_validate(payload)
        _require_proof_integrity(normalized)
    except AgentWorkspaceProofStorageConflictError:
        raise
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise AgentWorkspaceProofStorageConflictError(
            "AGENT_WORKSPACE_PROOF_STORED_PAYLOAD_INVALID"
        ) from exc
    return normalized.runtime_payload()


def _normalize_and_verify_proof(
    proof: AgentWorkspaceProofV1 | Mapping[str, object],
) -> AgentWorkspaceProofV1:
    payload = (
        proof.runtime_payload() if isinstance(proof, AgentWorkspaceProofV1) else proof
    )
    normalized = AgentWorkspaceProofV1.model_validate(payload)
    _require_proof_integrity(normalized)
    return normalized


def _require_insert_authority_and_chain(
    connection: sqlite3.Connection,
    proof: AgentWorkspaceProofV1,
    *,
    exact_replay: bool,
) -> None:
    """Validate durable authority, the live lease, and the append-only chain."""

    _require_authorization_binding(connection, proof)
    _require_workflow_revision_binding(connection, proof)
    expected_source = _require_run_and_active_attempt(connection, proof)
    _require_job_source_binding(proof, expected_source)

    latest = fetch_latest_agent_workspace_proof_for_attempt_for_connection(
        connection,
        proof.attemptId,
        lease_generation=proof.leaseGeneration,
    )
    if exact_replay:
        if latest is None or latest["proofHash"] != proof.proofHash:
            raise AgentWorkspaceProofStorageConflictError(
                "AGENT_WORKSPACE_PROOF_REPLAY_NOT_CHAIN_HEAD"
            )
        return
    if latest is None:
        if expected_source is not None:
            _require_resume_initial_proof(
                connection,
                proof,
                expected_source_generation=expected_source[1],
            )
        else:
            _require_fresh_initial_proof(proof)
        return
    _require_successor_proof(latest, proof)


def _require_authorization_binding(
    connection: sqlite3.Connection,
    proof: AgentWorkspaceProofV1,
) -> None:
    try:
        authorization = fetch_agent_run_authorization_by_id_for_connection(
            connection,
            proof.authorizationId,
        )
    except AgentRunAuthorizationStorageConflictError as exc:
        raise AgentWorkspaceProofStorageConflictError(
            "AGENT_WORKSPACE_PROOF_AUTHORIZATION_INVALID"
        ) from exc
    if authorization is None:
        raise AgentWorkspaceProofStorageConflictError(
            "AGENT_WORKSPACE_PROOF_AUTHORIZATION_NOT_FOUND"
        )
    input_digest = str(authorization["inputManifestDigest"])
    expected = {
        "runId": authorization["runId"],
        "workflowRevisionId": authorization["workflowRevisionId"],
        "runSpecHash": authorization["runSpecHash"],
        "inputSnapshotHash": input_digest.removeprefix("sha256:"),
        "runtimeLockHash": authorization["runtimeLockHash"],
        "runtimeProofHash": authorization["runtimeProofHash"],
    }
    observed = {
        "runId": proof.runId,
        "workflowRevisionId": proof.workflowRevisionId,
        "runSpecHash": proof.runSpecHash,
        "inputSnapshotHash": proof.inputSnapshotHash,
        "runtimeLockHash": proof.runtimeLockHash,
        "runtimeProofHash": proof.runtimeProofHash,
    }
    if observed != expected:
        raise AgentWorkspaceProofStorageConflictError(
            "AGENT_WORKSPACE_PROOF_AUTHORIZATION_BINDING_MISMATCH"
        )


def _require_workflow_revision_binding(
    connection: sqlite3.Connection,
    proof: AgentWorkspaceProofV1,
) -> None:
    try:
        revision = fetch_workflow_revision_for_connection(
            connection,
            proof.workflowRevisionId,
        )
    except WorkflowDesignRevisionConflictError as exc:
        raise AgentWorkspaceProofStorageConflictError(
            "AGENT_WORKSPACE_PROOF_WORKFLOW_REVISION_INVALID"
        ) from exc
    if revision is None:
        raise AgentWorkspaceProofStorageConflictError(
            "AGENT_WORKSPACE_PROOF_WORKFLOW_REVISION_NOT_FOUND"
        )
    manifest_hash = hashlib.sha256(
        _stable_json(revision["manifest"]).encode("utf-8")
    ).hexdigest()
    if (
        proof.workflowRevisionContentHash != revision["contentHash"]
        or proof.workflowRevisionManifestHash != manifest_hash
    ):
        raise AgentWorkspaceProofStorageConflictError(
            "AGENT_WORKSPACE_PROOF_WORKFLOW_REVISION_BINDING_MISMATCH"
        )


def _require_run_and_active_attempt(
    connection: sqlite3.Connection,
    proof: AgentWorkspaceProofV1,
) -> tuple[str, int] | None:
    run = connection.execute(
        "SELECT workflow_revision_id FROM runs WHERE run_id = ?",
        (proof.runId,),
    ).fetchone()
    if run is None:
        raise AgentWorkspaceProofStorageConflictError(
            "AGENT_WORKSPACE_PROOF_RUN_NOT_FOUND"
        )
    if str(run["workflow_revision_id"] or "") != proof.workflowRevisionId:
        raise AgentWorkspaceProofStorageConflictError(
            "AGENT_WORKSPACE_PROOF_RUN_REVISION_MISMATCH"
        )

    attempt = _fetch_attempt(connection, proof.attemptId)
    if attempt is None:
        raise AgentWorkspaceProofStorageConflictError(
            "AGENT_WORKSPACE_PROOF_TARGET_ATTEMPT_NOT_FOUND"
        )
    if (
        str(attempt["run_id"]) != proof.runId
        or int(attempt["lease_generation"]) != proof.leaseGeneration
    ):
        raise AgentWorkspaceProofStorageConflictError(
            "AGENT_WORKSPACE_PROOF_TARGET_ATTEMPT_MISMATCH"
        )
    job = connection.execute(
        "SELECT run_id, state, execution_options_json FROM run_jobs WHERE job_id = ?",
        (attempt["job_id"],),
    ).fetchone()
    if (
        job is None
        or str(job["run_id"]) != proof.runId
        or str(job["state"]) != "claimed"
        or str(attempt["state"]) != "running"
    ):
        raise AgentWorkspaceProofStorageConflictError(
            "AGENT_WORKSPACE_PROOF_CLAIM_STATE_MISMATCH"
        )
    lease = connection.execute(
        "SELECT attempt_id, lease_generation, expires_at, state "
        "FROM run_leases WHERE run_id = ?",
        (proof.runId,),
    ).fetchone()
    if (
        lease is None
        or str(lease["attempt_id"]) != proof.attemptId
        or int(lease["lease_generation"]) != proof.leaseGeneration
        or str(lease["state"]) != "active"
        or not execution_lease_expiry_is_future(lease["expires_at"])
    ):
        raise AgentWorkspaceProofStorageConflictError(
            "AGENT_WORKSPACE_PROOF_ACTIVE_LEASE_MISMATCH"
        )
    return _resume_source_from_claimed_job(job, proof)


def _resume_source_from_claimed_job(
    job: sqlite3.Row,
    proof: AgentWorkspaceProofV1,
) -> tuple[str, int] | None:
    try:
        execution_options = json.loads(str(job["execution_options_json"]))
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise AgentWorkspaceProofStorageConflictError(
            "AGENT_WORKSPACE_PROOF_EXECUTION_OPTIONS_INVALID"
        ) from exc
    if not isinstance(execution_options, dict):
        raise AgentWorkspaceProofStorageConflictError(
            "AGENT_WORKSPACE_PROOF_EXECUTION_OPTIONS_INVALID"
        )
    resume_requested = run_resume_execution_options_requested(execution_options)
    if not resume_requested:
        if "resumeScope" in execution_options:
            raise AgentWorkspaceProofStorageConflictError(
                "AGENT_WORKSPACE_PROOF_EXECUTION_OPTIONS_INVALID"
            )
        return None
    try:
        validate_run_resume_claim_preflight(
            execution_options,
            run_id=proof.runId,
            attempt_id=proof.attemptId,
            lease_generation=proof.leaseGeneration,
        )
        scope = execution_options["resumeScope"]
        source = scope["sourceAttempt"]
        source_attempt_id = str(source["attemptId"])
        source_generation = int(source["leaseGeneration"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AgentWorkspaceProofStorageConflictError(
            "AGENT_WORKSPACE_PROOF_EXECUTION_OPTIONS_INVALID"
        ) from exc
    return source_attempt_id, source_generation


def _require_job_source_binding(
    proof: AgentWorkspaceProofV1,
    expected_source: tuple[str, int] | None,
) -> None:
    expected_source_id = "" if expected_source is None else expected_source[0]
    if proof.sourceAttemptId != expected_source_id:
        raise AgentWorkspaceProofStorageConflictError(
            "AGENT_WORKSPACE_PROOF_JOB_RESUME_SOURCE_MISMATCH"
        )


def _require_fresh_initial_proof(proof: AgentWorkspaceProofV1) -> None:
    if (
        proof.processOrdinal != 1
        or proof.processBoundary != "pre_dry_run"
        or proof.previousProofHash is not None
        or proof.snakemakeManifest
    ):
        raise AgentWorkspaceProofStorageConflictError(
            "AGENT_WORKSPACE_PROOF_FRESH_INITIAL_INVALID"
        )


def _require_resume_initial_proof(
    connection: sqlite3.Connection,
    proof: AgentWorkspaceProofV1,
    *,
    expected_source_generation: int,
) -> None:
    if (
        proof.sourceAttemptId == proof.attemptId
        or proof.processOrdinal != 1
        or proof.processBoundary != "pre_dry_run"
    ):
        raise AgentWorkspaceProofStorageConflictError(
            "AGENT_WORKSPACE_PROOF_RESUME_INITIAL_INVALID"
        )
    source_attempt = _fetch_attempt(connection, proof.sourceAttemptId)
    if source_attempt is None:
        raise AgentWorkspaceProofStorageConflictError(
            "AGENT_WORKSPACE_PROOF_SOURCE_ATTEMPT_NOT_FOUND"
        )
    if str(source_attempt["run_id"]) != proof.runId:
        raise AgentWorkspaceProofStorageConflictError(
            "AGENT_WORKSPACE_PROOF_SOURCE_ATTEMPT_MISMATCH"
        )
    source_generation = int(source_attempt["lease_generation"])
    if source_generation != expected_source_generation:
        raise AgentWorkspaceProofStorageConflictError(
            "AGENT_WORKSPACE_PROOF_SOURCE_ATTEMPT_LEASE_MISMATCH"
        )
    source_terminal = fetch_terminal_agent_workspace_proof_for_attempt_for_connection(
        connection,
        proof.sourceAttemptId,
        lease_generation=source_generation,
    )
    source_latest = fetch_latest_agent_workspace_proof_for_attempt_for_connection(
        connection,
        proof.sourceAttemptId,
        lease_generation=source_generation,
    )
    if source_terminal is None or source_latest is None:
        raise AgentWorkspaceProofStorageConflictError(
            "AGENT_WORKSPACE_PROOF_SOURCE_TERMINAL_REQUIRED"
        )
    if source_latest["proofHash"] != source_terminal["proofHash"]:
        raise AgentWorkspaceProofStorageConflictError(
            "AGENT_WORKSPACE_PROOF_SOURCE_TERMINAL_NOT_LATEST"
        )
    if proof.previousProofHash != source_terminal["proofHash"]:
        raise AgentWorkspaceProofStorageConflictError(
            "AGENT_WORKSPACE_PROOF_SOURCE_PREVIOUS_HASH_MISMATCH"
        )
    _require_same_authority_facts(source_terminal, proof.runtime_payload())
    _require_same_immutable_manifest(source_terminal, proof.runtime_payload())
    if not _strict_json_equal(
        source_terminal["snakemakeManifest"],
        proof.runtime_payload()["snakemakeManifest"],
    ):
        raise AgentWorkspaceProofStorageConflictError(
            "AGENT_WORKSPACE_PROOF_SOURCE_CHECKPOINT_MISMATCH"
        )


def _require_successor_proof(
    latest: Mapping[str, object],
    proof: AgentWorkspaceProofV1,
) -> None:
    payload = proof.runtime_payload()
    if proof.processOrdinal != int(latest["processOrdinal"]) + 1:
        raise AgentWorkspaceProofStorageConflictError(
            "AGENT_WORKSPACE_PROOF_CHAIN_ORDINAL_INVALID"
        )
    if proof.previousProofHash != latest["proofHash"]:
        raise AgentWorkspaceProofStorageConflictError(
            "AGENT_WORKSPACE_PROOF_CHAIN_PREVIOUS_HASH_MISMATCH"
        )
    if proof.sourceAttemptId != latest["sourceAttemptId"]:
        raise AgentWorkspaceProofStorageConflictError(
            "AGENT_WORKSPACE_PROOF_CHAIN_SOURCE_ATTEMPT_MISMATCH"
        )
    _require_same_authority_facts(latest, payload)
    _require_same_immutable_manifest(latest, payload)
    allowed = _NEXT_BOUNDARIES[str(latest["processBoundary"])]
    if proof.processBoundary not in allowed:
        raise AgentWorkspaceProofStorageConflictError(
            "AGENT_WORKSPACE_PROOF_CHAIN_BOUNDARY_INVALID"
        )


def _require_same_authority_facts(
    expected: Mapping[str, object],
    observed: Mapping[str, object],
) -> None:
    if any(expected[field] != observed[field] for field in _AUTHORITY_FACT_FIELDS):
        raise AgentWorkspaceProofStorageConflictError(
            "AGENT_WORKSPACE_PROOF_CHAIN_AUTHORITY_MISMATCH"
        )


def _require_same_immutable_manifest(
    expected: Mapping[str, object],
    observed: Mapping[str, object],
) -> None:
    if expected["immutableManifestHash"] != observed[
        "immutableManifestHash"
    ] or not _strict_json_equal(
        expected["immutableManifest"], observed["immutableManifest"]
    ):
        raise AgentWorkspaceProofStorageConflictError(
            "AGENT_WORKSPACE_PROOF_CHAIN_IMMUTABLE_MANIFEST_MISMATCH"
        )


def _fetch_attempt(
    connection: sqlite3.Connection,
    attempt_id: str,
) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT run_id, job_id, lease_generation, state "
        "FROM run_attempts WHERE attempt_id = ?",
        (attempt_id,),
    ).fetchone()


def _strict_json_equal(left: object, right: object) -> bool:
    try:
        return _stable_json(left) == _stable_json(right)
    except (TypeError, ValueError):
        return False


def _require_proof_integrity(proof: AgentWorkspaceProofV1) -> None:
    payload = proof.runtime_payload()
    immutable_manifest_hash = agent_workspace_manifest_hash(
        payload["immutableManifest"]
    )
    if not hmac.compare_digest(immutable_manifest_hash, proof.immutableManifestHash):
        raise AgentWorkspaceProofStorageConflictError(
            "AGENT_WORKSPACE_PROOF_IMMUTABLE_MANIFEST_HASH_MISMATCH"
        )
    snakemake_manifest_hash = agent_workspace_manifest_hash(
        payload["snakemakeManifest"]
    )
    if not hmac.compare_digest(snakemake_manifest_hash, proof.snakemakeManifestHash):
        raise AgentWorkspaceProofStorageConflictError(
            "AGENT_WORKSPACE_PROOF_SNAKEMAKE_MANIFEST_HASH_MISMATCH"
        )
    expected_proof_hash = agent_workspace_proof_hash(payload)
    if not hmac.compare_digest(expected_proof_hash, proof.proofHash):
        raise AgentWorkspaceProofStorageConflictError(
            "AGENT_WORKSPACE_PROOF_HASH_MISMATCH"
        )
    expected_proof_id = agent_workspace_proof_id(expected_proof_hash)
    if expected_proof_id != proof.workspaceProofId:
        raise AgentWorkspaceProofStorageConflictError(
            "AGENT_WORKSPACE_PROOF_ID_MISMATCH"
        )


def _fetch_by_ordinal_for_connection(
    connection: sqlite3.Connection,
    *,
    attempt_id: str,
    lease_generation: int,
    process_ordinal: int,
) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT * FROM agent_workspace_proofs
        WHERE attempt_id = ? AND lease_generation = ? AND process_ordinal = ?
        """,
        (attempt_id, lease_generation, process_ordinal),
    ).fetchone()
    return None if row is None else agent_workspace_proof_row_to_dict(row)


def _fetch_unique_collision_for_connection(
    connection: sqlite3.Connection,
    proof: AgentWorkspaceProofV1,
) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT * FROM agent_workspace_proofs
        WHERE workspace_proof_id = ? OR proof_hash = ? OR event_id = ?
           OR (attempt_id = ? AND lease_generation = ? AND process_ordinal = ?)
        LIMIT 1
        """,
        (
            proof.workspaceProofId,
            proof.proofHash,
            proof.eventId,
            proof.attemptId,
            proof.leaseGeneration,
            proof.processOrdinal,
        ),
    ).fetchone()
    return None if row is None else agent_workspace_proof_row_to_dict(row)


def _require_exact_replay(
    existing: Mapping[str, object],
    proof: AgentWorkspaceProofV1,
    *,
    conflict_code: str = "AGENT_WORKSPACE_PROOF_ORDINAL_CONFLICT",
) -> dict[str, Any]:
    normalized = proof.runtime_payload()
    if dict(existing) != normalized:
        raise AgentWorkspaceProofStorageConflictError(conflict_code)
    return dict(existing)


def _parse_manifest_json(value: object) -> list[object]:
    if not isinstance(value, str):
        raise TypeError("manifest JSON must be text")
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        raise TypeError("manifest JSON must be an array")
    return parsed


def _stable_json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


__all__ = [
    "AgentWorkspaceProofStorageConflictError",
    "agent_workspace_proof_row_to_dict",
    "fetch_agent_workspace_proof_by_id_for_connection",
    "fetch_latest_agent_workspace_proof_for_attempt_for_connection",
    "fetch_terminal_agent_workspace_proof_for_attempt_for_connection",
    "insert_agent_workspace_proof_for_connection",
    "resolve_agent_workspace_proof_replay_for_connection",
]
