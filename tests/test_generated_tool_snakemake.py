from __future__ import annotations

import json
from pathlib import Path

from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from apps.remote_runner.executor import run_snakemake_execution
from apps.remote_runner.generated_workflow import GENERATED_TOOL_RUN_PIPELINE_ID
from apps.remote_runner.pipeline import list_pipelines
from apps.remote_runner.storage import persist_upload
from apps.remote_runner.tools import ToolRegistryError, add_registered_tool
from tests.generated_workflow_test_helpers import (
    generated_workflow_graph,
    generated_workflow_node,
    generated_workflow_runner_config as _cfg,
    prepare_unchecked_generated_tool_workflow as prepare_generated_tool_workflow,
    upsert_ready_tool as upsert_tool,
    workflow_design_run_spec_from_graph,
)


def test_generated_tool_pipeline_is_listed() -> None:
    cfg = RemoteRunnerConfig(release_dir=str(Path.cwd() / "apps" / "remote_runner"))

    pipeline_ids = {item.pipeline_id for item in list_pipelines(cfg)}

    assert GENERATED_TOOL_RUN_PIPELINE_ID in pipeline_ids


def test_generated_tool_run_writes_snakefile_and_per_rule_conda_env(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    upsert_tool(
        cfg,
        {
            "id": "conda-forge::coreutils",
            "name": "coreutils",
            "source": "conda-forge",
            "sourceLabel": "conda-forge",
            "version": "9.5",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "testCommand": "wc --version",
            "ruleTemplate": {
                "commandTemplate": "wc -c {input.primary:q} > {output.count:q}",
                "inputs": [{"name": "primary", "type": "file", "required": True}],
                "outputs": [{"name": "count", "path": "wc-count.txt", "kind": "log", "mimeType": "text/plain"}],
            },
            "status": "declared",
            "message": "Tool declared.",
        },
    )
    upload = persist_upload(
        cfg,
        filename="reads.txt",
        content_base64="QUJDREVGCg==",
        mime_type="text/plain",
    )
    calls: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(cmd, **_kwargs):
        calls.append(cmd)
        return Result()

    monkeypatch.setattr("apps.remote_runner.executor.subprocess.run", fake_run)
    monkeypatch.setattr("apps.remote_runner.executor._collect_artifacts", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("apps.remote_runner.executor.update_run_state", lambda *args, **kwargs: None)
    monkeypatch.setattr("apps.remote_runner.executor.append_log_lines", lambda *args, **kwargs: None)

    run_snakemake_execution(
        cfg,
        run_id="run_generated_tool",
        request_id="req_generated_tool",
        run_spec=workflow_design_run_spec_from_graph(
            cfg,
            generated_workflow_graph(
                [
                    generated_workflow_node(
                        "conda-forge::coreutils",
                        node_id="coreutils",
                        inputs={"primary": {"fromInput": "input"}},
                    )
                ],
                outputs=[{"from": {"nodeId": "coreutils", "port": "count"}, "as": "count"}],
            ),
            upload_id=upload["uploadId"],
            draft_name="Coreutils workflow",
        ),
    )

    work_dir = Path(cfg.work_dir) / "run_generated_tool"
    snakefile = (work_dir / "workflow" / "Snakefile").read_text(encoding="utf-8")
    env_yaml = (work_dir / "workflow" / "envs" / "conda-forge_coreutils.yaml").read_text(encoding="utf-8")
    run_config = json.loads((work_dir / "run-config.json").read_text(encoding="utf-8"))

    assert len(calls) == 2
    assert calls[0][0] == cfg.snakemake_command
    assert calls[0][calls[0].index("--snakefile") + 1] == str(work_dir / "workflow" / "Snakefile")
    assert "--workflow-profile" in calls[0]
    assert str(Path(cfg.workflow_profile_dir)) in calls[0]
    assert 'conda:'.encode().decode() in snakefile
    assert "envs/conda-forge_coreutils.yaml" in snakefile
    assert "wc -c" in snakefile
    assert "count=" in snakefile
    assert "conda-forge::coreutils=9.5" in env_yaml
    assert run_config["pipeline_id"] == GENERATED_TOOL_RUN_PIPELINE_ID
    assert run_config["tool"]["id"] == "conda-forge::coreutils"
    assert run_config["tool"]["ruleTemplate"]["commandTemplate"] == "wc -c {input.primary:q} > {output.count:q}"
    assert run_config["outputs"]["count"].endswith("wc-count.txt")


def test_tool_rule_template_is_persisted(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)

    saved = upsert_tool(
        cfg,
        {
            "id": "conda-forge::coreutils",
            "name": "coreutils",
            "source": "conda-forge",
            "sourceLabel": "conda-forge",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "wc -c {input.primary:q} > {output.count:q}",
                "inputs": [{"name": "primary"}],
                "outputs": [{"name": "count", "path": "wc-count.txt", "kind": "log", "mimeType": "text/plain"}],
            },
        },
    )

    assert saved["ruleTemplate"]["commandTemplate"] == "wc -c {input.primary:q} > {output.count:q}"


def test_tool_rule_spec_draft_is_persisted(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)

    saved = upsert_tool(
        cfg,
        {
            "id": "bioconda::fastq",
            "name": "fastq",
            "source": "bioconda",
            "sourceLabel": "Bioconda",
            "packageSpec": "bioconda::fastq=2.0.4",
            "targetPlatformSupported": True,
            "ruleSpecDraft": {
                "source": "conda-package",
                "requiresUserCompletion": True,
                "lock": {"type": "conda-package", "packageSpec": "bioconda::fastq=2.0.4"},
                "ruleTemplate": {
                    "commandTemplate": "fastq {input.primary:q} > {output.primary:q}",
                    "inputs": [{"name": "primary"}],
                    "outputs": [
                        {
                            "name": "primary",
                            "path": "fastq.out",
                            "kind": "file",
                            "mimeType": "application/octet-stream",
                        }
                    ],
                },
            },
        },
    )

    assert saved["ruleSpecDraft"]["source"] == "conda-package"
    assert saved["ruleSpecDraft"]["lock"]["packageSpec"] == "bioconda::fastq=2.0.4"


def test_tool_rule_template_accepts_outputs_without_semantic_metadata(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)

    saved = add_registered_tool(
        cfg,
        {
            "id": "conda-forge::coreutils",
            "name": "coreutils",
            "source": "conda-forge",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "wc -c {input.primary:q} > {output.count:q}",
                "inputs": [{"name": "primary"}],
                "outputs": [{"name": "count", "path": "wc-count.txt"}],
            },
        },
    )

    assert saved["ruleTemplate"]["outputs"] == [{"name": "count", "path": "wc-count.txt"}]


