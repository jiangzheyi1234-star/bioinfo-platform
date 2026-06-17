from __future__ import annotations

from pathlib import Path

from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from apps.remote_runner.generated_workflow import GENERATED_TOOL_RUN_PIPELINE_ID
from apps.remote_runner.pipeline import get_pipeline
from apps.remote_runner.preflight import RunPreflightError, preflight_run_spec
from apps.remote_runner.storage import upsert_tool as _upsert_tool
from apps.remote_runner.tool_revisions import publish_tool_revision
from apps.remote_runner.workflow_revision_storage import create_or_fetch_workflow_revision
from core.contracts.workflow_design import workflow_design_to_generated_run_spec
from apps.remote_runner.workflow_design_storage import create_workflow_design_draft

READY_CONTRACT_STATUS = {"dryRun": {"status": "passed"}, "smokeRun": {"status": "passed"}, "outputValidation": {"status": "passed"}}
_TOOL_REVISIONS: dict[str, str] = {}


def test_preflight_uses_shared_generated_workflow_planner_boundary() -> None:
    source = (Path.cwd() / "apps" / "remote_runner" / "preflight.py").read_text(encoding="utf-8")

    assert "generated_workflow_plan" in source
    assert "from .generated_workflow import (" not in source


def _cfg(tmp_path: Path) -> RemoteRunnerConfig:
    return RemoteRunnerConfig(
        token="run-preflight-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(Path.cwd() / "apps" / "remote_runner"),
    )


def upsert_tool(cfg: RemoteRunnerConfig, tool: dict) -> dict:
    rule_template = tool.get("ruleTemplate")
    if isinstance(rule_template, dict):
        rule_template.setdefault("params", {})
        rule_template.setdefault("resources", {"threads": {"default": 1}, "mem_mb": {"default": 128}})
        rule_template.setdefault("log", "logs/tool.log")
        rule_template.setdefault("smokeTest", {"inputs": {str(item.get("name") or f"input_{index + 1}"): {"filename": f"input_{index + 1}.txt", "content": "smoke\n"} for index, item in enumerate(rule_template.get("inputs", [])) if isinstance(item, dict)}})
        rule_template.setdefault(
            "environment",
            {"conda": {"channels": ["conda-forge", "bioconda"], "dependencies": [tool["packageSpec"]]}},
        )
    tool.setdefault("contractStatus", {key: dict(value) for key, value in READY_CONTRACT_STATUS.items()})
    tool.setdefault("validationSummary", _test_validation_summary(tool))
    published = publish_tool_revision(cfg, tool)
    published.setdefault("validationSummary", tool["validationSummary"])
    published.setdefault("validationResultId", tool["validationSummary"]["latestResultId"])
    published.setdefault("evidenceId", tool["validationSummary"]["evidenceId"])
    published["status"] = "published"
    saved = _upsert_tool(cfg, published)
    _TOOL_REVISIONS[str(saved.get("id") or "")] = str(saved.get("toolRevisionId") or "")
    return saved


def _test_validation_summary(tool: dict) -> dict[str, str]:
    tool_id = str(tool.get("id") or "tool").replace("::", "_").replace("/", "_").replace("=", "_")
    return {
        "latestResultId": f"toolval_test_{tool_id}",
        "latestStatus": "passed",
        "evidenceId": f"evid_test_{tool_id}",
        "updatedAt": "2026-01-01T00:00:00Z",
    }


def _register_tool(cfg: RemoteRunnerConfig, tool_id: str, output_name: str = "out") -> None:
    upsert_tool(
        cfg,
        {
            "id": tool_id,
            "name": tool_id.rsplit("::", 1)[-1],
            "source": "conda-forge",
            "sourceLabel": "conda-forge",
            "version": "9.5",
            "packageSpec": f"conda-forge::{tool_id.rsplit('::', 1)[-1]}=9.5",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": f"cp {{input.primary:q}} {{output.{output_name}:q}}",
                "inputs": [{"name": "primary", "type": "file", "required": True}],
                "outputs": [{"name": output_name, "path": f"{output_name}.txt", "kind": "log", "mimeType": "text/plain"}],
            },
            "status": "declared",
            "message": "Tool declared.",
        },
    )


