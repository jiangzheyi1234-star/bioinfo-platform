from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

import apps.remote_runner.agent_fastq_qc_validation as validation
from apps.api.tool_profile_prepare_payload import profile_prepare_payload
from apps.api.tool_profile_sources import all_tool_profiles
from apps.remote_runner.agent_session_storage import create_agent_session
from apps.remote_runner.upload_storage import persist_upload
from core.agent_fastq_qc_planner import (
    FASTQ_QC_CAPABILITY_PACK_ID,
    build_fastq_qc_plan_proposal_from_capabilities,
    fastq_qc_capability_id,
)
from core.contracts.agent_fastq_qc import (
    AGENT_FASTQ_QC_TOOL_PROFILES,
    AGENT_FASTQ_QC_TOOL_VERSIONS,
    fastq_qc_manifest_digest,
)
from tests.generated_workflow_test_helpers import upsert_ready_tool
from tests.helpers.workflow_design_drafts import workflow_design_config


def test_authority_snapshot_is_exact_path_free_and_reads_each_authority_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case = _authority_case(tmp_path)
    upload_reads = 0
    tool_reads: list[str] = []
    original_upload_reader = validation.require_materialized_upload
    original_tool_reader = validation.fetch_tool_revision

    def counted_upload_reader(cfg: Any, upload_id: str) -> dict[str, Any]:
        nonlocal upload_reads
        upload_reads += 1
        return original_upload_reader(cfg, upload_id)

    def counted_tool_reader(cfg: Any, revision_id: str) -> dict[str, Any] | None:
        tool_reads.append(revision_id)
        return original_tool_reader(cfg, revision_id)

    monkeypatch.setattr(
        validation, "require_materialized_upload", counted_upload_reader
    )
    monkeypatch.setattr(validation, "fetch_tool_revision", counted_tool_reader)

    snapshot = validation.require_fastq_qc_authority_snapshot(
        case["cfg"],
        session=case["session"],
        plan=case["proposal"],
    )

    assert upload_reads == 1
    assert tool_reads == [
        case["tools"]["fastqc"]["toolRevisionId"],
        case["tools"]["multiqc"]["toolRevisionId"],
    ]
    assert snapshot.context.runtime_payload() == case["session"]["goal"]["context"]
    manifest = snapshot.materialized_input.runtime_payload()
    assert manifest == {
        "uploadId": case["upload"]["uploadId"],
        "role": "reads",
        "filename": case["upload"]["filename"],
        "sha256": case["upload"]["sha256"],
        "sizeBytes": case["upload"]["sizeBytes"],
        "mimeType": case["upload"]["mimeType"],
    }
    assert "path" not in manifest
    assert "uploadedAt" not in manifest
    assert snapshot.input_manifest_digest == fastq_qc_manifest_digest(snapshot.context)
    assert (
        snapshot.canonical_proposal.runtime_payload()
        == case["proposal"].runtime_payload()
    )

    facts = [item.runtime_payload() for item in snapshot.trusted_tools]
    assert facts == [
        _expected_tool_fact("fastqc", case["tools"]["fastqc"]),
        _expected_tool_fact("multiqc", case["tools"]["multiqc"]),
    ]
    safe_observation = json.dumps(
        {"input": manifest, "tools": facts},
        ensure_ascii=False,
        sort_keys=True,
    )
    assert "uploadedAt" not in safe_observation
    assert '"path"' not in safe_observation
    assert str(Path(case["cfg"].uploads_dir).resolve()) not in safe_observation
    with pytest.raises(FrozenInstanceError):
        snapshot.input_manifest_digest = "sha256:" + "0" * 64


def test_authority_snapshot_rejects_materialized_upload_byte_tamper(
    tmp_path: Path,
) -> None:
    case = _authority_case(tmp_path)
    upload_path = Path(case["upload"]["path"])
    content = upload_path.read_bytes()
    upload_path.write_bytes(bytes([content[0] ^ 1]) + content[1:])

    with pytest.raises(ValueError, match="INPUT_UPLOAD_SHA256_MISMATCH"):
        validation.require_fastq_qc_authority_snapshot(
            case["cfg"],
            session=case["session"],
            plan=case["proposal"],
        )


