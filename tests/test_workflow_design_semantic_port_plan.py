from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from apps.remote_runner.workflow_design_planner import plan_workflow_design_draft
from apps.remote_runner.workflow_design_storage import create_workflow_design_draft
from tests.generated_workflow_test_helpers import test_tool_revision_id, upsert_ready_tool
from tests.helpers.workflow_design_drafts import (
    workflow_design_config as _cfg,
    workflow_design_draft as _base_draft,
    workflow_design_tool_manifest as _base_tool,
)


def _alignment_source_tool(*, file_format: str) -> dict[str, Any]:
    tool = _base_tool(f"bioconda::source-{file_format}=1.0")
    tool["name"] = f"source-{file_format}"
    tool["ruleTemplate"]["outputs"][0].update(
        {
            "kind": "alignment",
            "data": "data_0863",
            "format": file_format,
            "mimeType": "application/octet-stream",
        }
    )
    return tool


def _alignment_consumer_tool(*, file_format: str) -> dict[str, Any]:
    tool = _base_tool(f"bioconda::consume-{file_format}=1.0")
    tool["name"] = f"consume-{file_format}"
    tool["ruleTemplate"]["inputs"][0].update(
        {
            "kind": "alignment",
            "data": "data_0863",
            "format": file_format,
            "mimeType": "application/octet-stream",
        }
    )
    return tool


def _sam_to_bam_converter(
    tool_id: str = "bioconda::sam-to-bam=1.0",
    *,
    type_only: bool = False,
    generic_only: bool = False,
    requires_database: bool = False,
) -> dict[str, Any]:
    tool = _base_tool(tool_id)
    tool["name"] = "sam-to-bam"
    tool["ruleTemplate"]["commandTemplate"] = "cp {input.sam:q} {output.bam:q}"
    if type_only:
        semantic_input = {"type": "file"}
        semantic_output = {"type": "file"}
    elif generic_only:
        semantic_input = {"type": "file", "format": "format_1915"}
        semantic_output = {"type": "file", "format": "format_1915"}
    else:
        semantic_input = {"type": "file", "kind": "alignment", "data": "data_0863", "format": "sam"}
        semantic_output = {"type": "file", "kind": "alignment", "data": "data_0863", "format": "bam"}
    tool["ruleTemplate"]["inputs"] = [{"name": "sam", "required": True, **semantic_input}]
    tool["ruleTemplate"]["outputs"] = [
        {
            "name": "bam",
            "path": "converted.bam",
            "mimeType": "application/octet-stream",
            **semantic_output,
        }
    ]
    if requires_database:
        tool["ruleTemplate"]["resources"] = {"ref": {"type": "database", "required": True}}
    tool["ruleTemplate"]["metadata"] = {"operation": "format conversion", "workflowStage": "conversion"}
    return tool


def _two_node_design(*, source_format: str, target_format: str) -> dict[str, Any]:
    source_id = f"bioconda::source-{source_format}=1.0"
    target_id = f"bioconda::consume-{target_format}=1.0"
    draft = _base_draft(source_id)
    draft["nodes"][0]["id"] = "source"
    draft["nodes"][0]["toolRevisionId"] = test_tool_revision_id(source_id)
    draft["nodes"].append(
        {
            "id": "target",
            "toolRevisionId": test_tool_revision_id(target_id),
            "inputs": {},
            "params": {"min_len": 80},
            "runtime": {"threads": 1, "schedulerResources": {"mem_mb": 128}},
            "resources": {},
            "outputs": {"report": {"expose": True}},
            "metadata": {},
            "provenance": {},
        }
    )
    draft["edges"] = [
        {
            "from": {"nodeId": "source", "port": "report"},
            "to": {"nodeId": "target", "port": "reads"},
        }
    ]
    draft["outputs"] = [{"from": {"nodeId": "target", "port": "report"}, "as": "target_report"}]
    return draft


def _plan(tmp_path: Path, draft: dict[str, Any]) -> dict[str, Any]:
    cfg = _cfg(tmp_path)
    saved = create_workflow_design_draft(cfg, draft)
    return plan_workflow_design_draft(
        cfg,
        saved["draft"],
        preview_root=tmp_path / "preview",
        draft_id=saved["draftId"],
        revision=saved["revision"],
    )


