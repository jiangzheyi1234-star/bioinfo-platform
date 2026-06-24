from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from apps.remote_runner.workflow_design_compiler import compile_workflow_design_project
from apps.remote_runner.workflow_design_planner import plan_workflow_design_draft
from apps.remote_runner.workflow_design_storage import create_workflow_design_draft
from tests.generated_workflow_test_helpers import test_tool_revision_id, upsert_ready_tool
from tests.test_workflow_design_drafts import _cfg, _draft, _tool_manifest


def _source_tool() -> dict[str, Any]:
    tool = _tool_manifest("bioconda::source=1.0")
    tool["ruleTemplate"]["outputs"][0]["kind"] = "reads"
    tool["ruleTemplate"]["outputs"][0]["format"] = "fastq"
    return tool


def _converter_tool() -> dict[str, Any]:
    tool = _tool_manifest("bioconda::sam-to-bam=1.0")
    tool["name"] = "sam-to-bam"
    tool["ruleTemplate"]["commandTemplate"] = "cp {input.reads:q} {output.bam:q}"
    tool["ruleTemplate"]["inputs"] = [{"name": "reads", "required": True, "kind": "reads", "format": "fastq"}]
    tool["ruleTemplate"]["outputs"] = [
        {
            "name": "bam",
            "path": "converted.bam",
            "kind": "alignment_bam",
            "format": "bam",
            "mimeType": "application/octet-stream",
        }
    ]
    return tool


def _bam_consumer_tool() -> dict[str, Any]:
    tool = _tool_manifest("bioconda::bam-qc=1.0")
    tool["name"] = "bam-qc"
    tool["ruleTemplate"]["inputs"][0]["kind"] = "alignment_bam"
    tool["ruleTemplate"]["inputs"][0]["format"] = "bam"
    return tool


def _two_step_draft(*, edge_output: str = "report", exposed_output: str = "report") -> dict[str, Any]:
    draft = _draft("bioconda::source=1.0")
    draft["nodes"][0]["id"] = "source"
    draft["nodes"][0]["toolRevisionId"] = test_tool_revision_id("bioconda::source=1.0")
    draft["nodes"].append(
        {
            "id": "copy",
            "toolRevisionId": test_tool_revision_id("bioconda::copy=1.0"),
            "inputs": {},
            "params": {},
            "runtime": {"threads": 1, "schedulerResources": {"mem_mb": 128}},
            "resources": {},
            "outputs": {"report": {"expose": True}},
            "metadata": {},
            "provenance": {},
        }
    )
    draft["edges"] = [
        {
            "from": {"nodeId": "source", "port": edge_output},
            "to": {"nodeId": "copy", "port": "reads"},
        }
    ]
    draft["outputs"] = [{"from": {"nodeId": "copy", "port": exposed_output}, "as": "copied_report"}]
    return draft


def _converter_inserted_draft() -> dict[str, Any]:
    draft = _draft("bioconda::source=1.0")
    draft["nodes"][0]["id"] = "source"
    draft["nodes"][0]["toolRevisionId"] = test_tool_revision_id("bioconda::source=1.0")
    draft["nodes"].append(
        {
            "id": "sam_to_bam_converter",
            "toolRevisionId": test_tool_revision_id("bioconda::sam-to-bam=1.0"),
            "inputs": {},
            "params": {"min_len": 50},
            "runtime": {"threads": 1, "schedulerResources": {"mem_mb": 128}},
            "resources": {},
            "outputs": {},
            "metadata": {},
            "provenance": {},
        }
    )
    draft["nodes"].append(
        {
            "id": "target",
            "toolRevisionId": test_tool_revision_id("bioconda::bam-qc=1.0"),
            "inputs": {},
            "params": {"min_len": 50},
            "runtime": {"threads": 1, "schedulerResources": {"mem_mb": 128}},
            "resources": {},
            "outputs": {"report": {"expose": True}},
            "metadata": {},
            "provenance": {},
        }
    )
    edge_audit = {
        "source": "auto",
        "decision": "recommended",
        "confidence": 0.85,
        "reason": "one-hop converter",
        "hardChecks": "[\"one-hop-converter\"]",
        "evidence": "[\"source -> converter -> target\"]",
    }
    draft["edges"] = [
        {
            "from": {"nodeId": "source", "port": "report"},
            "to": {"nodeId": "sam_to_bam_converter", "port": "reads"},
            "audit": edge_audit,
        },
        {
            "from": {"nodeId": "sam_to_bam_converter", "port": "bam"},
            "to": {"nodeId": "target", "port": "reads"},
            "audit": edge_audit,
        },
    ]
    draft["outputs"] = [{"from": {"nodeId": "target", "port": "report"}, "as": "target_report"}]
    return draft


