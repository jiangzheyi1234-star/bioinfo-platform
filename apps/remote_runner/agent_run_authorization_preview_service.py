"""Read-only authorization preview for one Agent-owned workflow run."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from core.contracts.agent_effect_budget import agent_effect_budget_hash
from core.contracts.agent_fastq_qc import (
    AGENT_FASTQ_QC_ADAPTER_ID,
    AGENT_FASTQ_QC_ADAPTER_VERSION,
    AGENT_FASTQ_QC_MODEL_REF,
)
from core.contracts.agent_run_authorization_preview import (
    AGENT_RUN_AUTHORIZATION_PREVIEW_CONTRACT_VERSION,
    AgentRunAuthorizationPreview,
    agent_run_authorization_preview_hash,
)

from .agent_effect_budget_storage import fetch_agent_effect_budget_for_connection
from .agent_fastq_qc_execution_candidate import (
    AgentFastqQcExecutionCandidate,
    build_agent_fastq_qc_execution_candidate,
)
from .agent_plan_storage import require_active_agent_plan_for_connection
from .agent_run_authorization_storage import (
    count_agent_run_authorizations_for_connection,
    fetch_agent_run_authorization_by_session_for_connection,
)
from .agent_session_storage import require_agent_session_for_connection
from .config import RemoteRunnerConfig
from .errors import (
    RemoteRunnerAuthorizationError,
    WorkflowDesignRevisionConflictError,
)
from .route_utils import (
    authorized_config,
    data_response,
    remote_runner_principal,
    run_sync,
)
from .storage_core import get_connection
from .workflow_revision_storage import fetch_workflow_revision_for_connection


_EXPECTED_FASTQ_QC_PLANNER = {
    "adapterId": AGENT_FASTQ_QC_ADAPTER_ID,
    "adapterVersion": AGENT_FASTQ_QC_ADAPTER_VERSION,
    "modelRef": AGENT_FASTQ_QC_MODEL_REF,
}


@dataclass(frozen=True, slots=True)
class _PreviewAuthoritySnapshot:
    """All mutable ledgers that must stay stable while a candidate is built."""

    session: dict[str, Any]
    plan: dict[str, Any]
    workflow_revision: dict[str, Any]
    effect_budget: dict[str, Any] | None
    existing_binding: dict[str, Any] | None
    used_authorization_count: int

    def comparison_payload(self) -> dict[str, Any]:
        return {
            "session": self.session,
            "plan": self.plan,
            "workflowRevision": self.workflow_revision,
            "effectBudget": self.effect_budget,
            "existingBinding": self.existing_binding,
            "usedAuthorizationCount": self.used_authorization_count,
        }


def build_agent_run_authorization_preview(
    cfg: RemoteRunnerConfig,
    session_id: str,
    *,
    actor: str,
) -> dict[str, Any]:
    """Build a side-effect-free preview from two matching authority snapshots."""

    first = _read_preview_authority_snapshot(cfg, session_id)
    _require_preview_admission(first, actor=actor)

    # Runtime hashing, upload hashing, ToolRevision checks, and preflight must not
    # hold a SQLite transaction open.
    candidate = build_agent_fastq_qc_execution_candidate(
        cfg,
        session=deepcopy(first.session),
        plan=deepcopy(first.plan),
        workflow_revision=deepcopy(first.workflow_revision),
    )

    second = _read_preview_authority_snapshot(cfg, session_id)
    if not _strict_json_equal(
        first.comparison_payload(),
        second.comparison_payload(),
    ):
        raise WorkflowDesignRevisionConflictError(
            "AGENT_RUN_AUTHORIZATION_PREVIEW_AUTHORITY_CHANGED"
        )
    _require_preview_admission(second, actor=actor)
    return _preview_payload(second, candidate)


async def get_agent_run_authorization_preview_from_http(
    session_id: str,
    authorization: str | None,
) -> dict[str, Any]:
    """Authorize the remote principal and return the strict public projection."""

    cfg = authorized_config(
        authorization,
        action="agent_session.run_authorization_preview.read",
    )
    principal = remote_runner_principal(cfg)
    preview = await run_sync(
        build_agent_run_authorization_preview,
        cfg,
        session_id,
        actor=principal.actor,
    )
    return data_response(preview)


def _read_preview_authority_snapshot(
    cfg: RemoteRunnerConfig,
    session_id: str,
) -> _PreviewAuthoritySnapshot:
    """Read one coherent snapshot and immediately release its read transaction."""

    with get_connection(cfg) as connection:
        connection.execute("BEGIN")
        try:
            session = require_agent_session_for_connection(connection, session_id)
            resolved_session_id = session["sessionId"]
            plan = require_active_agent_plan_for_connection(connection, session)
            workflow_revision_id = session.get("workflowRevisionId")
            if not isinstance(workflow_revision_id, str):
                raise WorkflowDesignRevisionConflictError(
                    "AGENT_RUN_AUTHORIZATION_PREVIEW_WORKFLOW_REVISION_REQUIRED"
                )
            workflow_revision = fetch_workflow_revision_for_connection(
                connection,
                workflow_revision_id,
            )
            if workflow_revision is None:
                raise WorkflowDesignRevisionConflictError(
                    "AGENT_RUN_AUTHORIZATION_PREVIEW_WORKFLOW_REVISION_NOT_FOUND"
                )
            effect_budget = fetch_agent_effect_budget_for_connection(
                connection,
                resolved_session_id,
            )
            existing_binding = fetch_agent_run_authorization_by_session_for_connection(
                connection,
                resolved_session_id,
            )
            used_authorization_count = count_agent_run_authorizations_for_connection(
                connection,
                resolved_session_id,
            )
            return _PreviewAuthoritySnapshot(
                session=deepcopy(session),
                plan=deepcopy(plan),
                workflow_revision=deepcopy(workflow_revision),
                effect_budget=deepcopy(effect_budget),
                existing_binding=deepcopy(existing_binding),
                used_authorization_count=used_authorization_count,
            )
        finally:
            connection.rollback()


def _require_preview_admission(
    snapshot: _PreviewAuthoritySnapshot,
    *,
    actor: str,
) -> None:
    if (
        not isinstance(actor, str)
        or not actor
        or actor != actor.strip()
        or snapshot.session.get("createdBy") != actor
    ):
        raise RemoteRunnerAuthorizationError(
            "AGENT_RUN_AUTHORIZATION_PREVIEW_OWNER_MISMATCH"
        )

    proposal = snapshot.plan.get("proposal")
    proposal_planner = proposal.get("planner") if isinstance(proposal, dict) else None
    if not _strict_json_equal(
        snapshot.session.get("planner"),
        _EXPECTED_FASTQ_QC_PLANNER,
    ) or not _strict_json_equal(proposal_planner, _EXPECTED_FASTQ_QC_PLANNER):
        raise WorkflowDesignRevisionConflictError(
            "AGENT_RUN_AUTHORIZATION_PREVIEW_ADAPTER_UNSUPPORTED"
        )

    budget = snapshot.effect_budget
    if budget is None:
        raise WorkflowDesignRevisionConflictError(
            "AGENT_RUN_AUTHORIZATION_PREVIEW_EFFECT_BUDGET_REQUIRED"
        )
    if budget.get("sessionId") != snapshot.session.get("sessionId"):
        raise WorkflowDesignRevisionConflictError(
            "AGENT_RUN_AUTHORIZATION_PREVIEW_EFFECT_BUDGET_SESSION_MISMATCH"
        )
    if budget.get("actor") != actor:
        raise WorkflowDesignRevisionConflictError(
            "AGENT_RUN_AUTHORIZATION_PREVIEW_EFFECT_BUDGET_OWNER_MISMATCH"
        )
    if type(budget.get("maxRunSubmissions")) is not int or (
        budget["maxRunSubmissions"] != 1
    ):
        raise WorkflowDesignRevisionConflictError(
            "AGENT_RUN_AUTHORIZATION_PREVIEW_EFFECT_BUDGET_INVALID"
        )
    if snapshot.existing_binding is not None:
        raise WorkflowDesignRevisionConflictError(
            "AGENT_RUN_AUTHORIZATION_ALREADY_BOUND"
        )
    if type(snapshot.used_authorization_count) is not int or (
        snapshot.used_authorization_count < 0
    ):
        raise WorkflowDesignRevisionConflictError(
            "AGENT_RUN_AUTHORIZATION_PREVIEW_AUTHORIZATION_COUNT_INVALID"
        )
    if snapshot.used_authorization_count != 0:
        raise WorkflowDesignRevisionConflictError(
            "AGENT_RUN_AUTHORIZATION_PREVIEW_EFFECT_BUDGET_EXHAUSTED"
        )


def _preview_payload(
    snapshot: _PreviewAuthoritySnapshot,
    candidate: AgentFastqQcExecutionCandidate,
) -> dict[str, Any]:
    session = snapshot.session
    plan = snapshot.plan
    workflow_revision = snapshot.workflow_revision
    budget = snapshot.effect_budget
    if budget is None:
        raise WorkflowDesignRevisionConflictError(
            "AGENT_RUN_AUTHORIZATION_PREVIEW_EFFECT_BUDGET_REQUIRED"
        )

    payload: dict[str, Any] = {
        "contractVersion": AGENT_RUN_AUTHORIZATION_PREVIEW_CONTRACT_VERSION,
        "sessionId": session["sessionId"],
        "stateVersion": session["stateVersion"],
        "adapterId": _EXPECTED_FASTQ_QC_PLANNER["adapterId"],
        "adapterVersion": _EXPECTED_FASTQ_QC_PLANNER["adapterVersion"],
        "plannerModel": _EXPECTED_FASTQ_QC_PLANNER["modelRef"],
        "planRevisionId": plan["planRevisionId"],
        "planGeneration": plan["planGeneration"],
        "planHash": plan["planHash"],
        "workflowRevisionId": workflow_revision["workflowRevisionId"],
        "workflowRevisionContentHash": workflow_revision["contentHash"],
        "inputManifestDigest": candidate.input_manifest_digest,
        "runSpecHash": candidate.run_spec_hash,
        "executionPolicyId": candidate.execution_policy_id,
        "executionPolicyHash": candidate.execution_policy_hash,
        "executionPolicy": deepcopy(candidate.execution_policy),
        "runtimeLockHash": candidate.runtime_lock_hash,
        "runtimeProofHash": candidate.runtime_proof_hash,
        "effectBudgetHash": agent_effect_budget_hash(budget),
        "maxRunSubmissions": budget["maxRunSubmissions"],
        "usedRunSubmissions": snapshot.used_authorization_count,
        "remainingRunSubmissions": (
            budget["maxRunSubmissions"] - snapshot.used_authorization_count
        ),
        "tools": [deepcopy(item) for item in candidate.tools],
        "runtime": deepcopy(candidate.runtime),
        "resources": deepcopy(candidate.resources),
        "consequenceCode": "create-and-enqueue-one-workflow-run",
    }
    payload["previewHash"] = agent_run_authorization_preview_hash(payload)
    return AgentRunAuthorizationPreview.model_validate(payload).runtime_payload()


def _strict_json_equal(left: Any, right: Any) -> bool:
    try:
        return _canonical_json(left) == _canonical_json(right)
    except (TypeError, ValueError):
        return False


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


__all__ = [
    "build_agent_run_authorization_preview",
    "get_agent_run_authorization_preview_from_http",
]
