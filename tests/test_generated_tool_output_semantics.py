from __future__ import annotations

import json
from pathlib import Path

from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from apps.remote_runner.executor import _collect_artifacts, run_snakemake_execution
from apps.remote_runner.generated_workflow import GENERATED_TOOL_RUN_PIPELINE_ID, prepare_generated_tool_workflow
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


def test_tool_rule_template_accepts_output_semantics(tmp_path: Path) -> None:
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
                "commandTemplate": "mkdir -p {output.cache:q}; cp {input.primary:q} {output.report:q}",
                "inputs": [{"name": "primary"}],
                "outputs": [
                    {
                        "name": "cache",
                        "path": "cache-dir",
                        "kind": "directory",
                        "mimeType": "inode/directory",
                        "directory": True,
                        "temp": True,
                    },
                    {
                        "name": "report",
                        "path": "report.html",
                        "kind": "report",
                        "mimeType": "text/html",
                        "protected": True,
                    },
                ],
            },
        },
    )

    outputs = {item["name"]: item for item in saved["ruleTemplate"]["outputs"]}
    assert outputs["cache"]["directory"] is True
    assert outputs["cache"]["temp"] is True
    assert outputs["report"]["protected"] is True


def test_tool_rule_template_rejects_conflicting_output_semantics(tmp_path: Path) -> None:
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
                    "commandTemplate": "cp {input.primary:q} {output.report:q}",
                    "inputs": [{"name": "primary"}],
                    "outputs": [
                        {
                            "name": "report",
                            "path": "report.html",
                            "kind": "report",
                            "mimeType": "text/html",
                            "temp": True,
                            "protected": True,
                        }
                    ],
                },
            },
        )
    except ToolRegistryError as exc:
        assert str(exc) == "TOOL_RULE_OUTPUT_FLAGS_INVALID: report"
    else:
        raise AssertionError("temp and protected output semantics should be rejected together")


def test_generated_workflow_renders_output_semantics(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    upsert_tool(
        cfg,
        {
            "id": "conda-forge::output-semantics",
            "name": "output-semantics",
            "source": "conda-forge",
            "sourceLabel": "conda-forge",
            "version": "9.5",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "mkdir -p {output.cache:q}; cp {input.primary:q} {output.report:q}",
                "inputs": [{"name": "primary", "type": "file", "required": True}],
                "outputs": [
                    {
                        "name": "cache",
                        "path": "cache-dir",
                        "kind": "directory",
                        "mimeType": "inode/directory",
                        "directory": True,
                        "temp": True,
                    },
                    {
                        "name": "report",
                        "path": "report.html",
                        "kind": "report",
                        "mimeType": "text/html",
                        "protected": True,
                    },
                ],
            },
            "status": "declared",
            "message": "Tool declared.",
        },
    )
    upload = persist_upload(cfg, filename="reads.txt", content_base64="QUJDREVGCg==", mime_type="text/plain")
    collected: dict[str, dict] = {}

    class Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_collect(_cfg, _run_id, *, output_schema, outputs):
        collected["output_schema"] = output_schema
        collected["outputs"] = outputs
        return []

    monkeypatch.setattr("apps.remote_runner.executor.subprocess.run", lambda *_args, **_kwargs: Result())
    monkeypatch.setattr("apps.remote_runner.executor._collect_artifacts", fake_collect)
    monkeypatch.setattr("apps.remote_runner.executor.update_run_state", lambda *args, **kwargs: None)
    monkeypatch.setattr("apps.remote_runner.executor.append_log_lines", lambda *args, **kwargs: None)

    run_snakemake_execution(
        cfg,
        run_id="run_generated_output_semantics",
        request_id="req_generated_output_semantics",
        run_spec={
            "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
            "projectId": "proj_demo",
            "inputs": [{"uploadId": upload["uploadId"], "filename": "reads.txt", "role": "input"}],
            "workflow": {
                "steps": [{"id": "run_tool", "tool": {"id": "conda-forge::output-semantics"}}],
                "outputs": {"report": "run_tool.report"},
            },
        },
    )

    work_dir = Path(cfg.work_dir) / "run_generated_output_semantics"
    snakefile = (work_dir / "workflow" / "Snakefile").read_text(encoding="utf-8")
    run_config = json.loads((work_dir / "run-config.json").read_text(encoding="utf-8"))
    artifacts = {item["key"]: item for item in collected["output_schema"]["artifacts"]}
    output_specs = run_config["workflow"]["steps"][0]["outputSpecs"]
    exposed_outputs = run_config["workflow"]["outputs"]

    assert "cache=temp(directory(" in snakefile
    assert "report=protected(" in snakefile
    assert "cache" not in artifacts
    assert artifacts["report"]["protected"] is True
    assert output_specs["cache"]["directory"] is True
    assert output_specs["cache"]["temp"] is True
    assert output_specs["cache"]["kind"] == "directory"
    assert output_specs["report"]["protected"] is True
    assert exposed_outputs["report"]["protected"] is True


def test_generated_workflow_rejects_exposed_temp_outputs(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
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
    input_path = tmp_path / "reads.txt"
    input_path.write_text("ACGT\n", encoding="utf-8")

    try:
        prepare_generated_tool_workflow(
            cfg,
            run_id="run_temp_output",
            request_id="req_temp_output",
            run_spec={
                "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
                "tool": {"id": "conda-forge::temp-output"},
            },
            resolved_inputs=[{"path": str(input_path), "role": "input"}],
            work_dir=tmp_path / "work",
            result_dir=tmp_path / "results",
        )
    except ValueError as exc:
        assert str(exc) == "WORKFLOW_OUTPUT_TEMP_EXPOSED: run_tool.cache"
    else:
        raise AssertionError("generated workflow should reject temp outputs as final artifacts")


def test_output_artifact_collection_accepts_declared_directories(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    output_dir = tmp_path / "outputs" / "cache"
    output_dir.mkdir(parents=True)
    (output_dir / "alpha.txt").write_bytes(b"alpha\n")
    nested = output_dir / "nested"
    nested.mkdir()
    (nested / "beta.txt").write_bytes(b"beta\n")

    artifacts = _collect_artifacts(
        cfg,
        "run_directory_artifact",
        output_schema={
            "artifacts": [
                {
                    "key": "cache",
                    "kind": "directory",
                    "mimeType": "inode/directory",
                    "directory": True,
                }
            ]
        },
        outputs={"cache": str(output_dir)},
    )

    assert artifacts[0]["path"] == str(output_dir)
    assert artifacts[0]["sizeBytes"] == 11
    assert artifacts[0]["sha256"]


def test_output_artifact_collection_rejects_empty_text_outputs(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    output = tmp_path / "outputs" / "report.txt"
    output.parent.mkdir(parents=True)
    output.write_text("", encoding="utf-8")

    try:
        _collect_artifacts(
            cfg,
            "run_empty_output",
            output_schema={
                "artifacts": [
                    {"key": "report", "kind": "log", "mimeType": "text/plain"},
                ]
            },
            outputs={"report": str(output)},
        )
    except ValueError as exc:
        assert str(exc) == "OUTPUT_ARTIFACT_EMPTY: Output file is empty: report"
    else:
        raise AssertionError("empty declared text outputs should fail artifact collection")