def test_authority_snapshot_rejects_tool_revision_tamper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case = _authority_case(tmp_path)
    original_tool_reader = validation.fetch_tool_revision
    multiqc_revision_id = case["tools"]["multiqc"]["toolRevisionId"]

    def drifted_tool_reader(cfg: Any, revision_id: str) -> dict[str, Any] | None:
        tool = original_tool_reader(cfg, revision_id)
        if tool is not None and revision_id == multiqc_revision_id:
            tool = deepcopy(tool)
            tool["version"] = "1.33"
        return tool

    monkeypatch.setattr(validation, "fetch_tool_revision", drifted_tool_reader)

    with pytest.raises(ValueError, match="WORKFLOW_FASTQ_QC_TOOL_IDENTITY_INVALID"):
        validation.require_fastq_qc_authority_snapshot(
            case["cfg"],
            session=case["session"],
            plan=case["proposal"],
        )


def test_authority_snapshot_rejects_noncanonical_proposal_tamper(
    tmp_path: Path,
) -> None:
    case = _authority_case(tmp_path)
    tampered = deepcopy(case["proposal"].runtime_payload())
    tampered["draft"]["nodes"][1]["params"]["use_input_files_only"] = False

    with pytest.raises(ValueError, match="WORKFLOW_FASTQ_QC_PLAN_NOT_CANONICAL"):
        validation.require_fastq_qc_authority_snapshot(
            case["cfg"],
            session=case["session"],
            plan=tampered,
        )


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("draft", "nodes", 1, "params", "use_input_files_only"), 1),
        (("draft", "nodes", 0, "runtime", "schedulerResources", "mem_mb"), 2048.0),
    ],
)
def test_authority_snapshot_rejects_json_type_equivalent_proposal_tamper(
    tmp_path: Path,
    path: tuple[str | int, ...],
    replacement: object,
) -> None:
    case = _authority_case(tmp_path)
    tampered = deepcopy(case["proposal"].runtime_payload())
    target: Any = tampered
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = replacement

    with pytest.raises(ValueError, match="WORKFLOW_FASTQ_QC_PLAN_NOT_CANONICAL"):
        validation.require_fastq_qc_authority_snapshot(
            case["cfg"],
            session=case["session"],
            plan=tampered,
        )


@pytest.mark.parametrize(
    ("profile_id", "mutate", "code"),
    [
        (
            "multiqc",
            lambda tool: tool.__setitem__("version", 1.34),
            "WORKFLOW_FASTQ_QC_TOOL_IDENTITY_INVALID",
        ),
        (
            "fastqc",
            lambda tool: tool["ruleSpecDraft"]["lock"].__setitem__(
                "profileVersion", 2.0
            ),
            "WORKFLOW_FASTQ_QC_TOOL_PROFILE_LOCK_INVALID",
        ),
    ],
)
def test_authority_snapshot_rejects_tool_json_type_coercion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    profile_id: str,
    mutate: Any,
    code: str,
) -> None:
    case = _authority_case(tmp_path)
    original_tool_reader = validation.fetch_tool_revision
    revision_id = case["tools"][profile_id]["toolRevisionId"]

    def drifted_tool_reader(cfg: Any, candidate_id: str) -> dict[str, Any] | None:
        tool = original_tool_reader(cfg, candidate_id)
        if tool is not None and candidate_id == revision_id:
            tool = deepcopy(tool)
            mutate(tool)
        return tool

    monkeypatch.setattr(validation, "fetch_tool_revision", drifted_tool_reader)

    with pytest.raises(ValueError, match=code):
        validation.require_fastq_qc_authority_snapshot(
            case["cfg"],
            session=case["session"],
            plan=case["proposal"],
        )


def test_legacy_validator_keeps_compatibility_while_snapshot_has_no_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case = _authority_case(tmp_path)

    assert (
        validation.validate_fastq_qc_materialized_plan(
            case["cfg"],
            session=case["session"],
            proposal=case["proposal"],
        )
        is None
    )

    generic_session = deepcopy(case["session"])
    generic_session["goal"]["context"] = {"analysis": "generic"}
    generic_plan = deepcopy(case["proposal"].runtime_payload())
    generic_plan["planner"] = {
        "adapterId": "h2ometa.generic-test.v1",
        "adapterVersion": "1.0.0",
        "modelRef": "deterministic:test",
    }
    assert (
        validation.validate_fastq_qc_materialized_plan(
            case["cfg"],
            session=generic_session,
            proposal=generic_plan,
            replan=True,
        )
        is None
    )
    with pytest.raises(ValueError, match="WORKFLOW_FASTQ_QC_ADAPTER_CONTEXT_MISMATCH"):
        validation.require_fastq_qc_authority_snapshot(
            case["cfg"],
            session=generic_session,
            plan=generic_plan,
        )

    monkeypatch.setattr(
        validation,
        "require_materialized_upload",
        lambda *_args, **_kwargs: pytest.fail("replan must fail before authority I/O"),
    )
    with pytest.raises(
        ValueError,
        match="WORKFLOW_FASTQ_QC_REPLAN_ADJUSTMENT_UNSUPPORTED",
    ):
        validation.validate_fastq_qc_materialized_plan(
            case["cfg"],
            session=case["session"],
            proposal=case["proposal"],
            replan=True,
        )


