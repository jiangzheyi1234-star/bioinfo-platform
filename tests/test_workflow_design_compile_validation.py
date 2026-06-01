from __future__ import annotations

from pathlib import Path
from typing import Any

from apps.remote_runner.workflow_design_compiler import compile_workflow_design_project
from apps.remote_runner.workflow_design_storage import create_workflow_design_draft
from tests.generated_workflow_test_helpers import test_tool_revision_id, upsert_ready_tool
from tests.test_workflow_design_drafts import _cfg, _draft, _tool_manifest


def test_compile_validation_failure_preserves_existing_export(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    upsert_ready_tool(cfg, _tool_manifest("bioconda::source=1.0"))
    export_dir = tmp_path / "export"
    existing_files = {
        export_dir / "workflow" / "Snakefile": "previous snakefile",
        export_dir / "config" / "config.yaml": "previous config",
        export_dir / ".test" / "run-config.json": '{"previous": true}',
        export_dir / "README.md": "previous readme",
    }
    for path, content in existing_files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    draft = _draft("bioconda::source=1.0")
    draft["nodes"][0]["inputs"]["reads"] = {"fromInput": "missing_role"}

    try:
        compile_workflow_design_project(
            cfg,
            draft,
            export_dir=export_dir,
            draft_id="wfd_invalid",
            revision=1,
        )
    except ValueError as exc:
        assert str(exc) == "WORKFLOW_STEP_INPUT_ROLE_UNKNOWN: missing_role"
    else:
        raise AssertionError("invalid WorkflowDesignDraft should not be exported")

    for path, content in existing_files.items():
        assert path.read_text(encoding="utf-8") == content


def test_compile_asset_materialization_failure_preserves_existing_export(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    for tool_id, content in [
        ("bioconda::script-a=1.0", "from pathlib import Path\nPath(snakemake.output.report).write_text('a')\n"),
        ("bioconda::script-b=1.0", "from pathlib import Path\nPath(snakemake.output.report).write_text('b')\n"),
    ]:
        upsert_ready_tool(cfg, _script_tool(tool_id, content))
    export_dir = tmp_path / "export"
    existing_files = {
        export_dir / "workflow" / "Snakefile": "previous snakefile",
        export_dir / "config" / "config.yaml": "previous config",
        export_dir / ".test" / "run-config.json": '{"previous": true}',
        export_dir / "README.md": "previous readme",
    }
    for path, content in existing_files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    saved = create_workflow_design_draft(cfg, _script_conflict_draft())

    try:
        compile_workflow_design_project(
            cfg,
            saved["draft"],
            export_dir=export_dir,
            draft_id=saved["draftId"],
            revision=saved["revision"],
        )
    except ValueError as exc:
        assert str(exc) == "TOOL_RULE_SCRIPT_ASSET_CONFLICT: scripts/run.py"
    else:
        raise AssertionError("conflicting script assets should fail before replacing an existing export")

    for path, content in existing_files.items():
        assert path.read_text(encoding="utf-8") == content


def _script_tool(tool_id: str, script_content: str) -> dict[str, Any]:
    return {
        "id": tool_id,
        "name": tool_id.rsplit("::", 1)[-1],
        "source": "bioconda",
        "version": "1.0",
        "packageSpec": "bioconda::python=3.12",
        "ruleTemplate": {
            "script": "scripts/run.py",
            "scriptAssets": [{"path": "scripts/run.py", "content": script_content}],
            "inputs": [
                {
                    "name": "reads",
                    "type": "file",
                    "kind": "text",
                    "mimeType": "text/plain",
                    "required": True,
                }
            ],
            "outputs": [
                {
                    "name": "report",
                    "path": "report.txt",
                    "kind": "text",
                    "mimeType": "text/plain",
                }
            ],
            "schedulerResources": {"mem_mb": 128},
        },
    }


def _script_conflict_draft() -> dict[str, Any]:
    draft = _draft("bioconda::script-a=1.0")
    draft["nodes"][0]["id"] = "first"
    draft["nodes"][0]["toolRevisionId"] = test_tool_revision_id("bioconda::script-a=1.0")
    draft["nodes"][0]["inputs"] = {"reads": {"fromInput": "input"}}
    draft["nodes"][0]["params"] = {}
    draft["nodes"].append(
        {
            "id": "second",
            "toolRevisionId": test_tool_revision_id("bioconda::script-b=1.0"),
            "inputs": {},
            "params": {},
            "runtime": {"threads": 1, "schedulerResources": {"mem_mb": 128}},
            "resources": {},
            "outputs": {"report": {"expose": True}},
            "metadata": {},
            "provenance": {},
        }
    )
    draft["edges"] = [{"from": {"nodeId": "first", "port": "report"}, "to": {"nodeId": "second", "port": "reads"}}]
    draft["outputs"] = [{"from": {"nodeId": "second", "port": "report"}, "as": "final_report"}]
    return draft
