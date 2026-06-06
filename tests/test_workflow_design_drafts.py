from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from apps.remote_runner.generated_workflow import GENERATED_TOOL_RUN_PIPELINE_ID
from apps.remote_runner.generated_workflow_plan import plan_generated_workflow_steps
from apps.remote_runner.api_models import WorkflowDesignDraftCreateRequest, WorkflowDesignDraftPlanRequest
from apps.remote_runner.databases import add_reference_database
from apps.remote_runner.pipeline import get_pipeline
from apps.remote_runner.preflight import RunPreflightError, preflight_run_spec
from core.contracts.workflow_design import workflow_design_graph, workflow_design_to_generated_run_spec
from apps.remote_runner.workflow_design_compiler import compile_workflow_design_project
from apps.remote_runner.workflow_design_planner import plan_workflow_design_draft
from apps.remote_runner.workflow_design_storage import (
    create_workflow_design_draft,
    fetch_workflow_design_draft,
    fork_workflow_design_draft,
    list_workflow_design_drafts,
    update_workflow_design_draft,
)
from tests.generated_workflow_test_helpers import test_tool_revision_id, upsert_ready_tool
from tests.helpers.workflow_design_drafts import (
    workflow_design_config as _cfg,
    workflow_design_draft as _draft,
    workflow_design_tool_manifest as _tool_manifest,
)


