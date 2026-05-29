from __future__ import annotations

import json
from pathlib import Path

from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from apps.remote_runner.executor import run_snakemake_execution
from apps.remote_runner.generated_workflow import GENERATED_TOOL_RUN_PIPELINE_ID, prepare_generated_tool_workflow
from apps.remote_runner.pipeline import list_pipelines
from apps.remote_runner.storage import persist_upload, upsert_tool
from apps.remote_runner.tools import ToolRegistryError, add_registered_tool


def _cfg(tmp_path: Path) -> RemoteRunnerConfig:
    return RemoteRunnerConfig(
        token="phase-tool-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(Path.cwd() / "apps" / "remote_runner"),
        managed_conda_command=str(tmp_path / "workflow-env" / "bin" / "conda"),
        snakemake_command=str(tmp_path / "workflow-env" / "bin" / "snakemake"),
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
        run_spec={
            "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
            "projectId": "proj_demo",
            "inputs": [{"uploadId": upload["uploadId"], "filename": "reads.txt", "role": "input"}],
            "tool": {
                "id": "conda-forge::coreutils",
            },
        },
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


def test_tool_rule_template_rejects_incomplete_outputs(tmp_path: Path) -> None:
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
                    "commandTemplate": "wc -c {input.primary:q} > {output.count:q}",
                    "inputs": [{"name": "primary"}],
                    "outputs": [{"name": "count", "path": "wc-count.txt"}],
                },
            },
        )
    except ToolRegistryError as exc:
        assert str(exc) == "TOOL_RULE_OUTPUT_SPEC_INVALID"
    else:
        raise AssertionError("incomplete output metadata should be rejected")


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
                "workflow": {
                    "steps": [
                        {
                            "id": "count",
                            "tool": {"id": "conda-forge::optional-input"},
                            "inputs": {"primary": {"fromInput": "input"}},
                        }
                    ]
                },
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
        run_spec={
            "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
            "projectId": "proj_demo",
            "inputs": [{"uploadId": upload["uploadId"], "filename": "reads.txt", "role": "input"}],
            "workflow": {
                "steps": [
                    {"id": "count_bytes", "tool": {"id": "conda-forge::coreutils-count"}},
                    {"id": "copy_summary", "tool": {"id": "conda-forge::coreutils-copy"}},
                ],
            },
        },
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
        run_spec={
            "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
            "projectId": "proj_demo",
            "inputs": [{"uploadId": upload["uploadId"], "filename": "reads.txt", "role": "input"}],
            "workflow": {
                "contractVersion": "rule-contract-v1",
                "nodes": [
                    {"id": "copy_summary", "toolId": "conda-forge::coreutils-copy"},
                    {"id": "count_bytes", "toolId": "conda-forge::coreutils-count", "inputs": {"primary": {"fromUpload": 0}}},
                ],
                "edges": [
                    {
                        "from": {"nodeId": "count_bytes", "port": "count"},
                        "to": {"nodeId": "copy_summary", "port": "primary"},
                    }
                ],
                "outputs": [{"from": {"nodeId": "copy_summary", "port": "final"}, "as": "final"}],
            },
        },
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
        run_spec={
            "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
            "projectId": "proj_demo",
            "inputs": [{"uploadId": upload["uploadId"], "filename": "reads.txt", "role": "input"}],
            "workflow": {
                "steps": [
                    {
                        "id": "filter_reads",
                        "tool": {"id": "conda-forge::awk-filter"},
                        "params": {"limit": 5},
                    }
                ]
            },
        },
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
            "workflow": {
                "steps": [
                    {
                        "id": "filter_reads",
                        "tool": {"id": "conda-forge::params-directive"},
                        "inputs": {"primary": {"fromInput": "reads"}},
                        "params": {"limit": 5},
                    }
                ]
            },
        },
        resolved_inputs=[{"path": str(reads), "role": "reads", "filename": "reads.txt"}],
        work_dir=tmp_path / "work",
        result_dir=tmp_path / "results",
    )

    snakefile = generated.snakefile.read_text(encoding="utf-8")

    assert "    params:\n        limit=5,\n" in snakefile


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
        run_spec={
            "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
            "projectId": "proj_demo",
            "inputs": [{"uploadId": upload["uploadId"], "filename": "reads.txt", "role": "input"}],
            "tool": {"id": "conda-forge::runtime-demo"},
        },
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
        run_spec={
            "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
            "projectId": "proj_demo",
            "inputs": [{"uploadId": upload["uploadId"], "filename": "reads.txt", "role": "input"}],
            "workflow": {
                "steps": [
                    {
                        "id": "merge",
                        "tool": {"id": "conda-forge::merge"},
                        "inputs": {
                            "left": {"fromStep": "branch_a", "output": "left"},
                            "right": {"fromStep": "branch_b", "output": "right"},
                        },
                    },
                    {
                        "id": "branch_b",
                        "tool": {"id": "conda-forge::branch-b"},
                        "inputs": {"primary": {"fromStep": "source", "output": "seed"}},
                    },
                    {
                        "id": "source",
                        "tool": {"id": "conda-forge::source"},
                        "inputs": {"primary": {"fromUpload": 0}},
                    },
                    {
                        "id": "branch_a",
                        "tool": {"id": "conda-forge::branch-a"},
                        "inputs": {"primary": {"fromStep": "source", "output": "seed"}},
                    },
                ],
                "outputs": {
                    "merged": {"step": "merge", "output": "final"},
                    "left_qc": {"step": "branch_a", "output": "left"},
                },
            },
        },
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
