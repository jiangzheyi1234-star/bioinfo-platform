from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from apps.api.capability_graph_service import CapabilityGraphService
from apps.api.tool_profile_sources import all_tool_profiles
from apps.remote_runner.workflow_design_planner import plan_workflow_design_draft
from apps.remote_runner.workflow_design_service import compile_workflow_design_draft_export
from apps.remote_runner.workflow_design_storage import create_workflow_design_draft
from apps.remote_runner.workflow_revision_storage import fetch_workflow_revision
from core.contracts.capability_bundle import CAPABILITY_BUNDLE_VERSION
from tests.generated_workflow_test_helpers import test_tool_revision_id, upsert_ready_tool
from tests.helpers.workflow_design_drafts import workflow_design_config


REAL_TOOL_FIXTURES = {
    "fastqc": {"package": "fastqc", "version": "0.12.1", "toolName": "fastqc"},
    "fastp": {"package": "fastp", "version": "0.24.1", "toolName": "fastp"},
    "seqkit-stats": {"package": "seqkit", "version": "2.13.0", "toolName": "seqkit-stats"},
    "multiqc": {"package": "multiqc", "version": "1.25", "toolName": "multiqc"},
    "bracken": {"package": "bracken", "version": "2.9", "toolName": "bracken"},
}


def test_real_tool_bundle_gate_accepts_fixture_backed_profiles_and_blocks_unapproved_database_tool() -> None:
    registered = [_registered_ready_tool(profile_id) for profile_id in REAL_TOOL_FIXTURES]

    snapshot = CapabilityGraphService().snapshot(registered_tools=registered, catalog=_empty_catalog())

    assert snapshot["capabilityBundleVersion"] == CAPABILITY_BUNDLE_VERSION
    assert snapshot["capabilityBundleGate"] == {
        "capabilityBundleVersion": CAPABILITY_BUNDLE_VERSION,
        "total": 5,
        "selectable": 4,
        "blocked": 1,
        "blockedTools": [
            {
                "toolId": "bioconda::bracken",
                "toolRevisionId": "bioconda::bracken@2.9",
                "capabilityId": (
                    "capability-bundle-v1:h2ometa-metagenomics-core:bracken:"
                    "bioconda__bracken@2.9"
                ),
                "blockedReasons": ["CAPABILITY_APPROVAL_REQUIRED"],
                "nextAction": "request-approval",
            }
        ],
    }
    selectable_by_profile = {bundle["profileId"]: bundle for bundle in snapshot["capabilityBundles"]}
    assert set(selectable_by_profile) == {"fastqc", "fastp", "seqkit-stats", "multiqc"}
    assert {tool["name"] for tool in snapshot["agentSelectableTools"]} == {
        "fastqc",
        "fastp",
        "seqkit-stats",
        "multiqc",
    }

    for profile_id, bundle in selectable_by_profile.items():
        fixture = bundle["validationEvidence"]["fixture"]
        environment = bundle["environmentLock"]
        expected_package = REAL_TOOL_FIXTURES[profile_id]
        assert bundle["capabilityBundleVersion"] == CAPABILITY_BUNDLE_VERSION
        assert bundle["agentSelectable"] is True
        assert bundle["risk"]["level"] == "low"
        assert bundle["permissions"]["databases"] == []
        assert bundle["approval"] == {
            "required": False,
            "approved": True,
            "policyVersion": "",
            "reason": "low-risk-auto-approved",
        }
        assert environment["packageSpec"] == (
            f"bioconda::{expected_package['package']}={expected_package['version']}"
        )
        assert environment["dependencies"] == [environment["packageSpec"]]
        assert fixture["inputs"], profile_id
        assert fixture["expectedArtifacts"], profile_id
        assert {artifact["path"] for artifact in fixture["expectedArtifacts"]}

    approved = [_registered_ready_tool(profile_id, approved=True) for profile_id in REAL_TOOL_FIXTURES]
    approved_snapshot = CapabilityGraphService().snapshot(registered_tools=approved, catalog=_empty_catalog())

    assert approved_snapshot["capabilityBundleGate"]["selectable"] == 5
    bracken_bundle = next(bundle for bundle in approved_snapshot["capabilityBundles"] if bundle["profileId"] == "bracken")
    assert bracken_bundle["risk"] == {"level": "medium", "reasons": ["requires-database"]}
    assert bracken_bundle["permissions"]["databases"] == ["bracken_db"]
    assert bracken_bundle["approval"] == {
        "required": True,
        "approved": True,
        "policyVersion": "capability-approval-v1",
        "reason": "fixture database reviewed",
    }


