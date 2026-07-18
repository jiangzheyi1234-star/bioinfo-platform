from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient

import apps.remote_runner.agent_fastq_qc_execution_candidate as candidate_module
from apps.api.agent_fastq_qc_planner import build_fastq_qc_plan_proposal
from apps.api.capability_graph_service import CapabilityGraphService
from apps.remote_runner.agent_effect_budget_storage import (
    grant_agent_session_effect_budget,
)
from apps.remote_runner.agent_fastq_qc_execution_candidate import (
    build_agent_fastq_qc_execution_candidate,
)
from apps.remote_runner.agent_plan_storage import fetch_agent_plan_revision
from apps.remote_runner.main import app
from apps.remote_runner.preflight import RunPreflightError
from apps.remote_runner.storage import get_connection, list_runs, persist_upload
from apps.remote_runner.workflow_revision_storage import fetch_workflow_revision
from core.contracts.agent_fastq_qc_execution import (
    AGENT_FASTQ_QC_EXECUTION_POLICY_ID,
    agent_fastq_qc_execution_hash,
    agent_workflow_run_spec_hash,
    build_agent_fastq_qc_execution,
)
from core.contracts.agent_fastq_qc import fastq_qc_manifest_digest
from core.contracts.agent_effect_budget import AgentSessionEffectBudgetGrantRequest
from core.contracts.agent_session import assert_agent_session_json_safe
from core.contracts.agent_workflow_runtime import workflow_runtime_lock_v2_hash
from tests.helpers.workflow_design_drafts import (
    install_agent_runtime_proof_test_seam,
    workflow_design_config,
)
from tests.test_agent_fastq_qc_api_lifecycle import (
    _capability_tools,
    _create_request,
    _data,
    _ready_profile_tool,
)


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
_TOOL_KEYS = {
    "capabilityId",
    "name",
    "packageSpec",
    "profileId",
    "profileVersion",
    "ruleTemplateSha256",
    "source",
    "stepId",
    "targetPlatform",
    "toolId",
    "toolRevisionId",
    "version",
    "wrapperIdentifier",
}