def _draft_node(tool_id: str, *, node_id: str | None = None, inputs: dict | None = None, params: dict | None = None) -> dict:
    return {
        "id": node_id or tool_id.rsplit("::", 1)[-1],
        "toolRevisionId": _TOOL_REVISIONS.get(tool_id, tool_id),
        "inputs": inputs or {},
        "params": params or {},
        "runtime": {},
        "resources": {},
        "outputs": {},
        "provenance": {"source": "test"},
    }


def _draft_run_spec(
    cfg: RemoteRunnerConfig,
    *,
    nodes: list[dict],
    edges: list[dict] | None = None,
    outputs: list[dict] | None = None,
    input_roles: tuple[str, ...] = ("reads",),
) -> dict:
    draft = {
        "contractVersion": "workflow-design-draft-v1",
        "engine": "snakemake",
        "metadata": {"name": "preflight fixture", "description": "", "projectId": "proj_preflight", "tags": []},
        "inputs": [
            {
                "id": role,
                "role": role,
                "path": f"inputs/{role}.txt",
                "filename": f"{role}.txt",
                "mimeType": "text/plain",
            }
            for role in input_roles
        ],
        "nodes": _nodes_without_node_to_node_inputs(nodes),
        "edges": edges or [],
        "resources": {"bindings": {}},
        "outputs": outputs or [],
        "provenance": {"createdBy": "test"},
    }
    saved = create_workflow_design_draft(cfg, draft)
    run_spec = workflow_design_to_generated_run_spec(
        saved["draft"],
        draft_id=saved["draftId"],
        revision=saved["revision"],
    )
    workflow_revision = create_or_fetch_workflow_revision(
        cfg,
        draft_id=saved["draftId"],
        draft_revision=saved["revision"],
        manifest={"files": []},
        graph_snapshot={"runSpec": run_spec},
        runtime_lock={"provider": "test"},
        compiler={"name": "test"},
    )
    run_spec["workflowRevisionId"] = workflow_revision["workflowRevisionId"]
    run_spec["inputs"] = [
        {"role": role, "uploadId": f"upl_{role}", "filename": f"{role}.txt"}
        for role in input_roles
    ]
    return run_spec


def _nodes_without_node_to_node_inputs(nodes: list[dict]) -> list[dict]:
    for node in nodes:
        node_id = str(node.get("id") or "")
        for input_name, binding in dict(node.get("inputs") or {}).items():
            if isinstance(binding, dict) and binding.get("fromStep") and binding.get("output"):
                raise ValueError(f"WORKFLOW_DESIGN_EDGE_REQUIRED: {node_id}.{input_name}")
    return nodes