def test_real_fastp_to_fastqc_bundle_compile_exports_run_config_report_and_revision_evidence(tmp_path: Path) -> None:
    cfg = workflow_design_config(tmp_path)
    upsert_ready_tool(cfg, _tool_manifest_from_profile("fastp"))
    upsert_ready_tool(cfg, _tool_manifest_from_profile("fastqc"))
    saved = create_workflow_design_draft(cfg, _fastp_to_fastqc_design())

    plan = plan_workflow_design_draft(
        cfg,
        saved["draft"],
        preview_root=tmp_path / "preview",
        draft_id=saved["draftId"],
        revision=saved["revision"],
    )

    assert plan["valid"] is True
    assert [step["id"] for step in plan["orderedSteps"]] == ["trim_reads", "qc_trimmed"]
    assert plan["resolvedPorts"]["qc_trimmed"]["inputs"]["reads"].endswith("trim_reads-fastp-cleaned.fastq")
    assert plan["exposedOutputs"]["trimmed_qc_html"]["mimeType"] == "text/html"
    assert plan["exposedOutputs"]["fastp_json"]["mimeType"] == "application/json"
    preview_config = json.loads(plan["previews"]["config"])
    assert [
        step["tool"]["capabilityBundle"]["capabilityBundleVersion"]
        for step in preview_config["workflow"]["steps"]
    ] == [CAPABILITY_BUNDLE_VERSION, CAPABILITY_BUNDLE_VERSION]
    assert preview_config["workflow"]["steps"][0]["tool"]["capabilityBundle"]["validationEvidence"]["fixture"][
        "expectedArtifacts"
    ]

    compiled = compile_workflow_design_draft_export(cfg, saved["draftId"])
    export_dir = Path(cfg.work_dir) / "workflow-design-exports" / saved["draftId"] / f"rev-{saved['revision']}"
    run_config = json.loads((export_dir / ".test" / "run-config.json").read_text(encoding="utf-8"))
    generated_rules = (export_dir / "workflow" / "rules" / "generated.smk").read_text(encoding="utf-8")

    assert "'v9.8.0/bio/fastp'" in generated_rules
    assert "'v9.8.0/bio/fastqc'" in generated_rules
    assert "workflow/envs/trim_reads-bioconda_fastp.yaml" in compiled["layout"]["envs"]
    assert "workflow/envs/qc_trimmed-bioconda_fastqc.yaml" in compiled["layout"]["envs"]
    assert (export_dir / "workflow" / "envs" / "trim_reads-bioconda_fastp.yaml").is_file()
    assert (export_dir / "workflow" / "envs" / "qc_trimmed-bioconda_fastqc.yaml").is_file()
    assert len(run_config["workflow"]["steps"]) == 2

    fastp_step = run_config["workflow"]["steps"][0]
    fastqc_step = run_config["workflow"]["steps"][1]
    assert fastp_step["tool"]["id"] == "bioconda::fastp"
    assert fastp_step["outputSpecs"]["json"]["mimeType"] == "application/json"
    assert fastp_step["tool"]["capabilityBundle"]["environmentLock"]["packageSpec"] == "bioconda::fastp=0.24.1"
    assert fastp_step["tool"]["capabilityBundle"]["validationEvidence"]["fixture"]["inputs"][0]["filename"] == (
        "reads.fastq"
    )
    assert {
        artifact["name"]
        for artifact in fastp_step["tool"]["capabilityBundle"]["validationEvidence"]["fixture"]["expectedArtifacts"]
    } == {"trimmed", "html", "json"}
    assert fastqc_step["tool"]["id"] == "bioconda::fastqc"
    assert fastqc_step["inputs"]["reads"].endswith("trim_reads-fastp-cleaned.fastq")
    assert fastqc_step["tool"]["capabilityBundle"]["selectionRationale"]["sourceOfTruth"] == CAPABILITY_BUNDLE_VERSION
    assert run_config["workflow"]["outputs"]["trimmed_qc_html"]["step"] == "qc_trimmed"
    assert run_config["workflow"]["outputs"]["fastp_json"]["step"] == "trim_reads"

    revision = fetch_workflow_revision(cfg, compiled["workflowRevisionId"])
    manifest_tools = revision["manifest"]["toolRevisions"]
    assert [item["capabilityBundleVersion"] for item in manifest_tools] == [
        CAPABILITY_BUNDLE_VERSION,
        CAPABILITY_BUNDLE_VERSION,
    ]
    assert [item["nextAction"] for item in manifest_tools] == ["execute-workflow-step", "execute-workflow-step"]
    assert manifest_tools[0]["validationEvidence"]["fixture"]["expectedArtifacts"]
    assert manifest_tools[1]["validationEvidence"]["fixture"]["expectedArtifacts"]
    assert compiled["capabilityBundleAudit"][0]["toolRevisionId"] == test_tool_revision_id("bioconda::fastp")
    assert compiled["capabilityBundleAudit"][1]["toolRevisionId"] == test_tool_revision_id("bioconda::fastqc")


