"""Completion proof evidence contract for First Successful Run status."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from apps.api.workflow_first_run_completion_store import (
    FIRST_RUN_COMPLETION_PROOF_SCHEMA_VERSION,
    FirstRunCompletionProofStoreError,
    latest_first_run_completion_proof,
)
from apps.api.workflow_first_run_completion_proof_validation import (
    FIRST_RUN_COMPLETION_PROOF_INVALID,
    saved_first_run_completion_proof_invalid_detail,
)


FIRST_RUN_COMPLETION_PROOF_STORE_UNREADABLE = "FIRST_RUN_COMPLETION_PROOF_STORE_UNREADABLE"
_FIRST_RUN_COMPLETION_PROOF_BLOCKED_CODES = frozenset(
    (FIRST_RUN_COMPLETION_PROOF_INVALID, FIRST_RUN_COMPLETION_PROOF_STORE_UNREADABLE)
)

def first_run_completion_proof_evidence(
    proof: dict[str, Any] | None,
    *,
    server_id: str | None = None,
) -> dict[str, Any]:
    if not proof:
        return {"ready": False}
    if not isinstance(proof, dict):
        return _invalid("saved first-run completion proof must be an object")
    if proof.get("ready") is not True:
        if proof.get("blockedCode") in _FIRST_RUN_COMPLETION_PROOF_BLOCKED_CODES:
            return deepcopy(proof)
        return {"ready": False}
    schema_version = str(proof.get("schemaVersion") or "").strip()
    if schema_version != FIRST_RUN_COMPLETION_PROOF_SCHEMA_VERSION:
        return _invalid("saved first-run completion proof schema is unsupported")
    requested_server_id = str(server_id or "").strip()
    proof_server_id = str(proof.get("serverId") or "").strip()
    if requested_server_id and proof_server_id != requested_server_id:
        return _invalid("saved first-run completion proof belongs to a different server")
    invalid_detail = saved_first_run_completion_proof_invalid_detail(proof)
    if invalid_detail:
        return _invalid(invalid_detail)
    return deepcopy(proof)


def first_run_completion_proof_store_unreadable_evidence(exc: Exception) -> dict[str, Any]:
    detail = str(exc).strip() or "unknown store error"
    return {
        "ready": False,
        "blockedCode": FIRST_RUN_COMPLETION_PROOF_STORE_UNREADABLE,
        "detail": f"saved first-run completion proof store is unreadable: {detail}",
    }


def latest_first_run_completion_proof_evidence(*, server_id: str) -> dict[str, Any]:
    try:
        proof = latest_first_run_completion_proof(server_id=server_id)
    except FirstRunCompletionProofStoreError as exc:
        return first_run_completion_proof_store_unreadable_evidence(exc)
    return first_run_completion_proof_evidence(proof, server_id=server_id)


def _invalid(detail: str) -> dict[str, Any]:
    return {"ready": False, "blockedCode": FIRST_RUN_COMPLETION_PROOF_INVALID, "detail": detail}