def test_preflight_rejects_unknown_generated_step_output(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    pipeline = get_pipeline(cfg, GENERATED_TOOL_RUN_PIPELINE_ID)
    _register_tool(cfg, "conda-forge::source", output_name="seed")
    _register_tool(cfg, "conda-forge::copy", output_name="copied")

    try:
        preflight_run_spec(
            cfg,
            pipeline,
            _draft_run_spec(
                cfg,
                nodes=[
                    _draft_node("conda-forge::source", node_id="source", inputs={"primary": {"fromInput": "reads"}}),
                    _draft_node("conda-forge::copy", node_id="copy"),
                ],
                edges=[{"from": {"nodeId": "source", "port": "missing"}, "to": {"nodeId": "copy", "port": "primary"}}],
            ),
        )
    except RunPreflightError as exc:
        assert str(exc) == "WORKFLOW_STEP_INPUT_OUTPUT_UNKNOWN: source.missing"
    else:
        raise AssertionError("unknown generated step output should be rejected before run creation")


def test_preflight_accepts_unordered_generated_step_references(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    pipeline = get_pipeline(cfg, GENERATED_TOOL_RUN_PIPELINE_ID)
    _register_tool(cfg, "conda-forge::source", output_name="seed")
    _register_tool(cfg, "conda-forge::copy", output_name="copied")

    preflight_run_spec(
        cfg,
        pipeline,
        _draft_run_spec(
            cfg,
            nodes=[
                _draft_node("conda-forge::copy", node_id="copy"),
                _draft_node("conda-forge::source", node_id="source", inputs={"primary": {"fromInput": "reads"}}),
            ],
            edges=[{"from": {"nodeId": "source", "port": "seed"}, "to": {"nodeId": "copy", "port": "primary"}}],
            outputs=[{"from": {"nodeId": "copy", "port": "copied"}, "as": "copied"}],
        ),
    )


def test_preflight_accepts_generated_graph_contract(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    pipeline = get_pipeline(cfg, GENERATED_TOOL_RUN_PIPELINE_ID)
    _register_tool(cfg, "conda-forge::source", output_name="seed")
    _register_tool(cfg, "conda-forge::copy", output_name="copied")

    preflight_run_spec(
        cfg,
        pipeline,
        _draft_run_spec(
            cfg,
            nodes=[
                _draft_node("conda-forge::copy", node_id="copy"),
                _draft_node("conda-forge::source", node_id="source", inputs={"primary": {"fromInput": "reads"}}),
            ],
            edges=[{"from": {"nodeId": "source", "port": "seed"}, "to": {"nodeId": "copy", "port": "primary"}}],
            outputs=[{"from": {"nodeId": "copy", "port": "copied"}, "as": "copied"}],
        ),
    )


def test_preflight_rejects_generated_graph_edge_to_unknown_input_port(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    pipeline = get_pipeline(cfg, GENERATED_TOOL_RUN_PIPELINE_ID)
    _register_tool(cfg, "conda-forge::source", output_name="seed")
    upsert_tool(
        cfg,
        {
            "id": "conda-forge::sink",
            "name": "sink",
            "source": "conda-forge",
            "sourceLabel": "conda-forge",
            "version": "9.5",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "printf ok > {output.copied:q}",
                "inputs": [{"name": "primary", "type": "file", "required": False}],
                "outputs": [{"name": "copied", "path": "copied.txt", "kind": "log", "mimeType": "text/plain"}],
            },
            "status": "declared",
            "message": "Tool declared.",
        },
    )

    try:
        preflight_run_spec(
            cfg,
            pipeline,
            _draft_run_spec(
                cfg,
                nodes=[
                    _draft_node("conda-forge::source", node_id="source", inputs={"primary": {"fromInput": "reads"}}),
                    _draft_node("conda-forge::sink", node_id="sink"),
                ],
                edges=[{"from": {"nodeId": "source", "port": "seed"}, "to": {"nodeId": "sink", "port": "ghost"}}],
                outputs=[{"from": {"nodeId": "sink", "port": "copied"}, "as": "copied"}],
            ),
        )
    except RunPreflightError as exc:
        assert str(exc) == "WORKFLOW_STEP_INPUT_PORT_UNKNOWN: sink.ghost"
    else:
        raise AssertionError("generated graph edges should target declared RuleSpec input ports")


def test_preflight_rejects_generated_graph_without_contract_version(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    pipeline = get_pipeline(cfg, GENERATED_TOOL_RUN_PIPELINE_ID)
    _register_tool(cfg, "conda-forge::source", output_name="seed")
    _register_tool(cfg, "conda-forge::copy", output_name="copied")

    try:
        preflight_run_spec(
            cfg,
            pipeline,
            {
                "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
                "inputs": [{"role": "reads"}],
                "workflow": {
                    "nodes": [
                        {"id": "source", "toolId": "conda-forge::source", "inputs": {"primary": {"fromInput": "reads"}}},
                        {"id": "copy", "toolId": "conda-forge::copy"},
                    ],
                    "edges": [{"from": {"nodeId": "source", "port": "seed"}, "to": {"nodeId": "copy", "port": "primary"}}],
                    "outputs": [{"from": {"nodeId": "copy", "port": "copied"}, "as": "copied"}],
                },
            },
        )
    except RunPreflightError as exc:
        assert str(exc) == "WORKFLOW_DESIGN_RUN_SPEC_REQUIRED"
    else:
        raise AssertionError("direct generated graph payloads should require a saved WorkflowDesignDraft")


def test_preflight_accepts_generated_step_params(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    pipeline = get_pipeline(cfg, GENERATED_TOOL_RUN_PIPELINE_ID)
    upsert_tool(
        cfg,
        {
            "id": "conda-forge::filter",
            "name": "filter",
            "source": "conda-forge",
            "sourceLabel": "conda-forge",
            "version": "9.5",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "head -n {params.limit} {input.primary:q} > {output.filtered:q}",
                "inputs": [{"name": "primary", "type": "file", "required": True}],
                "outputs": [{"name": "filtered", "path": "filtered.txt", "kind": "log", "mimeType": "text/plain"}],
                "params": {"limit": {"type": "integer", "default": 3}},
            },
            "status": "declared",
            "message": "Tool declared.",
        },
    )

    preflight_run_spec(
        cfg,
        pipeline,
        _draft_run_spec(
            cfg,
            nodes=[
                _draft_node(
                    "conda-forge::filter",
                    node_id="filter",
                    inputs={"primary": {"fromInput": "reads"}},
                    params={"limit": 5},
                )
            ],
        ),
    )


def test_preflight_rejects_invalid_generated_step_params(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    pipeline = get_pipeline(cfg, GENERATED_TOOL_RUN_PIPELINE_ID)
    _register_tool(cfg, "conda-forge::source", output_name="seed")

    try:
        preflight_run_spec(
            cfg,
            pipeline,
            {
                "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
                "workflow": {
                    "steps": [
                        {
                            "id": "source",
                            "tool": {"id": "conda-forge::source"},
                            "params": ["not", "a", "dict"],
                        }
                    ]
                },
            },
        )
    except RunPreflightError as exc:
        assert str(exc) == "WORKFLOW_DESIGN_RUN_SPEC_REQUIRED"
    else:
        raise AssertionError("direct generated step params should require a saved WorkflowDesignDraft")


def test_preflight_rejects_incompatible_generated_step_ports(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    pipeline = get_pipeline(cfg, GENERATED_TOOL_RUN_PIPELINE_ID)
    upsert_tool(
        cfg,
        {
            "id": "conda-forge::source",
            "name": "source",
            "source": "conda-forge",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "cp {input.primary:q} {output.reads:q}",
                "inputs": [{"name": "primary", "type": "file", "required": True}],
                "outputs": [
                    {
                        "name": "reads",
                        "path": "reads.bam",
                        "kind": "alignment",
                        "mimeType": "application/x-bam",
                    }
                ],
            },
        },
    )
    upsert_tool(
        cfg,
        {
            "id": "conda-forge::consumer",
            "name": "consumer",
            "source": "conda-forge",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "cp {input.reads:q} {output.report:q}",
                "inputs": [{"name": "reads", "type": "file", "kind": "sequence", "mimeType": "application/gzip"}],
                "outputs": [{"name": "report", "path": "report.txt", "kind": "log", "mimeType": "text/plain"}],
            },
        },
    )

    try:
        preflight_run_spec(
            cfg,
            pipeline,
            _draft_run_spec(
                cfg,
                input_roles=("input",),
                nodes=[
                    _draft_node("conda-forge::source", node_id="source", inputs={"primary": {"fromInput": "input"}}),
                    _draft_node("conda-forge::consumer", node_id="consumer"),
                ],
                edges=[{"from": {"nodeId": "source", "port": "reads"}, "to": {"nodeId": "consumer", "port": "reads"}}],
            ),
        )
    except RunPreflightError as exc:
        assert str(exc) == "WORKFLOW_STEP_INPUT_OUTPUT_INCOMPATIBLE: source.reads -> reads"
    else:
        raise AssertionError("incompatible generated workflow ports should be rejected")


def test_preflight_rejects_generated_step_cycles(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    pipeline = get_pipeline(cfg, GENERATED_TOOL_RUN_PIPELINE_ID)
    _register_tool(cfg, "conda-forge::left", output_name="left")
    _register_tool(cfg, "conda-forge::right", output_name="right")

    try:
        preflight_run_spec(
            cfg,
            pipeline,
            _draft_run_spec(
                cfg,
                nodes=[
                    _draft_node("conda-forge::left", node_id="left"),
                    _draft_node("conda-forge::right", node_id="right"),
                ],
                edges=[
                    {"from": {"nodeId": "right", "port": "right"}, "to": {"nodeId": "left", "port": "primary"}},
                    {"from": {"nodeId": "left", "port": "left"}, "to": {"nodeId": "right", "port": "primary"}},
                ],
            ),
        )
    except RunPreflightError as exc:
        assert str(exc) == "WORKFLOW_STEP_CYCLE: left, right"
    else:
        raise AssertionError("generated workflow cycles should be rejected before run creation")


def test_preflight_normalizes_generated_step_refs_and_exposed_outputs(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    pipeline = get_pipeline(cfg, GENERATED_TOOL_RUN_PIPELINE_ID)
    _register_tool(cfg, "conda-forge::source", output_name="seed")
    _register_tool(cfg, "conda-forge::copy", output_name="copied")

    preflight_run_spec(
        cfg,
        pipeline,
        _draft_run_spec(
            cfg,
            nodes=[
                _draft_node("conda-forge::copy", node_id="copy step"),
                _draft_node("conda-forge::source", node_id="source step", inputs={"primary": {"fromInput": "reads"}}),
            ],
            edges=[{"from": {"nodeId": "source step", "port": "seed"}, "to": {"nodeId": "copy step", "port": "primary"}}],
            outputs=[{"from": {"nodeId": "copy step", "port": "copied"}, "as": "copied"}],
        ),
    )


def test_preflight_rejects_invalid_generated_upload_binding(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    pipeline = get_pipeline(cfg, GENERATED_TOOL_RUN_PIPELINE_ID)
    _register_tool(cfg, "conda-forge::source", output_name="seed")

    try:
        preflight_run_spec(
            cfg,
            pipeline,
            {
                "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
                "inputs": [{"role": "reads"}],
                "workflow": {
                    "steps": [
                        {
                            "id": "source",
                            "tool": {"id": "conda-forge::source"},
                            "inputs": {"primary": {"fromUpload": "not-an-int"}},
                        }
                    ]
                },
            },
        )
    except RunPreflightError as exc:
        assert str(exc) == "WORKFLOW_DESIGN_RUN_SPEC_REQUIRED"
    else:
        raise AssertionError("direct generated fromUpload binding should require a saved WorkflowDesignDraft")


def test_preflight_rejects_invalid_generated_output_alias(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    pipeline = get_pipeline(cfg, GENERATED_TOOL_RUN_PIPELINE_ID)
    _register_tool(cfg, "conda-forge::source", output_name="seed")

    try:
        preflight_run_spec(
            cfg,
            pipeline,
            {
                "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
                "workflow": {
                    "steps": [{"id": "source", "tool": {"id": "conda-forge::source"}}],
                    "outputs": {"": {"step": "source", "output": "seed", "as": ""}},
                },
            },
        )
    except RunPreflightError as exc:
        assert str(exc) == "WORKFLOW_DESIGN_RUN_SPEC_REQUIRED"
    else:
        raise AssertionError("direct generated output alias should require a saved WorkflowDesignDraft")


def test_preflight_rejects_exposed_temp_generated_output(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    pipeline = get_pipeline(cfg, GENERATED_TOOL_RUN_PIPELINE_ID)
    upsert_tool(
        cfg,
        {
            "id": "conda-forge::temp-output",
            "name": "temp-output",
            "source": "conda-forge",
            "sourceLabel": "conda-forge",
            "version": "9.5",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "cp {input.primary:q} {output.cache:q}",
                "inputs": [{"name": "primary", "type": "file", "required": True}],
                "outputs": [{"name": "cache", "path": "cache.txt", "kind": "log", "mimeType": "text/plain", "temp": True}],
            },
            "status": "declared",
            "message": "Tool declared.",
        },
    )

    try:
        preflight_run_spec(
            cfg,
            pipeline,
            _draft_run_spec(
                cfg,
                nodes=[
                    _draft_node("conda-forge::temp-output", node_id="source", inputs={"primary": {"fromInput": "reads"}})
                ],
                outputs=[{"from": {"nodeId": "source", "port": "cache"}, "as": "cache"}],
            ),
        )
    except RunPreflightError as exc:
        assert str(exc) == "WORKFLOW_OUTPUT_TEMP_EXPOSED: source.cache"
    else:
        raise AssertionError("temp generated output should not be exposable as a final artifact")


def test_preflight_rejects_default_exposed_temp_generated_output(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    pipeline = get_pipeline(cfg, GENERATED_TOOL_RUN_PIPELINE_ID)
    upsert_tool(
        cfg,
        {
            "id": "conda-forge::temp-output",
            "name": "temp-output",
            "source": "conda-forge",
            "sourceLabel": "conda-forge",
            "version": "9.5",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "cp {input.primary:q} {output.cache:q}",
                "inputs": [{"name": "primary", "type": "file", "required": True}],
                "outputs": [{"name": "cache", "path": "cache.txt", "kind": "log", "mimeType": "text/plain", "temp": True}],
            },
            "status": "declared",
            "message": "Tool declared.",
        },
    )

    try:
        preflight_run_spec(
            cfg,
            pipeline,
            _draft_run_spec(
                cfg,
                nodes=[
                    _draft_node("conda-forge::temp-output", node_id="source", inputs={"primary": {"fromInput": "reads"}})
                ],
            ),
        )
    except RunPreflightError as exc:
        assert str(exc) == "WORKFLOW_OUTPUT_TEMP_EXPOSED: source.cache"
    else:
        raise AssertionError("default exposed temp generated output should be rejected before run creation")


def test_preflight_rejects_missing_required_generated_step_input(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    pipeline = get_pipeline(cfg, GENERATED_TOOL_RUN_PIPELINE_ID)
    _register_tool(cfg, "conda-forge::source", output_name="seed")
    upsert_tool(
        cfg,
        {
            "id": "conda-forge::merge",
            "name": "merge",
            "source": "conda-forge",
            "sourceLabel": "conda-forge",
            "version": "9.5",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "cat {input.left:q} {input.right:q} > {output.merged:q}",
                "inputs": [{"name": "left", "required": True}, {"name": "right", "required": True}],
                "outputs": [{"name": "merged", "path": "merged.txt", "kind": "log", "mimeType": "text/plain"}],
            },
            "status": "declared",
            "message": "Tool declared.",
        },
    )

    try:
        preflight_run_spec(
            cfg,
            pipeline,
            _draft_run_spec(
                cfg,
                nodes=[
                    _draft_node("conda-forge::source", node_id="source", inputs={"primary": {"fromInput": "reads"}}),
                    _draft_node("conda-forge::merge", node_id="merge"),
                ],
                edges=[{"from": {"nodeId": "source", "port": "seed"}, "to": {"nodeId": "merge", "port": "left"}}],
            ),
        )
    except RunPreflightError as exc:
        assert str(exc) == "TOOL_INPUT_REQUIRED: right"
    else:
        raise AssertionError("missing generated step input should be rejected before run creation")