def _registered_ready_tool(profile_id: str, *, approved: bool = False) -> dict[str, Any]:
    fixture = REAL_TOOL_FIXTURES[profile_id]
    package_name = fixture["package"]
    version = fixture["version"]
    package_spec = f"bioconda::{package_name}={version}"
    tool: dict[str, Any] = {
        "id": f"bioconda::{package_name}",
        "name": fixture["toolName"],
        "source": "bioconda",
        "version": version,
        "packageSpec": package_spec,
        "targetPlatform": "linux-64",
        "toolRevisionId": f"bioconda::{package_name}@{version}",
        "validationSummary": {
            "latestResultId": f"toolval_{package_name}",
            "latestStatus": "passed",
            "evidenceId": f"evid_{package_name}",
            "updatedAt": "2026-06-14T00:00:00Z",
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
                "dryRun": {"status": "passed", "checkedAt": "2026-06-14T00:00:00Z"},
                "smokeRun": {"status": "passed", "checkedAt": "2026-06-14T00:00:00Z"},
                "outputValidation": {"status": "passed", "checkedAt": "2026-06-14T00:00:00Z"},
            },
        },
    }
    if approved:
        tool["capabilityApproval"] = {
            "approved": True,
            "policyVersion": "capability-approval-v1",
            "reason": "fixture database reviewed",
        }
    return tool


def _tool_manifest_from_profile(profile_id: str) -> dict[str, Any]:
    profile = _profile(profile_id)
    fixture = REAL_TOOL_FIXTURES[profile_id]
    package_name = fixture["package"]
    version = fixture["version"]
    package_spec = f"bioconda::{package_name}={version}"
    return {
        "id": f"bioconda::{package_name}",
        "name": fixture["toolName"],
        "source": "bioconda",
        "version": version,
        "packageSpec": package_spec,
        "summary": f"P0-7B real bundle fixture for {profile_id}",
        "targetPlatform": "linux-64",
        "targetPlatformSupported": True,
        "ruleTemplate": _locked_rule_template(profile.rule_template, package_spec=package_spec),
    }