def _authority_case(tmp_path: Path) -> dict[str, Any]:
    cfg = workflow_design_config(tmp_path)
    tools = {
        profile_id: _ready_profile_tool(cfg, profile_id)
        for profile_id in ("fastqc", "multiqc")
    }
    upload = persist_upload(
        cfg,
        filename="reads.fastq",
        content_base64="QHNt b2tlCkFDR1RBQ0dUCisKRkZGRkZGRkYK".replace(" ", ""),
        mime_type="text/plain",
    )
    context = {
        "schemaVersion": "agent-fastq-qc-goal.v1",
        "analysis": "fastq-qc",
        "inputs": [
            {
                key: upload[key]
                for key in ("uploadId", "filename", "sha256", "sizeBytes", "mimeType")
            }
        ],
        "reportFormat": "multiqc-html",
    }
    session = create_agent_session(
        cfg,
        project_id="project-fastq-qc-authority",
        goal={
            "summary": "Inspect the FASTQ and produce a reviewable QC report.",
            "successCriteria": ["Produce FastQC and MultiQC evidence."],
            "context": context,
        },
        constraints={
            "allowedToolRevisionIds": [
                tools["fastqc"]["toolRevisionId"],
                tools["multiqc"]["toolRevisionId"],
            ],
            "forbiddenActions": ["arbitrary_shell", "undeclared_network"],
            "requirements": {},
        },
        budget={
            "maxModelTurns": 1,
            "maxToolCalls": 2,
            "maxReplans": 2,
            "maxRetries": 1,
            "maxWallClockSeconds": 600,
        },
        creation_request_id="create-fastq-qc-authority",
        created_by="user-1",
    )
    proposal = build_fastq_qc_plan_proposal_from_capabilities(
        session=session,
        fastqc=_planner_capability(tools["fastqc"], "fastqc"),
        multiqc=_planner_capability(tools["multiqc"], "multiqc"),
    )
    return {
        "cfg": cfg,
        "proposal": proposal,
        "session": session,
        "tools": tools,
        "upload": upload,
    }


def _ready_profile_tool(cfg: Any, profile_id: str) -> dict[str, Any]:
    profile = next(
        item for item in all_tool_profiles() if item.profile_id == profile_id
    )
    manifest = deepcopy(profile_prepare_payload(profile))
    manifest["summary"] = f"Authority snapshot fixture for {profile_id}"
    return upsert_ready_tool(cfg, manifest)


def _planner_capability(tool: dict[str, Any], profile_id: str) -> dict[str, Any]:
    rule_template = tool["ruleTemplate"]
    revision_id = str(tool["toolRevisionId"])
    return {
        "profileId": profile_id,
        "toolRevisionId": revision_id,
        "version": AGENT_FASTQ_QC_TOOL_VERSIONS[profile_id],
        "capabilityId": fastq_qc_capability_id(profile_id, revision_id),
        "inputs": deepcopy(rule_template["inputs"]),
        "outputs": deepcopy(rule_template["outputs"]),
        "parameters": deepcopy(rule_template.get("params") or {}),
    }


def _expected_tool_fact(profile_id: str, tool: dict[str, Any]) -> dict[str, Any]:
    profile = AGENT_FASTQ_QC_TOOL_PROFILES[profile_id]
    revision_id = str(tool["toolRevisionId"])
    return {
        "stepId": profile_id,
        "capabilityId": fastq_qc_capability_id(profile_id, revision_id),
        "toolId": f"bioconda::{profile_id}",
        "toolRevisionId": revision_id,
        "name": profile_id,
        "source": "bioconda",
        "version": AGENT_FASTQ_QC_TOOL_VERSIONS[profile_id],
        "packageSpec": profile["packageSpec"],
        "targetPlatform": "linux-64",
        "profileId": profile_id,
        "profileVersion": profile["profileVersion"],
        "packId": FASTQ_QC_CAPABILITY_PACK_ID,
        "wrapperIdentifier": profile["wrapper"],
        "ruleTemplateSha256": profile["ruleTemplateSha256"],
    }