def test_workflow_design_draft_payloads_are_strict() -> None:
    with pytest.raises(ValidationError) as exc_info:
        WorkflowDesignDraftCreateRequest.model_validate({"draft": _draft(), "legacyRunSpec": {}})

    assert exc_info.value.errors()[0]["type"] == "extra_forbidden"

    invalid = _draft()
    invalid["nodes"][0]["ruleTemplate"] = {"commandTemplate": "echo bypass"}
    with pytest.raises(ValidationError) as node_exc:
        WorkflowDesignDraftCreateRequest.model_validate({"draft": invalid})

    assert node_exc.value.errors()[0]["type"] == "extra_forbidden"

    duplicate_edge_input = _draft()
    duplicate_edge_input["nodes"][0]["inputs"]["reads"] = {"fromStep": "upstream", "output": "reads"}
    with pytest.raises(ValidationError):
        WorkflowDesignDraftCreateRequest.model_validate({"draft": duplicate_edge_input})

    executable_audit = _draft()
    executable_audit["edges"] = [
        {
            "from": {"nodeId": "qc", "port": "report"},
            "to": {"nodeId": "qc", "port": "reads"},
            "audit": {"ruleTemplate": {"commandTemplate": "echo bypass"}},
        }
    ]
    with pytest.raises(ValidationError):
        WorkflowDesignDraftCreateRequest.model_validate({"draft": executable_audit})

    scalar_audit = _draft()
    scalar_audit["edges"] = [
        {
            "from": {"nodeId": "qc", "port": "report"},
            "to": {"nodeId": "qc", "port": "reads"},
            "audit": {"source": "manual", "confidence": 1},
        }
    ]
    validated = WorkflowDesignDraftCreateRequest.model_validate({"draft": scalar_audit})
    assert workflow_design_graph(validated.draft)["edges"][0]["audit"] == {"source": "manual", "confidence": 1}
    assert "audit" not in workflow_design_to_generated_run_spec(validated.draft)["workflow"]["edges"][0]

    positional_upload_input = _draft()
    positional_upload_input["nodes"][0]["inputs"]["reads"] = {"fromUpload": 0}
    with pytest.raises(ValidationError):
        WorkflowDesignDraftCreateRequest.model_validate({"draft": positional_upload_input})

    duplicate_roles = _draft()
    duplicate_roles["inputs"].append(
        {
            "id": "reads_2",
            "role": "input",
            "path": "inputs/reads-2.fastq",
            "mimeType": "text/plain",
        }
    )
    with pytest.raises(ValidationError, match="WORKFLOW_DESIGN_INPUT_ROLE_DUPLICATE"):
        WorkflowDesignDraftCreateRequest.model_validate({"draft": duplicate_roles})

    duplicate_input_ids = _draft()
    duplicate_input_ids["inputs"].append(
        {
            "id": "reads",
            "role": "reads_2",
            "path": "inputs/reads-2.fastq",
            "mimeType": "text/plain",
        }
    )
    with pytest.raises(ValidationError, match="WORKFLOW_DESIGN_INPUT_ID_DUPLICATE"):
        WorkflowDesignDraftCreateRequest.model_validate({"draft": duplicate_input_ids})

    duplicate_nodes = _draft()
    duplicate_nodes["nodes"].append(dict(duplicate_nodes["nodes"][0]))
    with pytest.raises(ValidationError, match="WORKFLOW_DESIGN_NODE_ID_DUPLICATE"):
        WorkflowDesignDraftCreateRequest.model_validate({"draft": duplicate_nodes})

    normalized_duplicate_nodes = _draft()
    normalized_duplicate_nodes["nodes"][0]["id"] = "qc step"
    normalized_duplicate_nodes["outputs"][0]["from"]["nodeId"] = "qc step"
    normalized_duplicate_nodes["nodes"].append(
        {
            **dict(normalized_duplicate_nodes["nodes"][0]),
            "id": "qc_step",
            "inputs": {},
        }
    )
    with pytest.raises(ValidationError, match="WORKFLOW_DESIGN_NODE_ID_NORMALIZED_DUPLICATE"):
        WorkflowDesignDraftCreateRequest.model_validate({"draft": normalized_duplicate_nodes})

    duplicate_outputs = _draft()
    duplicate_outputs["outputs"].append({"from": {"nodeId": "qc", "port": "report"}, "as": "qc_report"})
    with pytest.raises(ValidationError, match="WORKFLOW_DESIGN_OUTPUT_ALIAS_DUPLICATE"):
        WorkflowDesignDraftCreateRequest.model_validate({"draft": duplicate_outputs})

    normalized_duplicate_outputs = _draft()
    normalized_duplicate_outputs["outputs"][0]["as"] = "qc-report"
    normalized_duplicate_outputs["outputs"].append({"from": {"nodeId": "qc", "port": "report"}, "as": "qc_report"})
    with pytest.raises(ValidationError, match="WORKFLOW_DESIGN_OUTPUT_ALIAS_NORMALIZED_DUPLICATE"):
        WorkflowDesignDraftCreateRequest.model_validate({"draft": normalized_duplicate_outputs})

    reserved_duplicate_outputs = _draft()
    reserved_duplicate_outputs["outputs"][0]["as"] = "count"
    reserved_duplicate_outputs["outputs"].append({"from": {"nodeId": "qc", "port": "report"}, "as": "tool_count"})
    with pytest.raises(ValidationError, match="WORKFLOW_DESIGN_OUTPUT_ALIAS_NORMALIZED_DUPLICATE"):
        WorkflowDesignDraftCreateRequest.model_validate({"draft": reserved_duplicate_outputs})

    numeric_duplicate_outputs = _draft()
    numeric_duplicate_outputs["outputs"][0]["as"] = "1report"
    numeric_duplicate_outputs["outputs"].append({"from": {"nodeId": "qc", "port": "report"}, "as": "tool_1report"})
    with pytest.raises(ValidationError, match="WORKFLOW_DESIGN_OUTPUT_ALIAS_NORMALIZED_DUPLICATE"):
        WorkflowDesignDraftCreateRequest.model_validate({"draft": numeric_duplicate_outputs})

    safe_reserved_outputs = _draft()
    safe_reserved_outputs["outputs"][0]["as"] = "count"
    safe_reserved_outputs["outputs"].append({"from": {"nodeId": "qc", "port": "report"}, "as": "count_alias"})
    WorkflowDesignDraftCreateRequest.model_validate({"draft": safe_reserved_outputs})

    python_field_aliases = _draft()
    python_field_aliases["outputs"] = [{"from_": {"nodeId": "qc", "port": "report"}, "as_": "qc_report"}]
    python_field_aliases["edges"] = [
        {"from_": {"nodeId": "qc", "port": "report"}, "to": {"nodeId": "qc", "port": "reads"}}
    ]
    with pytest.raises(ValidationError):
        WorkflowDesignDraftCreateRequest.model_validate({"draft": python_field_aliases})

    unknown_audit_key = _draft()
    unknown_audit_key["edges"] = [
        {
            "from": {"nodeId": "qc", "port": "report"},
            "to": {"nodeId": "qc", "port": "reads"},
            "audit": {"source": "manual", "unexpected": "kept"},
        }
    ]
    with pytest.raises(ValidationError, match="WORKFLOW_DESIGN_EDGE_AUDIT_UNKNOWN_KEY"):
        WorkflowDesignDraftCreateRequest.model_validate({"draft": unknown_audit_key})

    with pytest.raises(ValidationError) as plan_exc:
        WorkflowDesignDraftPlanRequest.model_validate({"inputOverrides": [{"role": "input", "path": "/tmp/override"}]})

    assert plan_exc.value.errors()[0]["type"] == "extra_forbidden"