def test_tool_rule_template_rejects_unknown_command_tokens(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)

    try:
        add_registered_tool(
            cfg,
            {
                "id": "conda-forge::coreutils",
                "name": "coreutils",
                "source": "conda-forge",
                "packageSpec": "conda-forge::coreutils=9.5",
                "targetPlatformSupported": True,
                "ruleTemplate": {
                    "commandTemplate": "wc -c {input.missing:q} > {output.count:q}",
                    "inputs": [{"name": "primary"}],
                    "outputs": [{"name": "count", "path": "wc-count.txt", "kind": "log", "mimeType": "text/plain"}],
                },
            },
        )
    except ToolRegistryError as exc:
        assert str(exc) == "TOOL_RULE_TOKEN_UNSUPPORTED: {input.missing:q}"
    else:
        raise AssertionError("unknown input token should be rejected")


def test_generated_workflow_rejects_unbound_command_input_token(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    upsert_tool(
        cfg,
        {
            "id": "conda-forge::optional-input",
            "name": "optional-input",
            "source": "conda-forge",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "cat {input.primary:q} {input.sidecar:q} > {output.count:q}",
                "inputs": [
                    {"name": "primary", "type": "file", "required": True},
                    {"name": "sidecar", "type": "file", "required": False},
                ],
                "outputs": [{"name": "count", "path": "wc-count.txt", "kind": "log", "mimeType": "text/plain"}],
            },
        },
    )
    reads = tmp_path / "reads.txt"
    reads.write_text("ACGT\n", encoding="utf-8")

    try:
        prepare_generated_tool_workflow(
            cfg,
            run_id="run_unbound_command_input",
            request_id="req_unbound_command_input",
            run_spec={
                "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
                "workflow": generated_workflow_graph(
                    [
                        generated_workflow_node(
                            "conda-forge::optional-input",
                            node_id="count",
                            inputs={"primary": {"fromInput": "input"}},
                        )
                    ],
                ),
            },
            resolved_inputs=[{"path": str(reads), "role": "input", "filename": "reads.txt"}],
            work_dir=tmp_path / "work",
            result_dir=tmp_path / "results",
        )
    except ValueError as exc:
        assert str(exc) == "WORKFLOW_STEP_INPUT_TOKEN_UNBOUND: sidecar"
    else:
        raise AssertionError("command input token should require a concrete input binding")


