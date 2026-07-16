from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

import pytest
from pydantic import ValidationError

from apps.api.agent_fastq_qc_planner import build_fastq_qc_plan_proposal
from apps.api.capability_graph_service import CapabilityGraphService
from apps.api.agent_session_models import AgentPlanRequest
from apps.api.tool_profile_definitions import TOOL_PROFILES
from apps.api.tool_profile_prepare_payload import profile_prepare_payload
from apps.remote_runner.tool_rule_template_normalization import normalize_rule_template
from core.contracts.agent_fastq_qc import (
    AGENT_FASTQ_QC_TOOL_PROFILES,
    AgentFastqQcGoalContext,
)
from core.contracts.capability_bundle import CAPABILITY_BUNDLE_VERSION


def test_fastq_qc_planner_is_deterministic_and_builds_exact_reviewable_plan() -> None:
    session = _session()
    graph = _capability_graph()

    first = build_fastq_qc_plan_proposal(session=session, capability_graph=graph)
    second = build_fastq_qc_plan_proposal(session=session, capability_graph=deepcopy(graph))

    assert first.runtime_payload() == second.runtime_payload()
    assert first.planner.runtime_payload() == {
        "adapterId": "h2ometa.fastq-qc.v1",
        "adapterVersion": "1.0.0",
        "modelRef": "deterministic:capability-bundle-v1",
    }
    draft = first.draft.runtime_payload()
    assert draft["metadata"]["projectId"] == "project-qc"
    assert draft["inputs"][0]["path"] == "inputs/reads.fastq"
    assert draft["inputs"][0]["metadata"]["uploadId"] == "upl_reads"
    assert "runner" not in draft["inputs"][0]["path"].lower()
    assert [node["id"] for node in draft["nodes"]] == ["fastqc", "multiqc"]
    assert [node["toolRevisionId"] for node in draft["nodes"]] == [
        "bioconda::fastqc@0.12.1",
        "bioconda::multiqc@1.34",
    ]
    assert draft["nodes"][0]["inputs"] == {"reads": {"fromInput": "reads"}}
    assert draft["nodes"][1]["params"] == {"use_input_files_only": True}
    assert draft["edges"] == [
        {
            "id": "fastqc_zip_to_multiqc",
            "from": {"nodeId": "fastqc", "port": "zip"},
            "to": {"nodeId": "multiqc", "port": "fastqc_data"},
            "audit": {
                "source": CAPABILITY_BUNDLE_VERSION,
                "decision": "connect-compatible-ports",
                "confidence": 1.0,
                "reason": "FastQC QC archive feeds the MultiQC report input.",
                "hardChecks": "type,kind,mimeType,data,format",
            },
        }
    ]
    assert [item["as"] for item in draft["outputs"]] == [
        "fastqc_html",
        "fastqc_archive",
        "multiqc_report",
    ]


def test_fastq_qc_planner_fails_closed_for_missing_ambiguous_or_drifted_capability() -> None:
    session = _session()
    graph = _capability_graph()

    missing = deepcopy(graph)
    missing["capabilityBundles"] = [
        item for item in missing["capabilityBundles"] if item["profileId"] != "multiqc"
    ]
    with pytest.raises(ValueError, match="CAPABILITY_BUNDLE_NOT_SELECTABLE: multiqc=1.34"):
        build_fastq_qc_plan_proposal(session=session, capability_graph=missing)

    ambiguous = deepcopy(graph)
    duplicate = deepcopy(
        next(item for item in ambiguous["capabilityBundles"] if item["profileId"] == "fastqc")
    )
    duplicate["toolRevisionId"] = "bioconda::fastqc@0.12.1-second"
    duplicate["capabilityId"] = f"{duplicate['capabilityId']}:second"
    ambiguous["capabilityBundles"].append(duplicate)
    ambiguous_session = _session()
    ambiguous_session["constraints"]["allowedToolRevisionIds"] = []
    with pytest.raises(ValueError, match="revision ambiguous"):
        build_fastq_qc_plan_proposal(session=ambiguous_session, capability_graph=ambiguous)

    drifted = deepcopy(graph)
    multiqc = next(item for item in drifted["capabilityBundles"] if item["profileId"] == "multiqc")
    multiqc["inputs"][0]["mimeType"] = "text/plain"
    with pytest.raises(ValueError, match="WORKFLOW_FASTQ_QC_PORT_INCOMPATIBLE: mimeType"):
        build_fastq_qc_plan_proposal(session=session, capability_graph=drifted)


