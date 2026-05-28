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
