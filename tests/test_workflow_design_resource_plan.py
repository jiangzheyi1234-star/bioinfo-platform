from __future__ import annotations

from pathlib import Path

from apps.remote_runner.workflow_design_planner import plan_workflow_design_draft
from apps.remote_runner.workflow_design_storage import create_workflow_design_draft
from tests.generated_workflow_test_helpers import upsert_ready_tool
from tests.test_workflow_design_drafts import _cfg, _draft, _tool_manifest


def _database_resource_tool() -> dict:
    tool = _tool_manifest("bioconda::db-qc=1.0")
    tool["ruleTemplate"]["resources"] = {
        "reference_database": {
            "type": "database",
            "acceptedTemplates": ["custom"],
            "acceptedCapabilities": ["reference_database"],
            "configKey": "reference_db",
        }
    }
    tool["ruleTemplate"]["schedulerResources"] = {"mem_mb": 128}
    return tool


def test_plan_reports_required_resources_when_database_binding_is_missing(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    upsert_ready_tool(cfg, _database_resource_tool())
    saved = create_workflow_design_draft(cfg, _draft("bioconda::db-qc=1.0"))

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
            "code": "WORKFLOW_RESOURCE_BINDING_REQUIRED",
            "message": "WORKFLOW_RESOURCE_BINDING_REQUIRED: reference_database",
        }
    ]
    assert plan["requiredResources"] == {
        "reference_database": {
            "type": "database",
            "acceptedTemplates": ["custom"],
            "acceptedCapabilities": ["reference_database"],
            "configKey": "reference_db",
        }
    }
    assert plan["requiredDatabases"] == {}
    assert plan["previews"] == {"snakefile": "", "config": ""}
    assert plan["runSpec"] == {}