def test_fastq_qc_command_and_goal_reject_graphs_gzip_and_multiple_inputs() -> None:
    command = {
        "requestId": "plan-1",
        "actor": "user-1",
        "idempotencyKey": "plan-1",
        "expectedStateVersion": 1,
        "serverId": "srv-qc",
    }
    assert AgentPlanRequest.model_validate(command).model_dump()["serverId"] == "srv-qc"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        AgentPlanRequest.model_validate(command | {"proposal": {"draft": {}}})

    gzip_context = _context()
    gzip_context["inputs"][0]["filename"] = "reads.fastq.gz"
    gzip_context["inputs"][0]["mimeType"] = "application/gzip"
    with pytest.raises(ValidationError, match="INPUT_FASTQ_QC_FILE_TYPE_UNSUPPORTED"):
        AgentFastqQcGoalContext.model_validate(gzip_context)

    multiple = _context()
    multiple["inputs"].append(dict(multiple["inputs"][0]) | {"uploadId": "upl_second"})
    with pytest.raises(ValidationError, match="too_long"):
        AgentFastqQcGoalContext.model_validate(multiple)


def test_fastq_qc_curated_profile_versions_pin_the_remote_rule_signatures() -> None:
    for profile_id, expected in AGENT_FASTQ_QC_TOOL_PROFILES.items():
        profile = next(item for item in TOOL_PROFILES if item.profile_id == profile_id)
        payload = profile_prepare_payload(profile)
        normalized = normalize_rule_template(payload["ruleTemplate"], required=True)
        raw = json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

        assert profile.version == expected["profileVersion"]
        assert payload["ruleSpecDraft"]["lock"]["profileVersion"] == expected["profileVersion"]
        assert payload["ruleSpecDraft"]["lock"]["packageSpec"] == expected["packageSpec"]
        assert hashlib.sha256(raw.encode("utf-8")).hexdigest() == expected["ruleTemplateSha256"]


def _session() -> dict[str, Any]:
    return {
        "contractVersion": "agent-session.v1",
        "sessionId": "ags_qc",
        "projectId": "project-qc",
        "goal": {
            "summary": "Inspect this FASTQ and provide a reviewable QC report.",
            "successCriteria": ["Produce a MultiQC HTML report."],
            "context": _context(),
        },
        "constraints": {
            "allowedToolRevisionIds": [
                "bioconda::fastqc@0.12.1",
                "bioconda::multiqc@1.34",
            ],
            "forbiddenActions": ["arbitrary_shell"],
            "requirements": {},
        },
        "budget": {
            "maxModelTurns": 1,
            "maxToolCalls": 2,
            "maxReplans": 2,
            "maxRetries": 1,
            "maxWallClockSeconds": 600,
        },
        "status": "created",
        "stateVersion": 1,
        "planGeneration": 0,
        "planner": {},
        "lastErrorCode": "",
        "creationRequestId": "create-qc",
        "createdBy": "user-1",
        "createdAt": "2026-07-15T00:00:00Z",
        "updatedAt": "2026-07-15T00:00:00Z",
    }


def _context() -> dict[str, Any]:
    return {
        "schemaVersion": "agent-fastq-qc-goal.v1",
        "analysis": "fastq-qc",
        "inputs": [
            {
                "uploadId": "upl_reads",
                "filename": "reads.fastq",
                "sha256": "a" * 64,
                "sizeBytes": 32,
                "mimeType": "text/plain",
            }
        ],
        "reportFormat": "multiqc-html",
    }


def _capability_graph() -> dict[str, Any]:
    registered = [
        _ready_tool("fastqc", "0.12.1"),
        _ready_tool("multiqc", "1.34"),
    ]
    return CapabilityGraphService().snapshot(
        registered_tools=registered,
        catalog={"items": [], "total": 0},
    )


def _ready_tool(profile_id: str, version: str) -> dict[str, Any]:
    package_spec = f"bioconda::{profile_id}={version}"
    return {
        "id": f"bioconda::{profile_id}",
        "name": profile_id,
        "source": "bioconda",
        "version": version,
        "packageSpec": package_spec,
        "targetPlatform": "linux-64",
        "toolRevisionId": f"bioconda::{profile_id}@{version}",
        "validationSummary": {
            "latestResultId": f"toolval_{profile_id}",
            "latestStatus": "passed",
            "evidenceId": f"evid_{profile_id}",
            "updatedAt": "2026-07-15T00:00:00Z",
        },
        "toolContract": {
            "state": "WorkflowReady",
            "workflowReady": True,
            "package": {
                "packageSpec": package_spec,
                "source": "bioconda",
                "version": version,
                "targetPlatform": "linux-64",
                "targetPlatformSupported": True,
            },
            "validation": {
                "dryRun": {"status": "passed"},
                "smokeRun": {"status": "passed"},
                "outputValidation": {"status": "passed"},
            },
        },
    }
