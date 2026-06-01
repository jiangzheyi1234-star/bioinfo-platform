from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from apps.remote_runner.config import ensure_runtime_layout
from apps.remote_runner.generated_workflow import GENERATED_TOOL_RUN_PIPELINE_ID
from apps.remote_runner.generated_workflow_graph import (
    GENERATED_WORKFLOW_RULE_CONTRACT_VERSION,
    normalize_generated_workflow_graph,
)
from apps.remote_runner.generated_workflow_plan import plan_generated_workflow_steps
from apps.remote_runner.tool_revisions import fetch_tool_revision
from apps.remote_runner.tools import update_registered_tool_rule_template
from tests.test_tool_contract_pipeline import _cfg, _rule_contract_fields
from tests.test_tool_prepare_contract import _prepare_tool_payload, _publish_tool_candidate


def test_prepare_publishes_immutable_tool_revisions(monkeypatch, tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)

    monkeypatch.setattr("apps.remote_runner.tool_preparation.run_tool_contract_validation", _passing_validation)

    first_payload = _prepare_tool_payload("conda-forge::revision-demo", "revision-demo")
    first_payload["ruleTemplate"]["outputs"] = [{"name": "report", "path": "report.txt"}]
    first = _publish_tool_candidate(cfg, first_payload)
    first_revision_id = first["toolRevisionId"]

    assert first["status"] == "published"
    assert first["revision"] == 1
    assert first_revision_id.startswith("conda-forge::revision-demo#")
    assert fetch_tool_revision(cfg, first_revision_id)["ruleTemplate"]["commandTemplate"] == "cp {input.primary:q} {output.report:q}"

    update_registered_tool_rule_template(
        cfg,
        "conda-forge::revision-demo",
        {
            "commandTemplate": "printf 'edited' > {output.report:q}",
            "inputs": [{"name": "primary", "type": "file", "required": True}],
            "outputs": [{"name": "report", "path": "edited.txt"}],
            **_rule_contract_fields(),
            "environment": {
                "conda": {
                    "channels": ["conda-forge", "bioconda"],
                    "dependencies": ["conda-forge::revision-demo=1.0"],
                }
            },
            "smokeTest": {"inputs": {"primary": {"filename": "input.txt", "content": "smoke\n"}}},
        },
    )

    first_revision = fetch_tool_revision(cfg, first_revision_id)
    assert first_revision["ruleTemplate"]["commandTemplate"] == "cp {input.primary:q} {output.report:q}"

    second_payload = _prepare_tool_payload("conda-forge::revision-demo", "revision-demo")
    second_payload["ruleTemplate"] = {
        **second_payload["ruleTemplate"],
        "commandTemplate": "printf 'v2' > {output.report:q}",
        "outputs": [{"name": "report", "path": "report.txt"}],
    }
    second = _publish_tool_candidate(cfg, second_payload)

    assert second["toolRevisionId"].startswith("conda-forge::revision-demo#")
    assert second["toolRevisionId"] != first_revision_id
    assert fetch_tool_revision(cfg, second["toolRevisionId"])["ruleTemplate"]["commandTemplate"] == "printf 'v2' > {output.report:q}"
    assert fetch_tool_revision(cfg, first_revision_id)["ruleTemplate"]["commandTemplate"] == "cp {input.primary:q} {output.report:q}"

    duplicate = _publish_tool_candidate(cfg, second_payload)
    assert duplicate["toolRevisionId"] == second["toolRevisionId"]


def test_generated_workflow_graph_requires_tool_revision_id(monkeypatch, tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    monkeypatch.setattr("apps.remote_runner.tool_preparation.run_tool_contract_validation", _passing_validation)
    published = _publish_tool_candidate(cfg, _prepare_tool_payload("conda-forge::revision-run", "revision-run"))
    revision_id = published["toolRevisionId"]
    input_path = tmp_path / "input.txt"
    input_path.write_text("smoke\n", encoding="utf-8")

    workflow = {
        "contractVersion": GENERATED_WORKFLOW_RULE_CONTRACT_VERSION,
        "nodes": [
            {
                "id": "copy",
                "toolRevisionId": revision_id,
                "inputs": {"primary": {"fromInput": "input"}},
                "params": {},
                "runtime": {},
            }
        ],
        "edges": [],
    }
    normalized = normalize_generated_workflow_graph(workflow)

    assert normalized["steps"][0]["toolRevisionId"] == revision_id
    assert "tool" not in normalized["steps"][0]

    plan = plan_generated_workflow_steps(
        cfg,
        run_spec={"pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID, "workflow": workflow},
        resolved_inputs=[{"role": "input", "path": str(input_path), "filename": input_path.name}],
        result_dir=tmp_path / "results",
    )

    assert plan.steps[0].tool_revision_id == revision_id
    assert plan.steps[0].tool_id == "conda-forge::revision-run"
    assert plan.steps[0].rule_template["commandTemplate"] == "cp {input.primary:q} {output.report:q}"

    with pytest.raises(ValueError, match="WORKFLOW_GRAPH_NODE_UNSUPPORTED_FIELD: legacy.tool"):
        normalize_generated_workflow_graph(
            {
                "contractVersion": GENERATED_WORKFLOW_RULE_CONTRACT_VERSION,
                "nodes": [{"id": "legacy", "tool": {"id": "conda-forge::revision-run"}}],
                "edges": [],
            }
        )


def _passing_validation(_cfg: Any, _tool: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "message": "Tool contract validation passed.",
        "contractStatus": {
            "dryRun": {"status": "passed", "message": "dry-run passed"},
            "smokeRun": {"status": "passed", "message": "smoke passed"},
            "outputValidation": {"status": "passed", "message": "output passed"},
            "production": {"status": "not_run", "message": ""},
        },
    }