def test_tool_rule_template_accepts_declared_param_tokens(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)

    saved = add_registered_tool(
        cfg,
        {
            "id": "conda-forge::coreutils",
            "name": "coreutils",
            "source": "conda-forge",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "head -n {params.limit} {input.primary:q} > {output.filtered:q}",
                "inputs": [{"name": "primary"}],
                "outputs": [{"name": "filtered", "path": "filtered.txt", "kind": "log", "mimeType": "text/plain"}],
                "params": {"limit": {"type": "integer", "default": 10}},
            },
        },
    )

    assert saved["ruleTemplate"]["params"]["limit"]["default"] == 10


def test_tool_rule_template_accepts_runtime_directive_tokens(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)

    saved = add_registered_tool(
        cfg,
        {
            "id": "conda-forge::coreutils",
            "name": "coreutils",
            "source": "conda-forge",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "wc -c --threads {threads} --mem {resources.mem_mb} {input.primary:q} > {output.count:q} 2> {log:q}",
                "inputs": [{"name": "primary"}],
                "outputs": [{"name": "count", "path": "wc-count.txt", "kind": "log", "mimeType": "text/plain"}],
                "resources": {
                    "threads": {"default": 4},
                    "mem_mb": {"default": 8000},
                },
                "log": "logs/wc-count.log",
            },
        },
    )

    assert saved["ruleTemplate"]["threads"] == 4
    assert saved["ruleTemplate"]["schedulerResources"]["mem_mb"] == 8000
    assert saved["ruleTemplate"]["log"] == "logs/wc-count.log"
    assert "resources" not in saved["ruleTemplate"]