def test_semantic_port_plan_reports_compatible_edge(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    upsert_ready_tool(cfg, _alignment_source_tool(file_format="bam"))
    upsert_ready_tool(cfg, _alignment_consumer_tool(file_format="bam"))
    saved = create_workflow_design_draft(cfg, _two_node_design(source_format="bam", target_format="bam"))

    plan = plan_workflow_design_draft(
        cfg,
        saved["draft"],
        preview_root=tmp_path / "preview",
        draft_id=saved["draftId"],
        revision=saved["revision"],
    )

    assert plan["valid"] is True
    port_plan = plan["semanticPortPlan"]
    assert port_plan["schemaVersion"] == "h2ometa.workflow-design-semantic-port-plan.v1"
    assert port_plan["compatibleEdgeCount"] == 1
    edge = port_plan["edges"][0]
    assert edge["decision"]["compatible"] is True
    assert "format" in edge["decision"]["matchedFields"]
    assert edge["recommendation"]["action"] == "connect"
    assert edge["converterCandidates"] == []


def test_semantic_port_plan_recommends_one_hop_converter_for_incompatible_edge(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    upsert_ready_tool(cfg, _alignment_source_tool(file_format="sam"))
    upsert_ready_tool(cfg, _alignment_consumer_tool(file_format="bam"))
    upsert_ready_tool(cfg, _sam_to_bam_converter())
    saved = create_workflow_design_draft(cfg, _two_node_design(source_format="sam", target_format="bam"))

    plan = plan_workflow_design_draft(
        cfg,
        saved["draft"],
        preview_root=tmp_path / "preview",
        draft_id=saved["draftId"],
        revision=saved["revision"],
    )

    assert plan["valid"] is False
    edge = plan["semanticPortPlan"]["edges"][0]
    assert edge["decision"]["compatible"] is False
    assert edge["decision"]["mismatchedField"] == "format"
    assert edge["recommendation"]["action"] == "insert-converter"
    assert edge["recommendation"]["reasonCode"] == "ONE_HOP_CONVERTER_AVAILABLE"
    assert len(edge["converterCandidates"]) == 1
    candidate = edge["converterCandidates"][0]
    assert candidate["converterToolName"] == "sam-to-bam"
    assert candidate["inputPort"] == "sam"
    assert candidate["outputPort"] == "bam"
    assert candidate["confirmationRequired"] is True
    assert candidate["insertionMode"] == "explicit-user-confirmed"
    assert candidate["inputDecision"]["compatible"] is True
    assert candidate["outputDecision"]["compatible"] is True
    serialized = json.dumps(plan["semanticPortPlan"], sort_keys=True)
    assert "commandTemplate" not in serialized
    assert "ruleTemplate" not in serialized
    assert "converterPath" not in serialized


def test_semantic_port_plan_excludes_type_only_and_generic_converter_candidates(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    upsert_ready_tool(cfg, _alignment_source_tool(file_format="sam"))
    upsert_ready_tool(cfg, _alignment_consumer_tool(file_format="bam"))
    upsert_ready_tool(cfg, _sam_to_bam_converter("bioconda::type-only=1.0", type_only=True))
    upsert_ready_tool(cfg, _sam_to_bam_converter("bioconda::generic-only=1.0", generic_only=True))
    saved = create_workflow_design_draft(cfg, _two_node_design(source_format="sam", target_format="bam"))

    plan = plan_workflow_design_draft(
        cfg,
        saved["draft"],
        preview_root=tmp_path / "preview",
        draft_id=saved["draftId"],
        revision=saved["revision"],
    )

    edge = plan["semanticPortPlan"]["edges"][0]
    assert edge["recommendation"]["action"] == "block"
    assert edge["recommendation"]["reasonCode"] == "PORTS_INCOMPATIBLE"
    assert edge["converterCandidates"] == []


def test_semantic_port_plan_excludes_database_resource_converter(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    upsert_ready_tool(cfg, _alignment_source_tool(file_format="sam"))
    upsert_ready_tool(cfg, _alignment_consumer_tool(file_format="bam"))
    upsert_ready_tool(cfg, _sam_to_bam_converter(requires_database=True))
    saved = create_workflow_design_draft(cfg, _two_node_design(source_format="sam", target_format="bam"))

    plan = plan_workflow_design_draft(
        cfg,
        saved["draft"],
        preview_root=tmp_path / "preview",
        draft_id=saved["draftId"],
        revision=saved["revision"],
    )

    edge = plan["semanticPortPlan"]["edges"][0]
    assert edge["recommendation"]["action"] == "block"
    assert edge["converterCandidates"] == []


def test_semantic_port_plan_reports_unresolved_edge_without_runnable_spec(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    upsert_ready_tool(cfg, _alignment_source_tool(file_format="bam"))
    upsert_ready_tool(cfg, _alignment_consumer_tool(file_format="bam"))
    draft = _two_node_design(source_format="bam", target_format="bam")
    draft["edges"][0]["from"]["port"] = "missing"
    saved = create_workflow_design_draft(cfg, draft)

    plan = plan_workflow_design_draft(
        cfg,
        saved["draft"],
        preview_root=tmp_path / "preview",
        draft_id=saved["draftId"],
        revision=saved["revision"],
    )

    assert plan["valid"] is False
    edge = plan["semanticPortPlan"]["edges"][0]
    assert edge["recommendation"]["action"] == "block"
    assert edge["recommendation"]["reasonCode"] == "SOURCE_PORT_UNRESOLVED"
    assert plan["runSpec"] == {}