def test_workflow_design_draft_storage_crud_and_fork(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    saved = create_workflow_design_draft(cfg, _draft())

    assert saved["draftId"].startswith("wfd_")
    assert saved["revision"] == 1
    assert saved["draft"]["metadata"]["name"] == "QC workflow"
    assert list_workflow_design_drafts(cfg)[0]["draftId"] == saved["draftId"]

    next_draft = _draft()
    next_draft["metadata"]["name"] = "QC workflow updated"
    updated = update_workflow_design_draft(cfg, saved["draftId"], next_draft, expected_revision=1)

    assert updated["revision"] == 2
    assert updated["draft"]["metadata"]["name"] == "QC workflow updated"
    assert fetch_workflow_design_draft(cfg, saved["draftId"])["revision"] == 2

    forked = fork_workflow_design_draft(cfg, saved["draftId"], name="QC workflow fork")
    assert forked["revision"] == 1
    assert forked["parentDraftId"] == saved["draftId"]
    assert forked["draft"]["metadata"]["name"] == "QC workflow fork"


def test_workflow_design_plan_preview_and_compile_export(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    upsert_ready_tool(cfg, _tool_manifest())
    saved = create_workflow_design_draft(cfg, _draft())

    plan = plan_workflow_design_draft(
        cfg,
        saved["draft"],
        preview_root=tmp_path / "preview",
        draft_id=saved["draftId"],
        revision=saved["revision"],
    )

    assert plan["valid"] is True
    assert plan["validationIssues"] == []
    assert plan["normalizedGraph"]["contractVersion"] == "workflow-design-draft-v1"
    assert plan["normalizedGraph"]["metadata"]["description"] == "Saved workflow design fixture"
    assert plan["normalizedGraph"]["inputs"][0]["metadata"] == {"lane": "L001"}
    assert plan["normalizedGraph"]["nodes"][0]["metadata"] == {"uiGroup": "qc"}
    assert plan["normalizedGraph"]["nodes"][0]["outputs"]["report"]["metadata"] == {"panel": "summary"}
    assert plan["normalizedGraph"]["nodes"][0]["provenance"] == {"source": "builder"}
    assert plan["normalizedGraph"]["resources"]["metadata"] == {"selectionMode": "manual"}
    assert plan["normalizedGraph"]["outputs"][0]["metadata"] == {"audience": "operator"}
    assert plan["normalizedGraph"]["provenance"] == {"createdBy": "test"}
    assert plan["orderedSteps"][0]["id"] == "qc"
    assert plan["requiredResources"] == {}
    assert plan["requiredDatabases"] == {}
    assert plan["resolvedPorts"]["qc"]["inputs"]["reads"].endswith("inputs/reads.fastq")
    assert plan["exposedOutputs"]["qc_report"]["output"] == "report"
    assert plan["runSpec"]["workflowDesign"]["draftId"] == saved["draftId"]
    assert plan["runSpec"]["workflowDesign"]["revision"] == saved["revision"]
    assert "audit" not in plan["runSpec"]["workflow"]["edges"][0] if plan["runSpec"]["workflow"]["edges"] else True
    assert "rule run_tool" in plan["previews"]["snakefile"]
    preview_config = json.loads(plan["previews"]["config"])
    assert preview_config["workflow"]["outputs"]["qc_report"]["output"] == "report"
    assert preview_config["workflow"]["graph"]["metadata"]["description"] == "Saved workflow design fixture"

    export_dir = tmp_path / "export"
    exported = compile_workflow_design_project(
        cfg,
        saved["draft"],
        export_dir=export_dir,
        draft_id=saved["draftId"],
        revision=saved["revision"],
    )

    assert exported["layout"]["snakefile"] == "workflow/Snakefile"
    assert exported["runSpec"]["workflowDesign"]["draftId"] == saved["draftId"]
    assert exported["runSpec"]["workflowDesign"]["revision"] == saved["revision"]
    assert (export_dir / "workflow" / "Snakefile").is_file()
    snakefile = (export_dir / "workflow" / "Snakefile").read_text(encoding="utf-8")
    generated_rules = (export_dir / "workflow" / "rules" / "generated.smk").read_text(encoding="utf-8")
    assert "from snakemake.utils import validate" in snakefile
    assert 'configfile: "run-config.json"' in snakefile
    assert 'configfile: "config/config.yaml"' not in snakefile
    assert 'validate(config, workflow.source_path("schemas/config.schema.yaml"))' in snakefile
    assert 'include: "rules/generated.smk"' in snakefile
    assert 'qc_report=config["outputs"]["qc_report"]' in snakefile
    assert 'report=config["outputs"]["qc_report"]' in generated_rules
    assert "{output.report:q}" in generated_rules
    assert "results/qc-report.txt" not in generated_rules
    assert "../envs/bioconda_qc_1.0.yaml" in generated_rules
    assert (export_dir / "workflow" / "envs" / "bioconda_qc_1.0.yaml").is_file()
    assert (export_dir / "workflow" / "schemas" / "config.schema.yaml").is_file()
    assert (export_dir / "config" / "config.yaml").is_file()
    assert not (export_dir / "config" / "schema" / "config.schema.json").exists()
    assert (export_dir / ".test" / "run-config.json").is_file()
    assert (export_dir / "README.md").read_text(encoding="utf-8").startswith("# QC workflow")


def test_workflow_design_plan_resolves_bound_database_resources(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    database_dir = tmp_path / "custom-db"
    database_dir.mkdir()
    (database_dir / "README.txt").write_text("custom database\n", encoding="utf-8")
    add_reference_database(
        cfg,
        {
            "id": "db_custom",
            "name": "Custom DB",
            "templateId": "custom",
            "version": "2026.05",
            "path": str(database_dir),
        },
    )
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
    upsert_ready_tool(cfg, tool)
    draft = _draft("bioconda::db-qc=1.0")
    draft["resources"]["bindings"] = {"reference_database": {"databaseId": "db_custom"}}
    saved = create_workflow_design_draft(cfg, draft)

    plan = plan_workflow_design_draft(
        cfg,
        saved["draft"],
        preview_root=tmp_path / "preview",
        draft_id=saved["draftId"],
        revision=saved["revision"],
    )

    assert plan["valid"] is True
    assert plan["requiredResources"] == {
        "reference_database": {
            "type": "database",
            "acceptedTemplates": ["custom"],
            "acceptedCapabilities": ["reference_database"],
            "configKey": "reference_db",
        }
    }
    resource = plan["requiredDatabases"]["reference_database"]
    assert resource["databaseId"] == "db_custom"
    assert resource["templateId"] == "custom"
    assert resource["configKey"] == "reference_db"
    assert resource["path"] == str(database_dir)
    assert resource["resolved"] == {"default": str(database_dir)}
    assert "reference_database" in resource["capabilities"]
    assert plan["runSpec"]["resourceBindings"] == {"reference_database": {"databaseId": "db_custom"}}

    preview_config = json.loads(plan["previews"]["config"])
    assert preview_config["databases"] == {"reference_db": str(database_dir)}
    assert preview_config["resourceConfig"] == {"reference_db": str(database_dir)}
    assert preview_config["resources"]["reference_database"]["databaseId"] == "db_custom"
    assert preview_config["workflow"]["graph"]["resources"]["bindings"] == {
        "reference_database": {"databaseId": "db_custom"}
    }


def test_workflow_design_compile_removes_stale_generated_files(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    upsert_ready_tool(cfg, _tool_manifest())
    saved = create_workflow_design_draft(cfg, _draft())
    export_dir = tmp_path / "export"

    compile_workflow_design_project(
        cfg,
        saved["draft"],
        export_dir=export_dir,
        draft_id=saved["draftId"],
        revision=saved["revision"],
    )
    stale_env = export_dir / "workflow" / "envs" / "stale.yaml"
    stale_config = export_dir / "config" / "stale.yaml"
    stale_test_file = export_dir / ".test" / "stale.txt"
    stale_readme = export_dir / "README.md"
    unrelated_note = export_dir / "operator-note.txt"
    stale_env.write_text("stale-env", encoding="utf-8")
    stale_config.write_text("stale-config", encoding="utf-8")
    stale_test_file.write_text("stale-test", encoding="utf-8")
    stale_readme.write_text("stale-readme", encoding="utf-8")
    unrelated_note.write_text("keep", encoding="utf-8")

    compile_workflow_design_project(
        cfg,
        saved["draft"],
        export_dir=export_dir,
        draft_id=saved["draftId"],
        revision=saved["revision"],
    )

    assert not stale_env.exists()
    assert not stale_config.exists()
    assert not stale_test_file.exists()
    assert stale_readme.read_text(encoding="utf-8").startswith("# QC workflow")
    assert unrelated_note.read_text(encoding="utf-8") == "keep"


def test_workflow_design_compile_keeps_generic_output_token_primary(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    tool = _tool_manifest("bioconda::multi=1.0")
    tool["ruleTemplate"]["commandTemplate"] = "printf ok > {output:q}"
    tool["ruleTemplate"]["outputs"] = [
        {"name": "report", "path": "report.txt", "kind": "report", "mimeType": "text/plain"},
        {"name": "sidecar", "path": "sidecar.txt", "kind": "log", "mimeType": "text/plain"},
    ]
    upsert_ready_tool(cfg, tool)
    saved = create_workflow_design_draft(cfg, _draft("bioconda::multi=1.0"))

    compile_workflow_design_project(
        cfg,
        saved["draft"],
        export_dir=tmp_path / "export",
        draft_id=saved["draftId"],
        revision=saved["revision"],
    )

    generated_rules = (tmp_path / "export" / "workflow" / "rules" / "generated.smk").read_text(encoding="utf-8")
    assert 'report=config["outputs"]["qc_report"]' in generated_rules
    assert "sidecar='results/sidecar.txt'" in generated_rules
    assert "printf ok > {output.report:q}" in generated_rules
    assert "printf ok > {output:q}" not in generated_rules


def test_workflow_design_plan_blocks_unready_tools(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    saved = create_workflow_design_draft(cfg, _draft(tool_id="bioconda::missing=1.0"))

    plan = plan_workflow_design_draft(cfg, saved["draft"], preview_root=tmp_path / "preview")

    assert plan["valid"] is False
    assert plan["validationIssues"][0]["code"] == "TOOL_REVISION_NOT_FOUND"
    assert plan["previews"]["snakefile"] == ""
    assert plan["runSpec"] == {}


def test_generated_tool_run_preflight_requires_saved_workflow_design_draft(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    upsert_ready_tool(cfg, _tool_manifest())
    saved = create_workflow_design_draft(cfg, _draft())
    pipeline = get_pipeline(cfg, GENERATED_TOOL_RUN_PIPELINE_ID)
    run_spec = workflow_design_to_generated_run_spec(
        saved["draft"],
        draft_id=saved["draftId"],
        revision=saved["revision"],
    )
    run_spec["inputs"] = [{"role": "input", "uploadId": "upl_reads", "filename": "reads.fastq"}]

    preflight_run_spec(cfg, pipeline, run_spec)

    with pytest.raises(RunPreflightError, match="WORKFLOW_DESIGN_RUN_SPEC_REQUIRED"):
        preflight_run_spec(
            cfg,
            pipeline,
            {
                "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
                "tool": {"id": "bioconda::qc=1.0"},
                "inputs": [{"role": "input", "uploadId": "upl_reads"}],
            },
        )

    tampered = json.loads(json.dumps(run_spec))
    tampered["workflow"]["nodes"][0]["params"]["min_len"] = 10
    with pytest.raises(RunPreflightError, match="WORKFLOW_DESIGN_RUN_SPEC_MISMATCH"):
        preflight_run_spec(cfg, pipeline, tampered)

    extra_input = json.loads(json.dumps(run_spec))
    extra_input["inputs"][0]["path"] = "/tmp/reads.fastq"
    with pytest.raises(RunPreflightError, match="WORKFLOW_DESIGN_RUN_INPUT_UNSUPPORTED_FIELD"):
        preflight_run_spec(cfg, pipeline, extra_input)

    renamed_role = json.loads(json.dumps(run_spec))
    renamed_role["inputs"][0]["role"] = "other"
    with pytest.raises(RunPreflightError, match="WORKFLOW_DESIGN_RUN_INPUT_ROLE_MISMATCH"):
        preflight_run_spec(cfg, pipeline, renamed_role)

    renamed_input = json.loads(json.dumps(run_spec))
    renamed_input["inputs"][0]["filename"] = "renamed.fastq"
    with pytest.raises(RunPreflightError, match="WORKFLOW_DESIGN_RUN_INPUT_FILENAME_MISMATCH"):
        preflight_run_spec(cfg, pipeline, renamed_input)

    missing_upload = json.loads(json.dumps(run_spec))
    missing_upload["inputs"][0]["uploadId"] = ""
    with pytest.raises(RunPreflightError, match="WORKFLOW_DESIGN_RUN_INPUT_UPLOAD_REQUIRED"):
        preflight_run_spec(cfg, pipeline, missing_upload)

    extra_upload = json.loads(json.dumps(run_spec))
    extra_upload["inputs"].append({"role": "extra", "uploadId": "upl_extra", "filename": "extra.fastq"})
    with pytest.raises(RunPreflightError, match="WORKFLOW_DESIGN_RUN_INPUTS_MISMATCH"):
        preflight_run_spec(cfg, pipeline, extra_upload)

    null_pipeline_version = json.loads(json.dumps(run_spec))
    null_pipeline_version["pipelineVersion"] = None
    with pytest.raises(RunPreflightError, match="WORKFLOW_DESIGN_RUN_SPEC_MISMATCH: pipelineVersion"):
        preflight_run_spec(cfg, pipeline, null_pipeline_version)


def test_generated_workflow_planner_rejects_legacy_direct_shapes(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    upsert_ready_tool(cfg, _tool_manifest())
    tool_revision_id = test_tool_revision_id("bioconda::qc=1.0")
    resolved_inputs = [{"role": "input", "path": "inputs/reads.fastq", "filename": "reads.fastq"}]

    with pytest.raises(ValueError, match="WORKFLOW_RUN_SPEC_UNSUPPORTED_FIELD: tool"):
        plan_generated_workflow_steps(
            cfg,
            run_spec={"pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID, "tool": {"id": "bioconda::qc=1.0"}},
            resolved_inputs=resolved_inputs,
            result_dir=tmp_path / "results",
        )

    with pytest.raises(ValueError, match="WORKFLOW_GRAPH_STEPS_UNSUPPORTED"):
        plan_generated_workflow_steps(
            cfg,
            run_spec={
                "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
                "workflow": {"steps": [{"id": "qc", "tool": {"id": "bioconda::qc=1.0"}}]},
            },
            resolved_inputs=resolved_inputs,
            result_dir=tmp_path / "results",
        )

    with pytest.raises(ValueError, match="WORKFLOW_STEP_INPUT_BINDING_UNSUPPORTED"):
        plan_generated_workflow_steps(
            cfg,
            run_spec={
                "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
                "workflow": {
                    "contractVersion": "rule-contract-v1",
                    "nodes": [
                        {
                            "id": "qc",
                            "toolRevisionId": tool_revision_id,
                            "inputs": {"reads": {"fromUpload": 0}},
                        }
                    ],
                    "edges": [],
                },
            },
            resolved_inputs=resolved_inputs,
            result_dir=tmp_path / "results",
        )

    with pytest.raises(ValueError, match="WORKFLOW_RUN_SPEC_UNSUPPORTED_FIELD: tool"):
        plan_generated_workflow_steps(
            cfg,
            run_spec={
                "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
                "tool": {"id": "bioconda::qc=1.0"},
                "workflow": {
                    "contractVersion": "rule-contract-v1",
                    "nodes": [
                        {
                            "id": "qc",
                            "tool": {"id": "bioconda::qc=1.0"},
                            "inputs": {"reads": {"fromInput": "input"}},
                        }
                    ],
                    "edges": [],
                },
            },
            resolved_inputs=resolved_inputs,
            result_dir=tmp_path / "results",
        )

    with pytest.raises(ValueError, match="WORKFLOW_GRAPH_NODE_UNSUPPORTED_FIELD: qc.toolId"):
        plan_generated_workflow_steps(
            cfg,
            run_spec={
                "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
                "workflow": {
                    "contractVersion": "rule-contract-v1",
                    "nodes": [
                        {
                            "id": "qc",
                            "toolId": "bioconda::qc=1.0",
                            "inputs": {"reads": {"fromInput": "input"}},
                        }
                    ],
                    "edges": [],
                },
            },
            resolved_inputs=resolved_inputs,
            result_dir=tmp_path / "results",
        )

    with pytest.raises(ValueError, match="WORKFLOW_GRAPH_NODE_UNSUPPORTED_FIELD: qc.tool"):
        plan_generated_workflow_steps(
            cfg,
            run_spec={
                "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
                "workflow": {
                    "contractVersion": "rule-contract-v1",
                    "nodes": [
                        {
                            "id": "qc",
                            "tool": {"id": "bioconda::qc=1.0"},
                            "toolId": "bioconda::legacy=1.0",
                            "inputs": {"reads": {"fromInput": "input"}},
                        }
                    ],
                    "edges": [],
                },
            },
            resolved_inputs=resolved_inputs,
            result_dir=tmp_path / "results",
        )