def test_plan_accepts_confirmed_converter_as_plain_v1_graph(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    upsert_ready_tool(cfg, _source_tool())
    upsert_ready_tool(cfg, _converter_tool())
    upsert_ready_tool(cfg, _bam_consumer_tool())
    saved = create_workflow_design_draft(cfg, _converter_inserted_draft())

    plan = plan_workflow_design_draft(
        cfg,
        saved["draft"],
        preview_root=tmp_path / "preview",
        draft_id=saved["draftId"],
        revision=saved["revision"],
    )

    assert plan["valid"] is True
    assert plan["validationIssues"] == []
    assert [step["id"] for step in plan["orderedSteps"]] == ["source", "sam_to_bam_converter", "target"]
    assert [edge["to"]["nodeId"] for edge in plan["normalizedGraph"]["edges"]] == ["sam_to_bam_converter", "target"]
    assert plan["normalizedGraph"]["edges"][0]["audit"]["source"] == "auto"
    assert all("audit" not in edge for edge in plan["runSpec"]["workflow"]["edges"])
    assert "converterPath" not in str(plan["normalizedGraph"])
    assert "converterPath" not in str(plan["runSpec"])


def test_plan_validates_declared_workflow_input_semantics(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    tool = _tool_manifest("bioconda::qc=1.0")
    tool["ruleTemplate"]["inputs"][0].update(
        {
            "type": "file",
            "kind": "reads",
            "data": "data_2044",
            "format": "fastq",
        }
    )
    upsert_ready_tool(cfg, tool)
    draft = _draft("bioconda::qc=1.0")
    draft["inputs"][0].update(
        {
            "type": "file",
            "kind": "reads",
            "data": "http://edamontology.org/data_2044",
            "format": "EDAM:format_1930",
        }
    )
    saved = create_workflow_design_draft(cfg, draft)

    plan = plan_workflow_design_draft(
        cfg,
        saved["draft"],
        preview_root=tmp_path / "preview",
        draft_id=saved["draftId"],
        revision=saved["revision"],
    )

    assert plan["valid"] is True
    assert plan["validationIssues"] == []
    assert plan["normalizedGraph"]["inputs"][0]["format"] == "EDAM:format_1930"
    assert plan["runSpec"]["inputs"][0] == {"role": "input", "filename": "reads.fastq"}
    assert '"format": "EDAM:format_1930"' in plan["previews"]["config"]


def test_plan_and_compile_reject_declared_workflow_input_semantic_conflict(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    upsert_ready_tool(cfg, _bam_consumer_tool())
    draft = _draft("bioconda::bam-qc=1.0")
    draft["inputs"][0].update(
        {
            "type": "file",
            "kind": "reads",
            "data": "data_2044",
            "format": "fastq",
        }
    )
    saved = create_workflow_design_draft(cfg, draft)

    plan = plan_workflow_design_draft(
        cfg,
        saved["draft"],
        preview_root=tmp_path / "preview",
        draft_id=saved["draftId"],
        revision=saved["revision"],
    )

    assert plan["valid"] is False
    assert plan["validationIssues"] == [
        {
            "code": "WORKFLOW_STEP_INPUT_OUTPUT_INCOMPATIBLE",
            "message": "WORKFLOW_STEP_INPUT_OUTPUT_INCOMPATIBLE: input.input -> reads",
        }
    ]
    with pytest.raises(ValueError, match="WORKFLOW_STEP_INPUT_OUTPUT_INCOMPATIBLE: input.input -> reads"):
        compile_workflow_design_project(
            cfg,
            saved["draft"],
            export_dir=tmp_path / "export",
            draft_id=saved["draftId"],
            revision=saved["revision"],
        )


def test_plan_reports_graph_edge_validation_issues_without_runnable_spec(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    upsert_ready_tool(cfg, _source_tool())
    upsert_ready_tool(cfg, _tool_manifest("bioconda::copy=1.0"))
    saved = create_workflow_design_draft(cfg, _two_step_draft(edge_output="missing"))

    plan = plan_workflow_design_draft(
        cfg,
        saved["draft"],
        preview_root=tmp_path / "preview",
        draft_id=saved["draftId"],
        revision=saved["revision"],
    )

    assert plan["valid"] is False
    assert plan["validationIssues"] == [
        {
            "code": "WORKFLOW_STEP_INPUT_OUTPUT_UNKNOWN",
            "message": "WORKFLOW_STEP_INPUT_OUTPUT_UNKNOWN: source.missing",
        }
    ]
    assert plan["normalizedGraph"]["edges"][0]["from"] == {"nodeId": "source", "port": "missing"}
    assert plan["orderedSteps"] == []
    assert plan["resolvedPorts"] == {}
    assert plan["previews"] == {"snakefile": "", "config": ""}
    assert plan["runSpec"] == {}


def test_plan_reports_exposed_output_validation_issues_without_runnable_spec(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    upsert_ready_tool(cfg, _source_tool())
    upsert_ready_tool(cfg, _tool_manifest("bioconda::copy=1.0"))
    saved = create_workflow_design_draft(cfg, _two_step_draft(exposed_output="missing"))

    plan = plan_workflow_design_draft(
        cfg,
        saved["draft"],
        preview_root=tmp_path / "preview",
        draft_id=saved["draftId"],
        revision=saved["revision"],
    )

    assert plan["valid"] is False
    assert plan["validationIssues"] == [
        {
            "code": "WORKFLOW_OUTPUT_NAME_UNKNOWN",
            "message": "WORKFLOW_OUTPUT_NAME_UNKNOWN: copy.missing",
        }
    ]
    assert plan["normalizedGraph"]["outputs"] == [
        {"from": {"nodeId": "copy", "port": "missing"}, "as": "copied_report", "metadata": {}}
    ]
    assert plan["previews"] == {"snakefile": "", "config": ""}
    assert plan["runSpec"] == {}


def test_plan_reports_unknown_input_role_without_runnable_spec(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    upsert_ready_tool(cfg, _tool_manifest("bioconda::source=1.0"))
    draft = _draft("bioconda::source=1.0")
    draft["nodes"][0]["inputs"]["reads"] = {"fromInput": "missing_role"}
    saved = create_workflow_design_draft(cfg, draft)

    plan = plan_workflow_design_draft(
        cfg,
        saved["draft"],
        preview_root=tmp_path / "preview",
        draft_id=saved["draftId"],
        revision=saved["revision"],
    )

    assert plan["valid"] is False
    assert plan["validationIssues"] == [
        {
            "code": "WORKFLOW_STEP_INPUT_ROLE_UNKNOWN",
            "message": "WORKFLOW_STEP_INPUT_ROLE_UNKNOWN: missing_role",
        }
    ]
    assert plan["normalizedGraph"]["nodes"][0]["inputs"]["reads"] == {"fromInput": "missing_role"}
    assert plan["orderedSteps"] == []
    assert plan["resolvedPorts"] == {}
    assert plan["previews"] == {"snakefile": "", "config": ""}
    assert plan["runSpec"] == {}