def test_generated_linear_workflow_writes_multiple_rules_and_step_dependencies(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    for tool_id, command, output_name, output_path in [
        ("conda-forge::coreutils-count", "wc -c {input.primary:q} > {output.count:q}", "count", "wc-count.txt"),
        ("conda-forge::coreutils-copy", "cp {input.primary:q} {output.final:q}", "final", "final-count.txt"),
    ]:
        upsert_tool(
            cfg,
            {
                "id": tool_id,
                "name": "coreutils",
                "source": "conda-forge",
                "sourceLabel": "conda-forge",
                "version": "9.5",
                "packageSpec": "conda-forge::coreutils=9.5",
                "targetPlatform": "linux-64",
                "targetPlatformSupported": True,
                "ruleTemplate": {
                    "commandTemplate": command,
                    "inputs": [{"name": "primary", "type": "file", "required": True}],
                    "outputs": [{"name": output_name, "path": output_path, "kind": "log", "mimeType": "text/plain"}],
                },
                "status": "declared",
                "message": "Tool declared.",
            },
        )
    upload = persist_upload(
        cfg,
        filename="reads.txt",
        content_base64="QUJDREVGCg==",
        mime_type="text/plain",
    )
    calls: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(cmd, **_kwargs):
        calls.append(cmd)
        return Result()

    monkeypatch.setattr("apps.remote_runner.executor.subprocess.run", fake_run)
    monkeypatch.setattr("apps.remote_runner.executor._collect_artifacts", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("apps.remote_runner.executor.update_run_state", lambda *args, **kwargs: None)
    monkeypatch.setattr("apps.remote_runner.executor.append_log_lines", lambda *args, **kwargs: None)

    run_snakemake_execution(
        cfg,
        run_id="run_generated_linear",
        request_id="req_generated_linear",
        run_spec=workflow_design_run_spec_from_graph(
            cfg,
            generated_workflow_graph(
                [
                    generated_workflow_node(
                        "conda-forge::coreutils-count",
                        node_id="count_bytes",
                        inputs={"primary": {"fromInput": "input"}},
                    ),
                    generated_workflow_node("conda-forge::coreutils-copy", node_id="copy_summary"),
                ],
                edges=[{"from": {"nodeId": "count_bytes", "port": "count"}, "to": {"nodeId": "copy_summary", "port": "primary"}}],
            ),
            upload_id=upload["uploadId"],
        ),
    )

    work_dir = Path(cfg.work_dir) / "run_generated_linear"
    snakefile = (work_dir / "workflow" / "Snakefile").read_text(encoding="utf-8")
    run_config = json.loads((work_dir / "run-config.json").read_text(encoding="utf-8"))

    assert len(calls) == 2
    assert "rule step_01_count_bytes:" in snakefile
    assert "rule step_02_copy_summary:" in snakefile
    assert "count_bytes-wc-count.txt" in snakefile
    assert "copy_summary-final-count.txt" in snakefile
    assert "cp " in snakefile
    assert "count_bytes-wc-count.txt" in run_config["workflow"]["steps"][1]["inputs"]["primary"]
    assert run_config["outputs"]["final"].endswith("copy_summary-final-count.txt")


def test_generated_graph_workflow_writes_rules_and_edges(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    for tool_id, command, output_name, output_path in [
        ("conda-forge::coreutils-count", "wc -c {input.primary:q} > {output.count:q}", "count", "wc-count.txt"),
        ("conda-forge::coreutils-copy", "cp {input.primary:q} {output.final:q}", "final", "final-count.txt"),
    ]:
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
                    "commandTemplate": command,
                    "inputs": [{"name": "primary", "type": "file", "required": True}],
                    "outputs": [{"name": output_name, "path": output_path, "kind": "log", "mimeType": "text/plain"}],
                },
                "status": "declared",
                "message": "Tool declared.",
            },
        )
    upload = persist_upload(
        cfg,
        filename="reads.txt",
        content_base64="QUJDREVGCg==",
        mime_type="text/plain",
    )
    calls: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(cmd, **_kwargs):
        calls.append(cmd)
        return Result()

    monkeypatch.setattr("apps.remote_runner.executor.subprocess.run", fake_run)
    monkeypatch.setattr("apps.remote_runner.executor._collect_artifacts", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("apps.remote_runner.executor.update_run_state", lambda *args, **kwargs: None)
    monkeypatch.setattr("apps.remote_runner.executor.append_log_lines", lambda *args, **kwargs: None)

    run_snakemake_execution(
        cfg,
        run_id="run_generated_graph_contract",
        request_id="req_generated_graph_contract",
        run_spec=workflow_design_run_spec_from_graph(
            cfg,
            generated_workflow_graph(
                [
                    generated_workflow_node("conda-forge::coreutils-copy", node_id="copy_summary"),
                    generated_workflow_node(
                        "conda-forge::coreutils-count",
                        node_id="count_bytes",
                        inputs={"primary": {"fromInput": "input"}},
                    ),
                ],
                edges=[
                    {
                        "from": {"nodeId": "count_bytes", "port": "count"},
                        "to": {"nodeId": "copy_summary", "port": "primary"},
                    }
                ],
                outputs=[{"from": {"nodeId": "copy_summary", "port": "final"}, "as": "final"}],
            ),
            upload_id=upload["uploadId"],
        ),
    )

    work_dir = Path(cfg.work_dir) / "run_generated_graph_contract"
    run_config = json.loads((work_dir / "run-config.json").read_text(encoding="utf-8"))
    snakefile = (work_dir / "workflow" / "Snakefile").read_text(encoding="utf-8")

    assert len(calls) == 2
    assert [step["id"] for step in run_config["workflow"]["steps"]] == ["count_bytes", "copy_summary"]
    assert "count_bytes-wc-count.txt" in run_config["workflow"]["steps"][1]["inputs"]["primary"]
    assert run_config["outputs"]["final"].endswith("copy_summary-final-count.txt")
    assert "rule step_01_count_bytes:" in snakefile
    assert "rule step_02_copy_summary:" in snakefile