@pytest.fixture
def candidate_case(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    cfg = workflow_design_config(tmp_path)
    install_agent_runtime_proof_test_seam(monkeypatch)
    cfg.work_dir = str(tmp_path.parent / f"agent-candidate-{tmp_path.name[-4:]}")
    cfg.api_token_actor = "user-1"
    fastqc = _ready_profile_tool(cfg, "fastqc")
    multiqc = _ready_profile_tool(cfg, "multiqc")
    upload = persist_upload(
        cfg,
        filename="reads.fastq",
        content_base64="QHNt b2tlCkFDR1RBQ0dUCisKRkZGRkZGRkYK".replace(" ", ""),
        mime_type="text/plain",
    )
    monkeypatch.setattr(
        "apps.remote_runner.route_utils.load_remote_runner_config",
        lambda: cfg,
    )
    client = TestClient(app)
    headers = {"Authorization": "Bearer workflow-design-token"}
    created_response = client.post(
        "/api/v1/agent-sessions",
        headers=headers,
        json=_create_request(
            upload,
            [fastqc["toolRevisionId"], multiqc["toolRevisionId"]],
        ),
    )
    assert created_response.status_code == 201, created_response.text
    created = _data(created_response)
    effect_budget = grant_agent_session_effect_budget(
        cfg,
        created["sessionId"],
        AgentSessionEffectBudgetGrantRequest(
            expectedStateVersion=1,
            maxRunSubmissions=1,
            confirmation="enable-one-run",
            requestId="grant-fastq-qc-candidate",
            idempotencyKey="grant-fastq-qc-candidate",
        ),
        actor="user-1",
    )
    proposal = build_fastq_qc_plan_proposal(
        session=created,
        capability_graph=CapabilityGraphService().snapshot(
            registered_tools=_capability_tools(cfg),
            catalog={"items": [], "total": 0},
            agent_selectable_only=True,
        ),
    )
    planned_response = client.post(
        f"/api/v1/agent-sessions/{created['sessionId']}/plan",
        headers=headers,
        json={
            "requestId": "plan-fastq-qc-candidate",
            "actor": "user-1",
            "idempotencyKey": "plan-fastq-qc-candidate",
            "expectedStateVersion": created["stateVersion"],
            "proposal": proposal.runtime_payload(),
        },
    )
    assert planned_response.status_code == 200, planned_response.text
    planned = _data(planned_response)
    approval_response = client.post(
        f"/api/v1/agent-sessions/{created['sessionId']}/approval",
        headers=headers,
        json={
            "requestId": "approve-fastq-qc-candidate",
            "actor": "user-1",
            "idempotencyKey": "approve-fastq-qc-candidate",
            "expectedStateVersion": planned["session"]["stateVersion"],
            "decision": "approve",
            "expectedPlanHash": planned["plan"]["planHash"],
            "reason": "Reviewed exact candidate authority and runtime evidence.",
        },
    )
    assert approval_response.status_code == 200, approval_response.text
    approved = _data(approval_response)
    plan = fetch_agent_plan_revision(cfg, planned["plan"]["planRevisionId"])
    revision = fetch_workflow_revision(
        cfg,
        approved["session"]["workflowRevisionId"],
    )
    assert plan is not None
    assert revision is not None
    assert list_runs(cfg) == []
    return {
        "cfg": cfg,
        "effect_budget": effect_budget,
        "plan": plan,
        "revision": revision,
        "session": approved["session"],
        "upload": upload,
    }


def test_candidate_is_deterministic_exact_path_free_and_read_only(
    candidate_case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = candidate_case["cfg"]
    validation_calls = 0
    preflight_calls = 0
    original_validation = candidate_module.validate_run_spec_for_pipeline
    original_preflight = candidate_module.preflight_run_spec

    def counted_validation(*args: Any, **kwargs: Any) -> None:
        nonlocal validation_calls
        validation_calls += 1
        original_validation(*args, **kwargs)

    def counted_preflight(*args: Any, **kwargs: Any) -> None:
        nonlocal preflight_calls
        preflight_calls += 1
        original_preflight(*args, **kwargs)

    monkeypatch.setattr(
        candidate_module,
        "validate_run_spec_for_pipeline",
        counted_validation,
    )
    monkeypatch.setattr(candidate_module, "preflight_run_spec", counted_preflight)
    before_counts = _mutation_counts(cfg)
    with get_connection(cfg) as observer:
        before_data_version = int(observer.execute("PRAGMA data_version").fetchone()[0])
        first = build_agent_fastq_qc_execution_candidate(
            cfg,
            session=candidate_case["session"],
            plan=candidate_case["plan"],
            workflow_revision=candidate_case["revision"],
        )
        second = build_agent_fastq_qc_execution_candidate(
            cfg,
            session=candidate_case["session"],
            plan=candidate_case["plan"],
            workflow_revision=candidate_case["revision"],
        )
        after_data_version = int(observer.execute("PRAGMA data_version").fetchone()[0])

    assert first == second
    assert validation_calls == 2
    assert preflight_calls == 2
    assert before_counts == (0, 0)
    assert _mutation_counts(cfg) == before_counts
    assert after_data_version == before_data_version
    assert list_runs(cfg) == []

    run_spec = first.run_spec
    assert set(run_spec) == _RUN_SPEC_KEYS
    assert run_spec["pipelineId"] == "generated-tool-run-v1"
    assert (
        run_spec["workflowRevisionId"]
        == candidate_case["revision"]["workflowRevisionId"]
    )
    assert run_spec["inputs"] == [
        {
            "role": "reads",
            "uploadId": candidate_case["upload"]["uploadId"],
            "filename": "reads.fastq",
        }
    ]
    assert set(run_spec["inputs"][0]) == _INPUT_KEYS
    assert run_spec["execution"] == {
        "queueName": "default",
        "retryPolicy": {
            "schemaVersion": "execution-retry-policy.v1",
            "maxAttempts": 3,
            "backoffSeconds": 5,
        },
        "timeoutPolicy": {
            "schemaVersion": "execution-timeout-policy.v1",
            "queueTtlSeconds": 0,
            "startToCloseTimeoutSeconds": 0,
            "heartbeatTimeoutSeconds": 60,
        },
    }
    assert first.execution_policy_id == AGENT_FASTQ_QC_EXECUTION_POLICY_ID
    assert first.execution_policy_hash == agent_fastq_qc_execution_hash(
        build_agent_fastq_qc_execution()
    )
    assert first.execution_policy == run_spec["execution"]
    assert first.run_spec_hash == agent_workflow_run_spec_hash(run_spec)
    assert first.runtime_lock_hash == workflow_runtime_lock_v2_hash(
        candidate_case["revision"]["runtimeLock"]
    )
    assert (
        first.runtime_proof_hash
        == candidate_case["revision"]["runtimeLock"]["runtimeProofHash"]
    )
    assert first.input_manifest_digest == fastq_qc_manifest_digest(
        candidate_case["session"]["goal"]["context"]
    )

    assert [tool["stepId"] for tool in first.tools] == ["fastqc", "multiqc"]
    assert all(set(tool) == _TOOL_KEYS for tool in first.tools)
    assert [tool["version"] for tool in first.tools] == ["0.12.1", "1.34"]
    assert first.resources == {
        "bindings": {},
        "orderedSteps": [
            {
                "stepId": "fastqc",
                "threads": 2,
                "resources": {},
                "schedulerResources": {"mem_mb": 2048},
            },
            {
                "stepId": "multiqc",
                "threads": 1,
                "resources": {},
                "schedulerResources": {"mem_mb": 1024},
            },
        ],
    }
    assert set(first.runtime) == {
        "platform",
        "runnerProtocol",
        "workflowRuntime",
        "snakemake",
        "managedConda",
        "workflowProfile",
        "release",
    }
    assert set(first.runtime["runnerProtocol"]) == {"version", "fingerprint"}
    assert set(first.runtime["workflowRuntime"]) == {
        "provider",
        "source",
        "version",
        "snakemakePackageVersion",
        "pythonSha256",
        "declaredArtifactArchiveSha256",
    }
    assert set(first.runtime["snakemake"]) == {"reportedVersion", "sha256"}
    assert set(first.runtime["managedConda"]) == {"sha256"}
    assert set(first.runtime["workflowProfile"]) == {"name", "fileSha256"}
    assert set(first.runtime["release"]) == {
        "treeHash",
        "wrapperMirrorTreeHash",
    }

    public_candidate = {
        "runSpec": run_spec,
        "tools": list(first.tools),
        "runtime": first.runtime,
        "resources": first.resources,
    }
    assert_agent_session_json_safe(public_candidate, path="candidate")
    assert not _keys_matching(public_candidate, _unsafe_public_key)
    serialized = json.dumps(public_candidate, ensure_ascii=False, sort_keys=True)
    for host_path in (
        candidate_case["upload"]["path"],
        cfg.release_dir,
        cfg.work_dir,
        cfg.snakemake_command,
        cfg.managed_conda_command,
        cfg.managed_conda_root_prefix,
    ):
        assert str(host_path) not in serialized
    assert all(
        set(output) == {"from", "as"} for output in run_spec["workflow"]["outputs"]
    )
    assert all(
        set(output["from"]) == {"nodeId", "port"}
        for output in run_spec["workflow"]["outputs"]
    )


def test_candidate_rejects_plan_identity_and_validation_tamper(
    candidate_case: dict[str, Any],
) -> None:
    generic_session = deepcopy(candidate_case["session"])
    generic_plan = deepcopy(candidate_case["plan"])
    generic_planner = {
        "adapterId": "h2ometa.generic.v1",
        "adapterVersion": "1.0.0",
        "modelRef": "deterministic:generic",
    }
    generic_session["planner"] = generic_planner
    generic_plan["proposal"]["planner"] = generic_planner
    _rehash_plan(generic_plan)
    generic_session["activePlanHash"] = generic_plan["planHash"]
    with pytest.raises(ValueError, match="AGENT_RUN_CANDIDATE_ADAPTER_UNSUPPORTED"):
        _build(candidate_case, session=generic_session, plan=generic_plan)

    invalid_session = deepcopy(candidate_case["session"])
    invalid_plan = deepcopy(candidate_case["plan"])
    invalid_plan["validation"]["valid"] = False
    _rehash_plan(invalid_plan)
    invalid_session["activePlanHash"] = invalid_plan["planHash"]
    with pytest.raises(ValueError, match="AGENT_RUN_CANDIDATE_PLAN_INVALID"):
        _build(candidate_case, session=invalid_session, plan=invalid_plan)

    incoherent_plan = deepcopy(candidate_case["plan"])
    incoherent_plan["validation"]["valid"] = False
    with pytest.raises(ValueError, match="AGENT_PLAN_CANONICAL"):
        _build(candidate_case, plan=incoherent_plan)


def test_candidate_rejects_workflow_revision_graph_manifest_and_ref_tamper(
    candidate_case: dict[str, Any],
) -> None:
    raw_content_tamper = deepcopy(candidate_case["revision"])
    raw_content_tamper["compiler"]["name"] = "tampered-compiler"
    with pytest.raises(ValueError, match="WORKFLOW_REVISION_STORED_HASH_MISMATCH"):
        _build(candidate_case, revision=raw_content_tamper)

    def invalid_graph_schema(revision: dict[str, Any]) -> None:
        revision["graphSnapshot"]["schemaVersion"] = "workflow-graph-snapshot.v2"

    session, revision = _coherent_revision_tamper(
        candidate_case,
        invalid_graph_schema,
    )
    with pytest.raises(ValueError, match="AGENT_RUN_CANDIDATE_GRAPH_SNAPSHOT_INVALID"):
        _build(candidate_case, session=session, revision=revision)

    def invalid_graph_run_spec(revision: dict[str, Any]) -> None:
        revision["graphSnapshot"]["runSpec"]["workflow"]["nodes"][0]["runtime"][
            "threads"
        ] = 3

    session, revision = _coherent_revision_tamper(
        candidate_case,
        invalid_graph_run_spec,
    )
    with pytest.raises(ValueError, match="WORKFLOW_REVISION_RUN_SPEC_MISMATCH"):
        _build(candidate_case, session=session, revision=revision)

    def invalid_manifest(revision: dict[str, Any]) -> None:
        revision["manifest"]["toolRevisions"][0]["toolVersion"] = "0.11.9"

    session, revision = _coherent_revision_tamper(candidate_case, invalid_manifest)
    with pytest.raises(ValueError, match="AGENT_RUN_CANDIDATE_MANIFEST_TOOLS_INVALID"):
        _build(candidate_case, session=session, revision=revision)

    def invalid_draft_ref(revision: dict[str, Any]) -> None:
        revision["draftRevision"] += 1

    session, revision = _coherent_revision_tamper(candidate_case, invalid_draft_ref)
    with pytest.raises(
        ValueError,
        match="AGENT_RUN_CANDIDATE_WORKFLOW_REVISION_IDENTITY_MISMATCH",
    ):
        _build(candidate_case, session=session, revision=revision)


def test_candidate_rejects_stored_and_current_runtime_tamper(
    candidate_case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def invalid_stored_runtime(revision: dict[str, Any]) -> None:
        revision["runtimeLock"]["runtimeProofHash"] = "0" * 64

    session, revision = _coherent_revision_tamper(
        candidate_case,
        invalid_stored_runtime,
    )
    with pytest.raises(ValueError, match="AGENT_WORKFLOW_RUNTIME_PROOF_HASH_MISMATCH"):
        _build(candidate_case, session=session, revision=revision)

    snakemake_path = Path(candidate_case["cfg"].snakemake_command)
    snakemake_path.write_bytes(snakemake_path.read_bytes() + b"runtime-drift")
    with pytest.raises(ValueError, match="AGENT_WORKFLOW_RUNTIME_PROOF_MISMATCH"):
        _build(candidate_case)


def test_candidate_rejects_current_draft_and_preflight_failure(
    candidate_case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def rejected_preflight(*_args: Any, **_kwargs: Any) -> None:
        raise RunPreflightError("AGENT_CANDIDATE_TEST_PREFLIGHT_REJECTED")

    with monkeypatch.context() as preflight_patch:
        preflight_patch.setattr(
            candidate_module,
            "preflight_run_spec",
            rejected_preflight,
        )
        with pytest.raises(ValueError, match="AGENT_CANDIDATE_TEST_PREFLIGHT_REJECTED"):
            _build(candidate_case)

    with get_connection(candidate_case["cfg"]) as connection:
        connection.execute(
            """
            UPDATE workflow_design_drafts
            SET revision = revision + 1
            WHERE draft_id = ?
            """,
            (candidate_case["plan"]["draftId"],),
        )
        connection.commit()
    with pytest.raises(ValueError, match="WORKFLOW_DESIGN_REVISION_MISMATCH"):
        _build(candidate_case)
    assert list_runs(candidate_case["cfg"]) == []
    assert _mutation_counts(candidate_case["cfg"])[1] == 0


def _build(
    case: dict[str, Any],
    *,
    session: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
    revision: dict[str, Any] | None = None,
) -> Any:
    return build_agent_fastq_qc_execution_candidate(
        case["cfg"],
        session=session or case["session"],
        plan=plan or case["plan"],
        workflow_revision=revision or case["revision"],
    )


def _coherent_revision_tamper(
    case: dict[str, Any],
    mutate: Callable[[dict[str, Any]], None],
) -> tuple[dict[str, Any], dict[str, Any]]:
    session = deepcopy(case["session"])
    revision = deepcopy(case["revision"])
    mutate(revision)
    _rehash_revision(revision)
    session["workflowRevisionId"] = revision["workflowRevisionId"]
    return session, revision


def _rehash_plan(plan: dict[str, Any]) -> None:
    payload = {
        key: plan[key]
        for key in (
            "budget",
            "contractVersion",
            "draftId",
            "draftRevision",
            "parentPlanRevisionId",
            "planGeneration",
            "proposal",
            "sessionId",
            "validation",
        )
    }
    canonical = _canonical_json(payload)
    plan["canonicalPayload"] = canonical
    plan["planHash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _rehash_revision(revision: dict[str, Any]) -> None:
    content = {
        "schemaVersion": "workflow-revision.v1",
        "draftId": revision["draftId"],
        "draftRevision": revision["draftRevision"],
        "manifest": revision["manifest"],
        "graphSnapshot": revision["graphSnapshot"],
        "runtimeLock": revision["runtimeLock"],
        "compiler": revision["compiler"],
    }
    digest = hashlib.sha256(_canonical_json(content).encode("utf-8")).hexdigest()
    revision["contentHash"] = digest
    revision["workflowRevisionId"] = f"wfrev_{digest[:24]}"


def _mutation_counts(cfg: Any) -> tuple[int, int]:
    with get_connection(cfg) as connection:
        run_count = int(connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0])
        authorization_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM agent_run_authorizations"
            ).fetchone()[0]
        )
    return run_count, authorization_count


def _keys_matching(value: Any, predicate: Callable[[str], bool]) -> list[str]:
    matches: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            if predicate(str(key)):
                matches.append(str(key))
            matches.extend(_keys_matching(nested, predicate))
    elif isinstance(value, list | tuple):
        for item in value:
            matches.extend(_keys_matching(item, predicate))
    return matches


def _unsafe_public_key(value: str) -> bool:
    normalized = "".join(
        character for character in value.lower() if character.isalnum()
    )
    return normalized.endswith("path") or any(
        marker in normalized
        for marker in (
            "accesstoken",
            "apikey",
            "authorization",
            "credential",
            "password",
            "privatekey",
            "secret",
        )
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
