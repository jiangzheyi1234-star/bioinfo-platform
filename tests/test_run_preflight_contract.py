from __future__ import annotations

from pathlib import Path

from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from apps.remote_runner.generated_workflow import GENERATED_TOOL_RUN_PIPELINE_ID
from apps.remote_runner.pipeline import get_pipeline
from apps.remote_runner.preflight import RunPreflightError, preflight_run_spec
from apps.remote_runner.storage import upsert_tool


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


def _register_tool(cfg: RemoteRunnerConfig, tool_id: str, output_name: str = "out") -> None:
    upsert_tool(
        cfg,
        {
            "id": tool_id,
            "name": tool_id.rsplit("::", 1)[-1],
            "source": "conda-forge",
            "sourceLabel": "conda-forge",
            "version": "9.5",
            "packageSpec": "conda-forge::coreutils=9.5",
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


def test_preflight_rejects_legacy_generated_database_bindings(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    pipeline = get_pipeline(cfg, GENERATED_TOOL_RUN_PIPELINE_ID)

    try:
        preflight_run_spec(
            cfg,
            pipeline,
            {
                "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
                "tool": {"id": "conda-forge::missing"},
                "databases": [{"id": "db_demo", "role": "taxonomy"}],
            },
        )
    except RunPreflightError as exc:
        assert str(exc) == "RESOURCE_BINDINGS_REQUIRED"
    else:
        raise AssertionError("legacy generated database bindings should be rejected before run creation")


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
            {
                "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
                "workflow": {
                    "steps": [
                        {"id": "source", "tool": {"id": "conda-forge::source"}},
                        {
                            "id": "copy",
                            "tool": {"id": "conda-forge::copy"},
                            "inputs": {"primary": {"fromStep": "source", "output": "missing"}},
                        },
                    ]
                },
            },
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
        {
            "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
            "workflow": {
                "steps": [
                    {
                        "id": "copy",
                        "tool": {"id": "conda-forge::copy"},
                        "inputs": {"primary": {"fromStep": "source", "output": "seed"}},
                    },
                    {"id": "source", "tool": {"id": "conda-forge::source"}},
                ],
                "outputs": {"copied": {"step": "copy", "output": "copied"}},
            },
        },
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
        {
            "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
            "inputs": [{"role": "reads"}],
            "workflow": {
                "contractVersion": "rule-contract-v1",
                "nodes": [
                    {
                        "id": "copy",
                        "toolId": "conda-forge::copy",
                    },
                    {
                        "id": "source",
                        "toolId": "conda-forge::source",
                        "inputs": {"primary": {"fromInput": "reads"}},
                    },
                ],
                "edges": [
                    {
                        "from": {"nodeId": "source", "port": "seed"},
                        "to": {"nodeId": "copy", "port": "primary"},
                    }
                ],
                "outputs": [{"from": {"nodeId": "copy", "port": "copied"}, "as": "copied"}],
            },
        },
    )


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
        assert str(exc) == "WORKFLOW_GRAPH_CONTRACT_VERSION_REQUIRED"
    else:
        raise AssertionError("generated graph payloads should declare their rule contract version")


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
        {
            "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
            "inputs": [{"role": "reads"}],
            "workflow": {
                "steps": [
                    {
                        "id": "filter",
                        "tool": {"id": "conda-forge::filter"},
                        "inputs": {"primary": {"fromInput": "reads"}},
                        "params": {"limit": 5},
                    }
                ]
            },
        },
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
        assert str(exc) == "WORKFLOW_STEP_PARAMS_INVALID"
    else:
        raise AssertionError("invalid generated step params should be rejected before run creation")


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
            {
                "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
                "inputs": [{"role": "input"}],
                "workflow": {
                    "steps": [
                        {"id": "source", "tool": {"id": "conda-forge::source"}, "inputs": {"primary": {"fromInput": "input"}}},
                        {
                            "id": "consumer",
                            "tool": {"id": "conda-forge::consumer"},
                            "inputs": {"reads": {"fromStep": "source", "output": "reads"}},
                        },
                    ]
                },
            },
        )
    except RunPreflightError as exc:
        assert str(exc) == "WORKFLOW_STEP_INPUT_OUTPUT_INCOMPATIBLE: source.reads -> reads"
    else:
        raise AssertionError("incompatible generated workflow ports should be rejected")


def test_preflight_accepts_capability_compatible_generated_step_ports(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    pipeline = get_pipeline(cfg, GENERATED_TOOL_RUN_PIPELINE_ID)
    capability_output = {
        "id": "emit_fastq",
        "outputs": [{"name": "reads", "data": "EDAM:data_2044", "format": "EDAM:format_1930"}],
    }
    capability_input = {
        "id": "consume_fastq",
        "inputs": [{"name": "reads", "data": "EDAM:data_2044", "format": "EDAM:format_1930"}],
    }
    upsert_tool(
        cfg,
        {
            "id": "conda-forge::source",
            "name": "source",
            "source": "conda-forge",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatformSupported": True,
            "capabilities": [capability_output],
            "ruleTemplate": {
                "commandTemplate": "cp {input.primary:q} {output.reads:q}",
                "inputs": [{"name": "primary", "type": "file", "required": True}],
                "outputs": [{"name": "reads", "path": "reads.fastq.gz", "kind": "sequence", "mimeType": "application/gzip"}],
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
            "capabilities": [capability_input],
            "ruleTemplate": {
                "commandTemplate": "cp {input.reads:q} {output.report:q}",
                "inputs": [{"name": "reads", "type": "file"}],
                "outputs": [{"name": "report", "path": "report.txt", "kind": "log", "mimeType": "text/plain"}],
            },
        },
    )

    preflight_run_spec(
        cfg,
        pipeline,
        {
            "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
            "inputs": [{"role": "input"}],
            "workflow": {
                "steps": [
                    {"id": "source", "tool": {"id": "conda-forge::source"}, "inputs": {"primary": {"fromInput": "input"}}},
                    {
                        "id": "consumer",
                        "tool": {"id": "conda-forge::consumer"},
                        "inputs": {"reads": {"fromStep": "source", "output": "reads"}},
                    },
                ]
            },
        },
    )


def test_preflight_uses_primary_capability_slots_for_generic_rule_ports(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    pipeline = get_pipeline(cfg, GENERATED_TOOL_RUN_PIPELINE_ID)
    capability_output = {
        "id": "emit_fastq",
        "outputs": [{"name": "clean_reads", "data": "EDAM:data_2044", "format": "EDAM:format_1930", "primary": True}],
    }
    capability_input = {
        "id": "consume_fastq",
        "inputs": [{"name": "reads", "data": "EDAM:data_2044", "format": "EDAM:format_1930", "primary": True}],
    }
    upsert_tool(
        cfg,
        {
            "id": "conda-forge::source",
            "name": "source",
            "source": "conda-forge",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatformSupported": True,
            "capabilities": [capability_output],
            "ruleTemplate": {
                "commandTemplate": "cp {input.primary:q} {output.tool_output:q}",
                "inputs": [{"name": "primary", "type": "file", "required": True}],
                "outputs": [{"name": "tool_output", "path": "reads.fastq.gz", "kind": "sequence", "mimeType": "application/gzip"}],
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
            "capabilities": [capability_input],
            "ruleTemplate": {
                "commandTemplate": "cp {input.primary:q} {output.report:q}",
                "inputs": [{"name": "primary", "type": "file"}],
                "outputs": [{"name": "report", "path": "report.txt", "kind": "log", "mimeType": "text/plain"}],
            },
        },
    )

    preflight_run_spec(
        cfg,
        pipeline,
        {
            "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
            "inputs": [{"role": "input"}],
            "workflow": {
                "steps": [
                    {"id": "source", "tool": {"id": "conda-forge::source"}, "inputs": {"primary": {"fromInput": "input"}}},
                    {
                        "id": "consumer",
                        "tool": {"id": "conda-forge::consumer"},
                        "inputs": {"primary": {"fromStep": "source", "output": "tool_output"}},
                    },
                ]
            },
        },
    )


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
            {
                "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
                "workflow": {
                    "steps": [
                        {
                            "id": "left",
                            "tool": {"id": "conda-forge::left"},
                            "inputs": {"primary": {"fromStep": "right", "output": "right"}},
                        },
                        {
                            "id": "right",
                            "tool": {"id": "conda-forge::right"},
                            "inputs": {"primary": {"fromStep": "left", "output": "left"}},
                        },
                    ]
                },
            },
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
        {
            "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
            "inputs": [{"role": "reads"}],
            "workflow": {
                "steps": [
                    {
                        "id": "copy step",
                        "tool": {"id": "conda-forge::copy"},
                        "inputs": {"primary": {"fromStep": "source step", "output": "seed"}},
                    },
                    {
                        "id": "source step",
                        "tool": {"id": "conda-forge::source"},
                        "inputs": {"primary": {"fromInput": "reads"}},
                    },
                ],
                "outputs": {"copied": {"step": "copy step", "output": "copied"}},
            },
        },
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
        assert str(exc) == "WORKFLOW_STEP_INPUT_UPLOAD_UNKNOWN: not-an-int"
    else:
        raise AssertionError("invalid generated fromUpload binding should be rejected before run creation")


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
        assert str(exc) == "WORKFLOW_OUTPUT_BINDING_INVALID"
    else:
        raise AssertionError("invalid generated output alias should be rejected before run creation")


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
            {
                "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
                "workflow": {
                    "steps": [{"id": "source", "tool": {"id": "conda-forge::temp-output"}}],
                    "outputs": {"cache": {"step": "source", "output": "cache"}},
                },
            },
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
            {
                "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
                "workflow": {
                    "steps": [{"id": "source", "tool": {"id": "conda-forge::temp-output"}}],
                },
            },
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
            {
                "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
                "workflow": {
                    "steps": [
                        {"id": "source", "tool": {"id": "conda-forge::source"}},
                        {
                            "id": "merge",
                            "tool": {"id": "conda-forge::merge"},
                            "inputs": {"left": {"fromStep": "source", "output": "seed"}},
                        },
                    ]
                },
            },
        )
    except RunPreflightError as exc:
        assert str(exc) == "TOOL_INPUT_REQUIRED: right"
    else:
        raise AssertionError("missing generated step input should be rejected before run creation")
