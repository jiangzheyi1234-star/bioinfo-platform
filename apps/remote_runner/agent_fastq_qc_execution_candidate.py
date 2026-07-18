"""Server-owned execution candidate for the deterministic FASTQ QC adapter."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from core.contracts.agent_fastq_qc import (
    AGENT_FASTQ_QC_ADAPTER_ID,
    AGENT_FASTQ_QC_ADAPTER_VERSION,
    AGENT_FASTQ_QC_MODEL_REF,
)
from core.contracts.agent_fastq_qc_execution import (
    AGENT_FASTQ_QC_EXECUTION_POLICY_ID,
    agent_fastq_qc_execution_hash,
    agent_workflow_run_spec_hash,
    build_agent_fastq_qc_execution,
)
from core.contracts.agent_plan import AgentPlanRevisionRecord
from core.contracts.agent_run_authorization_preview import (
    AgentRunAuthorizationResourceSummary,
    AgentRunAuthorizationRuntimeSummary,
    AgentRunAuthorizationToolSummary,
)
from core.contracts.agent_session import AgentSessionRecord
from core.contracts.capability_bundle import CAPABILITY_BUNDLE_VERSION
from core.contracts.workflow_design import workflow_design_to_generated_run_spec

from .agent_fastq_qc_validation import require_fastq_qc_authority_snapshot
from .agent_workflow_runtime import (
    require_passive_current_agent_workflow_runtime_lock,
)
from .config import RemoteRunnerConfig
from .generated_workflow_constants import GENERATED_TOOL_RUN_PIPELINE_ID
from .pipeline import get_pipeline, validate_run_spec_for_pipeline
from .preflight import preflight_run_spec


_RUN_SPEC_KEYS = {
    "execution",
    "inputs",
    "pipelineId",
    "projectId",
    "resourceBindings",
    "workflow",
    "workflowDesign",
    "workflowRevisionId",
}
_INPUT_KEYS = {"filename", "role", "uploadId"}


@dataclass(frozen=True, slots=True)
class AgentFastqQcExecutionCandidate:
    """Exact internal candidate consumed by preview and later atomic authorization."""

    run_spec: dict[str, Any]
    input_manifest_digest: str
    run_spec_hash: str
    execution_policy_id: str
    execution_policy_hash: str
    execution_policy: dict[str, Any]
    runtime_lock_hash: str
    runtime_proof_hash: str
    tools: tuple[dict[str, Any], ...]
    runtime: dict[str, Any]
    resources: dict[str, Any]


def build_agent_fastq_qc_execution_candidate(
    cfg: RemoteRunnerConfig,
    *,
    session: dict[str, Any],
    plan: dict[str, Any],
    workflow_revision: dict[str, Any],
) -> AgentFastqQcExecutionCandidate:
    """Rebuild and preflight one candidate without accepting caller run fields."""

    normalized_session = AgentSessionRecord.model_validate(session)
    normalized_plan = AgentPlanRevisionRecord.model_validate(plan)
    _require_session_plan_identity(normalized_session, normalized_plan)
    _require_workflow_revision_integrity(
        workflow_revision,
        workflow_revision_id=str(normalized_session.workflowRevisionId),
        draft_id=normalized_plan.draftId,
        draft_revision=normalized_plan.draftRevision,
    )

    authority = require_fastq_qc_authority_snapshot(
        cfg,
        session=normalized_session.runtime_payload(),
        plan=_authority_plan(normalized_session, normalized_plan),
    )
    base_run_spec = workflow_design_to_generated_run_spec(
        normalized_plan.proposal.draft,
        draft_id=normalized_plan.draftId,
        revision=normalized_plan.draftRevision,
    )
    _require_revision_graph_and_manifest(
        workflow_revision,
        base_run_spec=base_run_spec,
        trusted_tools=[item.runtime_payload() for item in authority.trusted_tools],
    )

    runtime_proof = require_passive_current_agent_workflow_runtime_lock(
        cfg,
        dict(workflow_revision["runtimeLock"]),
    )
    execution = build_agent_fastq_qc_execution()
    run_spec = _effective_run_spec(
        base_run_spec,
        upload=authority.materialized_input.runtime_payload(),
        execution=execution.runtime_payload(),
        workflow_revision_id=str(normalized_session.workflowRevisionId),
    )
    pipeline = get_pipeline(cfg, str(run_spec["pipelineId"]))
    validate_run_spec_for_pipeline(pipeline, run_spec)
    preflight_run_spec(cfg, pipeline, run_spec)

    tools = tuple(
        AgentRunAuthorizationToolSummary.model_validate(
            {
                key: value
                for key, value in fact.runtime_payload().items()
                if key != "packId"
            }
        ).runtime_payload()
        for fact in authority.trusted_tools
    )
    runtime = _runtime_summary(runtime_proof["runtimeLock"])
    resources = _resource_summary(base_run_spec)
    return AgentFastqQcExecutionCandidate(
        run_spec=deepcopy(run_spec),
        input_manifest_digest=authority.input_manifest_digest,
        run_spec_hash=agent_workflow_run_spec_hash(run_spec),
        execution_policy_id=AGENT_FASTQ_QC_EXECUTION_POLICY_ID,
        execution_policy_hash=agent_fastq_qc_execution_hash(execution),
        execution_policy=execution.runtime_payload(),
        runtime_lock_hash=str(runtime_proof["runtimeLockHash"]),
        runtime_proof_hash=str(runtime_proof["runtimeProofHash"]),
        tools=tools,
        runtime=runtime,
        resources=resources,
    )


def _require_session_plan_identity(
    session: AgentSessionRecord,
    plan: AgentPlanRevisionRecord,
) -> None:
    expected_planner = {
        "adapterId": AGENT_FASTQ_QC_ADAPTER_ID,
        "adapterVersion": AGENT_FASTQ_QC_ADAPTER_VERSION,
        "modelRef": AGENT_FASTQ_QC_MODEL_REF,
    }
    if session.status != "ready_to_run" or not session.workflowRevisionId:
        raise ValueError("AGENT_RUN_CANDIDATE_SESSION_NOT_READY")
    if not _strict_json_equal(session.planner.runtime_payload(), expected_planner):
        raise ValueError("AGENT_RUN_CANDIDATE_ADAPTER_UNSUPPORTED")
    if not _strict_json_equal(
        plan.proposal.planner.runtime_payload(), expected_planner
    ):
        raise ValueError("AGENT_RUN_CANDIDATE_ADAPTER_UNSUPPORTED")
    if plan.validation.get("valid") is not True:
        raise ValueError("AGENT_RUN_CANDIDATE_PLAN_INVALID")
    if (
        plan.sessionId != session.sessionId
        or plan.planGeneration != session.planGeneration
        or plan.planHash != session.activePlanHash
        or plan.draftId != session.activeDraftId
        or plan.draftRevision != session.activeDraftRevision
        or not _strict_json_equal(
            plan.budget.runtime_payload(), session.budget.runtime_payload()
        )
    ):
        raise ValueError("AGENT_RUN_CANDIDATE_PLAN_IDENTITY_MISMATCH")


def _authority_plan(
    session: AgentSessionRecord,
    plan: AgentPlanRevisionRecord,
) -> dict[str, Any]:
    """Remove only verified server-owned provenance before canonical rebuild."""

    proposal = plan.proposal.runtime_payload()
    draft = proposal.get("draft")
    provenance = draft.get("provenance") if isinstance(draft, dict) else None
    if not isinstance(provenance, dict) or not _strict_json_equal(
        {
            "agentSessionId": provenance.get("agentSessionId"),
            "agentPlanGeneration": provenance.get("agentPlanGeneration"),
        },
        {
            "agentSessionId": session.sessionId,
            "agentPlanGeneration": plan.planGeneration,
        },
    ):
        raise ValueError("AGENT_RUN_CANDIDATE_PLAN_PROVENANCE_MISMATCH")
    canonical_provenance = dict(provenance)
    del canonical_provenance["agentSessionId"]
    del canonical_provenance["agentPlanGeneration"]
    draft["provenance"] = canonical_provenance
    return proposal


def _require_workflow_revision_integrity(
    revision: dict[str, Any],
    *,
    workflow_revision_id: str,
    draft_id: str,
    draft_revision: int,
) -> None:
    try:
        content = {
            "schemaVersion": "workflow-revision.v1",
            "draftId": revision["draftId"],
            "draftRevision": revision["draftRevision"],
            "manifest": revision["manifest"],
            "graphSnapshot": revision["graphSnapshot"],
            "runtimeLock": revision["runtimeLock"],
            "compiler": revision["compiler"],
        }
        expected_hash = hashlib.sha256(
            _canonical_json(content).encode("utf-8")
        ).hexdigest()
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("AGENT_RUN_CANDIDATE_WORKFLOW_REVISION_INVALID") from exc
    if revision.get("contentHash") != expected_hash:
        raise ValueError("WORKFLOW_REVISION_STORED_HASH_MISMATCH")
    if revision.get("workflowRevisionId") != f"wfrev_{expected_hash[:24]}":
        raise ValueError("WORKFLOW_REVISION_STORED_ID_MISMATCH")
    if not _strict_json_equal(
        {
            "workflowRevisionId": revision.get("workflowRevisionId"),
            "draftId": revision.get("draftId"),
            "draftRevision": revision.get("draftRevision"),
        },
        {
            "workflowRevisionId": workflow_revision_id,
            "draftId": draft_id,
            "draftRevision": draft_revision,
        },
    ):
        raise ValueError("AGENT_RUN_CANDIDATE_WORKFLOW_REVISION_IDENTITY_MISMATCH")


def _require_revision_graph_and_manifest(
    revision: dict[str, Any],
    *,
    base_run_spec: dict[str, Any],
    trusted_tools: list[dict[str, Any]],
) -> None:
    graph = revision.get("graphSnapshot")
    if (
        not isinstance(graph, dict)
        or graph.get("schemaVersion") != "workflow-graph-snapshot.v1"
    ):
        raise ValueError("AGENT_RUN_CANDIDATE_GRAPH_SNAPSHOT_INVALID")
    if not _strict_json_equal(graph.get("runSpec"), base_run_spec):
        raise ValueError("WORKFLOW_REVISION_RUN_SPEC_MISMATCH")
    manifest = revision.get("manifest")
    if (
        not isinstance(manifest, dict)
        or manifest.get("schemaVersion") != "workflow-revision-manifest.v1"
    ):
        raise ValueError("AGENT_RUN_CANDIDATE_MANIFEST_INVALID")
    expected_run_spec_hash = hashlib.sha256(
        _canonical_json(base_run_spec).encode("utf-8")
    ).hexdigest()
    if manifest.get("runSpecSha256") != expected_run_spec_hash:
        raise ValueError("AGENT_RUN_CANDIDATE_MANIFEST_RUN_SPEC_MISMATCH")

    workflow = base_run_spec.get("workflow")
    nodes = workflow.get("nodes") if isinstance(workflow, dict) else None
    entries = manifest.get("toolRevisions")
    if not isinstance(nodes, list) or not isinstance(entries, list):
        raise ValueError("AGENT_RUN_CANDIDATE_MANIFEST_TOOLS_INVALID")
    if len(nodes) != len(entries) or len(nodes) != len(trusted_tools):
        raise ValueError("AGENT_RUN_CANDIDATE_MANIFEST_TOOLS_INVALID")
    for node, entry, tool in zip(nodes, entries, trusted_tools, strict=True):
        if not isinstance(node, dict) or not isinstance(entry, dict):
            raise ValueError("AGENT_RUN_CANDIDATE_MANIFEST_TOOLS_INVALID")
        revision_id = str(tool["toolRevisionId"])
        expected = {
            "capabilityBundleVersion": CAPABILITY_BUNDLE_VERSION,
            "capabilityId": _manifest_capability_id(revision_id),
            "stepId": node.get("id"),
            "toolRevisionId": node.get("toolRevisionId"),
            "toolVersion": tool["version"],
        }
        actual = {key: entry.get(key) for key in expected}
        if node.get("toolRevisionId") != revision_id or not _strict_json_equal(
            actual, expected
        ):
            raise ValueError("AGENT_RUN_CANDIDATE_MANIFEST_TOOLS_INVALID")


def _effective_run_spec(
    base: dict[str, Any],
    *,
    upload: dict[str, Any],
    execution: dict[str, Any],
    workflow_revision_id: str,
) -> dict[str, Any]:
    inputs = base.get("inputs")
    if (
        not isinstance(inputs, list)
        or len(inputs) != 1
        or not isinstance(inputs[0], dict)
    ):
        raise ValueError("AGENT_RUN_CANDIDATE_INPUT_INVALID")
    expected_input = inputs[0]
    if expected_input.get("role") != upload.get("role") or expected_input.get(
        "filename"
    ) != upload.get("filename"):
        raise ValueError("AGENT_RUN_CANDIDATE_INPUT_IDENTITY_MISMATCH")
    run_spec = deepcopy(base)
    run_spec["inputs"] = [
        {
            "role": upload["role"],
            "uploadId": upload["uploadId"],
            "filename": upload["filename"],
        }
    ]
    run_spec["execution"] = deepcopy(execution)
    run_spec["workflowRevisionId"] = workflow_revision_id
    if set(run_spec) != _RUN_SPEC_KEYS or set(run_spec["inputs"][0]) != _INPUT_KEYS:
        raise ValueError("AGENT_RUN_CANDIDATE_RUN_SPEC_SHAPE_INVALID")
    if run_spec.get("pipelineId") != GENERATED_TOOL_RUN_PIPELINE_ID:
        raise ValueError("AGENT_RUN_CANDIDATE_PIPELINE_INVALID")
    return run_spec


def _runtime_summary(runtime_lock: dict[str, Any]) -> dict[str, Any]:
    proof = runtime_lock.get("proof") if isinstance(runtime_lock, dict) else None
    if not isinstance(proof, dict):
        raise ValueError("AGENT_RUN_CANDIDATE_RUNTIME_PROOF_INVALID")
    runner = proof.get("runnerProtocol")
    workflow = proof.get("workflowRuntime")
    snakemake = proof.get("snakemake")
    conda = proof.get("managedConda")
    profile = proof.get("workflowProfile")
    release = proof.get("release")
    if not all(
        isinstance(value, dict)
        for value in (runner, workflow, snakemake, conda, profile, release)
    ):
        raise ValueError("AGENT_RUN_CANDIDATE_RUNTIME_PROOF_INVALID")
    return AgentRunAuthorizationRuntimeSummary.model_validate(
        {
            "platform": proof.get("platform"),
            "runnerProtocol": {
                "version": runner.get("version"),
                "fingerprint": runner.get("fingerprint"),
            },
            "workflowRuntime": {
                "provider": workflow.get("provider"),
                "source": workflow.get("source"),
                "version": workflow.get("version"),
                "snakemakePackageVersion": workflow.get("snakemakePackageVersion"),
                "pythonSha256": workflow.get("pythonSha256"),
                "declaredArtifactArchiveSha256": workflow.get(
                    "declaredArtifactArchiveSha256"
                ),
            },
            "snakemake": {
                "reportedVersion": snakemake.get("reportedVersion"),
                "sha256": snakemake.get("sha256"),
            },
            "managedConda": {"sha256": conda.get("sha256")},
            "workflowProfile": {
                "name": profile.get("name"),
                "fileSha256": profile.get("fileSha256"),
            },
            "release": {
                "treeHash": release.get("treeHash"),
                "wrapperMirrorTreeHash": release.get("wrapperMirrorTreeHash"),
            },
        }
    ).runtime_payload()


def _resource_summary(base_run_spec: dict[str, Any]) -> dict[str, Any]:
    workflow = base_run_spec.get("workflow")
    nodes = workflow.get("nodes") if isinstance(workflow, dict) else None
    bindings = base_run_spec.get("resourceBindings")
    if not isinstance(nodes, list) or not isinstance(bindings, dict):
        raise ValueError("AGENT_RUN_CANDIDATE_RESOURCES_INVALID")
    steps: list[dict[str, Any]] = []
    for node in nodes:
        runtime = node.get("runtime") if isinstance(node, dict) else None
        if not isinstance(runtime, dict):
            raise ValueError("AGENT_RUN_CANDIDATE_RESOURCES_INVALID")
        resources = runtime.get("resources")
        scheduler_resources = runtime.get("schedulerResources")
        if not isinstance(resources, dict) or not isinstance(scheduler_resources, dict):
            raise ValueError("AGENT_RUN_CANDIDATE_RESOURCES_INVALID")
        steps.append(
            {
                "stepId": node.get("id"),
                "threads": runtime.get("threads"),
                "resources": deepcopy(resources),
                "schedulerResources": deepcopy(scheduler_resources),
            }
        )
    return AgentRunAuthorizationResourceSummary.model_validate(
        {
            "bindings": deepcopy(bindings),
            "orderedSteps": steps,
        }
    ).runtime_payload()


def _manifest_capability_id(tool_revision_id: str) -> str:
    normalized = tool_revision_id.replace(":", "_").replace("/", "_")
    return f"{CAPABILITY_BUNDLE_VERSION}:tool:{normalized}"


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
    "AgentFastqQcExecutionCandidate",
    "build_agent_fastq_qc_execution_candidate",
]
