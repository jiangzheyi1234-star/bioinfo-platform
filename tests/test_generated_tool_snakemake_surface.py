from __future__ import annotations

import json
from pathlib import Path

from apps.remote_runner.config import ensure_runtime_layout
from apps.remote_runner.executor import run_snakemake_execution
from apps.remote_runner.generated_workflow import GENERATED_TOOL_RUN_PIPELINE_ID
from apps.remote_runner.storage import persist_upload
from tests.generated_workflow_test_helpers import (
    generated_workflow_graph,
    generated_workflow_node,
    generated_workflow_runner_config as _cfg,
    prepare_unchecked_generated_tool_workflow as prepare_generated_tool_workflow,
    upsert_ready_tool as upsert_tool,
    workflow_design_run_spec_from_graph,
)


def test_generated_graph_run_config_preserves_graph_contract(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    for tool_id, command, output_name, output_path in [
        ("conda-forge::graph-source", "cp {input.primary:q} {output.seed:q}", "seed", "seed.txt"),
        ("conda-forge::graph-copy", "cp {input.primary:q} {output.final:q}", "final", "final.txt"),
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
    reads = tmp_path / "reads.txt"
    reads.write_text("ACGT\n", encoding="utf-8")

    prepare_generated_tool_workflow(
        cfg,
        run_id="run_generated_graph_config",
        request_id="req_generated_graph_config",
        run_spec={
            "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
            "workflow": generated_workflow_graph(
                [
                    generated_workflow_node(
                        "conda-forge::graph-source",
                        node_id="source",
                        inputs={"primary": {"fromInput": "reads"}},
                    ),
                    generated_workflow_node("conda-forge::graph-copy", node_id="copy"),
                ],
                edges=[
                    {
                        "from": {"nodeId": "source", "port": "seed"},
                        "to": {"nodeId": "copy", "port": "primary"},
                        "audit": {"source": "auto", "decision": "recommended", "reason": "匹配 type"},
                    }
                ],
                outputs=[{"from": {"nodeId": "copy", "port": "final"}, "as": "final"}],
            ),
        },
        resolved_inputs=[{"path": str(reads), "role": "reads", "filename": "reads.txt"}],
        work_dir=tmp_path / "work",
        result_dir=tmp_path / "results",
    )
    run_config = json.loads((tmp_path / "work" / "run-config.json").read_text(encoding="utf-8"))
    graph = run_config["workflow"]["graph"]
    assert graph["contractVersion"] == "rule-contract-v1"
    assert [node["id"] for node in graph["nodes"]] == ["source", "copy"]
    assert graph["edges"] == [
        {
            "from": {"nodeId": "source", "port": "seed"},
            "to": {"nodeId": "copy", "port": "primary"},
            "audit": {"source": "auto", "decision": "recommended", "reason": "匹配 type"},
        }
    ]
    assert graph["outputs"] == [{"from": {"nodeId": "copy", "port": "final"}, "as": "final"}]


def test_generated_workflow_renders_step_params_tokens(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    upsert_tool(
        cfg,
        {
            "id": "conda-forge::awk-filter",
            "name": "awk-filter",
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
        run_id="run_generated_params",
        request_id="req_generated_params",
        run_spec=workflow_design_run_spec_from_graph(
            cfg,
            generated_workflow_graph(
                [
                    generated_workflow_node(
                        "conda-forge::awk-filter",
                        node_id="filter_reads",
                        inputs={"primary": {"fromInput": "input"}},
                        params={"limit": 5},
                    )
                ],
            ),
            upload_id=upload["uploadId"],
        ),
    )
    work_dir = Path(cfg.work_dir) / "run_generated_params"
    snakefile = (work_dir / "workflow" / "Snakefile").read_text(encoding="utf-8")
    run_config = json.loads((work_dir / "run-config.json").read_text(encoding="utf-8"))
    assert len(calls) == 2
    assert "head -n 5" in snakefile
    assert "{params.limit}" not in snakefile
    assert run_config["workflow"]["steps"][0]["params"]["limit"] == 5


def test_generated_workflow_renders_step_params_directive(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    upsert_tool(
        cfg,
        {
            "id": "conda-forge::params-directive",
            "name": "params-directive",
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
    reads = tmp_path / "reads.txt"
    reads.write_text("ACGT\n", encoding="utf-8")
    generated = prepare_generated_tool_workflow(
        cfg,
        run_id="run_generated_params_directive",
        request_id="req_generated_params_directive",
        run_spec={
            "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
            "workflow": generated_workflow_graph(
                [
                    generated_workflow_node(
                        "conda-forge::params-directive",
                        node_id="filter_reads",
                        inputs={"primary": {"fromInput": "reads"}},
                        params={"limit": 5},
                    )
                ],
            ),
        },
        resolved_inputs=[{"path": str(reads), "role": "reads", "filename": "reads.txt"}],
        work_dir=tmp_path / "work",
        result_dir=tmp_path / "results",
    )
    snakefile = generated.snakefile.read_text(encoding="utf-8")
    assert "    params:\n        limit=5,\n" in snakefile


def test_generated_workflow_creates_output_parent_dirs_for_shell_rules(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    upsert_tool(
        cfg,
        {
            "id": "conda-forge::nested-output",
            "name": "nested-output",
            "source": "conda-forge",
            "sourceLabel": "conda-forge",
            "version": "9.5",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "wc -c {input.primary:q} > {output.report:q}",
                "inputs": [{"name": "primary", "type": "file", "required": True}],
                "outputs": [
                    {
                        "name": "report",
                        "path": "reports/nested-output.txt",
                        "kind": "report",
                        "mimeType": "text/plain",
                    }
                ],
            },
            "status": "declared",
            "message": "Tool declared.",
        },
    )
    reads = tmp_path / "reads.txt"
    reads.write_text("ACGT\n", encoding="utf-8")

    generated = prepare_generated_tool_workflow(
        cfg,
        run_id="run_generated_nested_output",
        request_id="req_generated_nested_output",
        run_spec={
            "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
            "workflow": generated_workflow_graph(
                [
                    generated_workflow_node(
                        "conda-forge::nested-output",
                        node_id="nested",
                        inputs={"primary": {"fromInput": "reads"}},
                    )
                ],
            ),
        },
        resolved_inputs=[{"path": str(reads), "role": "reads", "filename": "reads.txt"}],
        work_dir=tmp_path / "work",
        result_dir=tmp_path / "results",
    )

    snakefile = generated.snakefile.read_text(encoding="utf-8")
    output_parent = (tmp_path / "results" / "reports").as_posix()
    command_index = snakefile.index("wc -c")
    mkdir_index = snakefile.index(f"mkdir -p {output_parent}")
    assert mkdir_index < command_index


def test_generated_workflow_renders_runtime_directives(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    upsert_tool(
        cfg,
        {
            "id": "conda-forge::runtime-demo",
            "name": "runtime-demo",
            "source": "conda-forge",
            "sourceLabel": "conda-forge",
            "version": "9.5",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "printf '%s\\t%s\\n' {threads} {resources.mem_mb} > {output.report:q} 2> {log.stderr:q}",
                "inputs": [{"name": "primary", "type": "file", "required": True}],
                "outputs": [{"name": "report", "path": "runtime-report.txt", "kind": "log", "mimeType": "text/plain"}],
                "threads": {"default": 4},
                "schedulerResources": {"mem_mb": {"default": 8000}, "runtime": {"default": 30}},
                "log": {"stderr": "logs/runtime-demo.stderr.log"},
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

    class Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    monkeypatch.setattr("apps.remote_runner.executor.subprocess.run", lambda *_args, **_kwargs: Result())
    monkeypatch.setattr("apps.remote_runner.executor._collect_artifacts", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("apps.remote_runner.executor.update_run_state", lambda *args, **kwargs: None)
    monkeypatch.setattr("apps.remote_runner.executor.append_log_lines", lambda *args, **kwargs: None)

    run_snakemake_execution(
        cfg,
        run_id="run_generated_runtime",
        request_id="req_generated_runtime",
        run_spec=workflow_design_run_spec_from_graph(
            cfg,
            generated_workflow_graph(
                [
                    generated_workflow_node(
                        "conda-forge::runtime-demo",
                        inputs={"primary": {"fromInput": "input"}},
                    )
                ],
            ),
            upload_id=upload["uploadId"],
        ),
    )
    work_dir = Path(cfg.work_dir) / "run_generated_runtime"
    snakefile = (work_dir / "workflow" / "Snakefile").read_text(encoding="utf-8")
    run_config = json.loads((work_dir / "run-config.json").read_text(encoding="utf-8"))
    step_config = run_config["workflow"]["steps"][0]
    assert "    threads: 4\n" in snakefile
    assert "    resources:\n        mem_mb=8000,\n        runtime=30,\n" in snakefile
    assert "    log:\n        stderr=" in snakefile
    assert "runtime-demo.stderr.log" in snakefile
    assert "{threads}" not in snakefile
    assert "{resources.mem_mb}" not in snakefile
    assert "{log.stderr:q}" not in snakefile
    assert "printf '%s\\t%s\\n' 4 8000" in snakefile
    assert "mkdir -p" in snakefile
    assert step_config["threads"] == 4
    assert step_config["resources"] == {"mem_mb": 8000, "runtime": 30}
    stderr_log = Path(step_config["log"]["stderr"])
    assert stderr_log.name == "runtime-demo.stderr.log"
    assert stderr_log.parent.name == "logs"


def test_generated_workflow_topologically_orders_explicit_dag_bindings_and_exposed_outputs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    tool_specs = [
        (
            "conda-forge::source",
            "cp {input.primary:q} {output.seed:q}",
            [{"name": "primary", "type": "file", "required": True}],
            [{"name": "seed", "path": "seed.txt", "kind": "log", "mimeType": "text/plain"}],
        ),
        (
            "conda-forge::branch-a",
            "cp {input.primary:q} {output.left:q}",
            [{"name": "primary", "type": "file", "required": True}],
            [{"name": "left", "path": "left.txt", "kind": "log", "mimeType": "text/plain"}],
        ),
        (
            "conda-forge::branch-b",
            "cp {input.primary:q} {output.right:q}",
            [{"name": "primary", "type": "file", "required": True}],
            [{"name": "right", "path": "right.txt", "kind": "log", "mimeType": "text/plain"}],
        ),
        (
            "conda-forge::merge",
            "cat {input.left:q} {input.right:q} > {output.final:q}",
            [
                {"name": "left", "type": "file", "required": True},
                {"name": "right", "type": "file", "required": True},
            ],
            [{"name": "final", "path": "merged.txt", "kind": "log", "mimeType": "text/plain"}],
        ),
    ]
    for tool_id, command, inputs, outputs in tool_specs:
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
                    "inputs": inputs,
                    "outputs": outputs,
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
        run_id="run_generated_dag",
        request_id="req_generated_dag",
        run_spec=workflow_design_run_spec_from_graph(
            cfg,
            generated_workflow_graph(
                [
                    generated_workflow_node("conda-forge::merge", node_id="merge"),
                    generated_workflow_node("conda-forge::branch-b", node_id="branch_b"),
                    generated_workflow_node(
                        "conda-forge::source",
                        node_id="source",
                        inputs={"primary": {"fromInput": "input"}},
                    ),
                    generated_workflow_node("conda-forge::branch-a", node_id="branch_a"),
                ],
                edges=[
                    {"from": {"nodeId": "branch_a", "port": "left"}, "to": {"nodeId": "merge", "port": "left"}},
                    {"from": {"nodeId": "branch_b", "port": "right"}, "to": {"nodeId": "merge", "port": "right"}},
                    {"from": {"nodeId": "source", "port": "seed"}, "to": {"nodeId": "branch_b", "port": "primary"}},
                    {"from": {"nodeId": "source", "port": "seed"}, "to": {"nodeId": "branch_a", "port": "primary"}},
                ],
                outputs=[
                    {"from": {"nodeId": "merge", "port": "final"}, "as": "merged"},
                    {"from": {"nodeId": "branch_a", "port": "left"}, "as": "left_qc"},
                ],
            ),
            upload_id=upload["uploadId"],
        ),
    )
    work_dir = Path(cfg.work_dir) / "run_generated_dag"
    snakefile = (work_dir / "workflow" / "Snakefile").read_text(encoding="utf-8")
    run_config = json.loads((work_dir / "run-config.json").read_text(encoding="utf-8"))
    assert len(calls) == 2
    assert "rule step_01_source:" in snakefile
    assert "rule step_04_merge:" in snakefile
    assert [step["id"] for step in run_config["workflow"]["steps"]] == ["source", "branch_b", "branch_a", "merge"]
    assert "source-seed.txt" in run_config["workflow"]["steps"][1]["inputs"]["primary"]
    assert "branch_a-left.txt" in run_config["workflow"]["steps"][3]["inputs"]["left"]
    assert "branch_b-right.txt" in run_config["workflow"]["steps"][3]["inputs"]["right"]
    assert run_config["outputs"]["merged"].endswith("merge-merged.txt")
    assert run_config["outputs"]["left_qc"].endswith("branch_a-left.txt")
    assert "merge-merged.txt" in snakefile
    assert "branch_a-left.txt" in snakefile
