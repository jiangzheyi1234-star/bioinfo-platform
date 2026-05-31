from __future__ import annotations

from pathlib import Path
from typing import Any

from apps.remote_runner.workflow_design_planner import plan_workflow_design_draft
from apps.remote_runner.workflow_design_storage import create_workflow_design_draft
from tests.generated_workflow_test_helpers import upsert_ready_tool
from tests.test_workflow_design_drafts import _cfg, _draft, _tool_manifest


def _source_tool() -> dict[str, Any]:
    tool = _tool_manifest("bioconda::source=1.0")
    tool["ruleTemplate"]["outputs"][0]["kind"] = "reads"
    tool["ruleTemplate"]["outputs"][0]["format"] = "fastq"
    return tool


def _two_step_draft(*, edge_output: str = "report", exposed_output: str = "report") -> dict[str, Any]:
    draft = _draft("bioconda::source=1.0")
    draft["nodes"][0]["id"] = "source"
    draft["nodes"][0]["toolId"] = "bioconda::source=1.0"
    draft["nodes"].append(
        {
            "id": "copy",
            "toolId": "bioconda::copy=1.0",
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