def _locked_rule_template(rule_template: dict[str, Any], *, package_spec: str) -> dict[str, Any]:
    template = deepcopy(rule_template)
    environment = template.get("environment") if isinstance(template.get("environment"), dict) else {}
    conda = environment.get("conda") if isinstance(environment.get("conda"), dict) else {}
    if conda:
        conda["dependencies"] = [
            package_spec if str(item or "").strip() == "{packageSpec}" else str(item or "").strip()
            for item in conda.get("dependencies") or []
            if str(item or "").strip()
        ]
        environment["conda"] = conda
        template["environment"] = environment
    return template


def _fastp_to_fastqc_design() -> dict[str, Any]:
    return {
        "contractVersion": "workflow-design-draft-v1",
        "engine": "snakemake",
        "metadata": {
            "name": "P0-7B fastp to fastqc acceptance",
            "description": "Real profile capability bundle compile fixture",
            "projectId": "proj_p0_7b",
            "tags": ["p0-7b", "real-tools"],
        },
        "inputs": [
            {
                "id": "reads",
                "role": "input",
                "path": "inputs/reads.fastq",
                "filename": "reads.fastq",
                "mimeType": "text/plain",
            }
        ],
        "nodes": [
            {
                "id": "trim_reads",
                "toolRevisionId": test_tool_revision_id("bioconda::fastp"),
                "inputs": {"sample": {"fromInput": "input"}},
                "params": {},
                "runtime": {"threads": 2, "schedulerResources": {"mem_mb": 2048}},
                "resources": {},
                "outputs": {"json": {"expose": True}},
                "metadata": {"capabilityBundleVersion": CAPABILITY_BUNDLE_VERSION},
                "provenance": {"source": "capability-bundle-v1"},
            },
            {
                "id": "qc_trimmed",
                "toolRevisionId": test_tool_revision_id("bioconda::fastqc"),
                "inputs": {},
                "params": {},
                "runtime": {"threads": 2, "schedulerResources": {"mem_mb": 2048}},
                "resources": {},
                "outputs": {"html": {"expose": True}},
                "metadata": {"capabilityBundleVersion": CAPABILITY_BUNDLE_VERSION},
                "provenance": {"source": "capability-bundle-v1"},
            },
        ],
        "edges": [
            {
                "from": {"nodeId": "trim_reads", "port": "trimmed"},
                "to": {"nodeId": "qc_trimmed", "port": "reads"},
                "audit": {
                    "source": "capability-bundle-v1",
                    "decision": "connect-compatible-ports",
                    "confidence": 1,
                    "reason": "fastp trimmed sequence_reads feeds fastqc reads",
                },
            }
        ],
        "resources": {"bindings": {}, "metadata": {"selectionMode": "capability-bundle"}},
        "outputs": [
            {"from": {"nodeId": "qc_trimmed", "port": "html"}, "as": "trimmed_qc_html"},
            {"from": {"nodeId": "trim_reads", "port": "json"}, "as": "fastp_json"},
        ],
        "provenance": {"createdBy": "p0-7b-test"},
    }


def _profile(profile_id: str) -> Any:
    return next(profile for profile in all_tool_profiles() if profile.profile_id == profile_id)


def _empty_catalog() -> dict[str, Any]:
    return {
        "items": [],
        "total": 0,
        "page": 1,
        "pageSize": 50,
        "hasMore": False,
        "sourceCounts": {
            "condaPackages": 0,
            "snakemakeWrappers": 0,
            "toolProfiles": 0,
        },
        "addableDraftCounts": {
            "condaPackages": 0,
            "snakemakeWrappers": 0,
            "toolProfiles": 0,
            "total": 0,
        },
        "qualityCounts": {
            "discovered": 0,
            "draftRunnable": 0,
            "workflowReady": 0,
            "productionEnabled": 0,
        },
    }
