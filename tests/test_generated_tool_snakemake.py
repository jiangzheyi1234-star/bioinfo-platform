from __future__ import annotations

import json
from pathlib import Path

from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from apps.remote_runner.executor import run_snakemake_execution
from apps.remote_runner.generated_workflow import GENERATED_TOOL_RUN_PIPELINE_ID
from apps.remote_runner.pipeline import list_pipelines
from apps.remote_runner.storage import persist_upload, upsert_tool


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
    snakefile = (work_dir / "Snakefile").read_text(encoding="utf-8")
    env_yaml = (work_dir / "envs" / "conda-forge_coreutils.yaml").read_text(encoding="utf-8")
    run_config = json.loads((work_dir / "run-config.json").read_text(encoding="utf-8"))

    assert len(calls) == 2
    assert calls[0][0] == cfg.snakemake_command
    assert calls[0][calls[0].index("--snakefile") + 1] == str(work_dir / "Snakefile")
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
                "outputs": [{"name": "count", "path": "wc-count.txt"}],
            },
        },
    )

    assert saved["ruleTemplate"]["commandTemplate"] == "wc -c {input.primary:q} > {output.count:q}"


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
    snakefile = (work_dir / "Snakefile").read_text(encoding="utf-8")
    run_config = json.loads((work_dir / "run-config.json").read_text(encoding="utf-8"))

    assert len(calls) == 2
    assert "rule step_01_count_bytes:" in snakefile
    assert "rule step_02_copy_summary:" in snakefile
    assert "count_bytes-wc-count.txt" in snakefile
    assert "copy_summary-final-count.txt" in snakefile
    assert "cp " in snakefile
    assert "count_bytes-wc-count.txt" in run_config["workflow"]["steps"][1]["inputs"]["primary"]
    assert run_config["outputs"]["final"].endswith("copy_summary-final-count.txt")
