from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from apps.remote_runner.tools import add_registered_tool
from tests.test_tool_contract_pipeline import _validate_registered_tool


def _cfg(tmp_path: Path) -> RemoteRunnerConfig:
    workflow_bin = tmp_path / "workflow-env" / "bin"
    return RemoteRunnerConfig(
        token="tool-contract-observability-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(Path.cwd() / "apps" / "remote_runner"),
        managed_conda_command=str(workflow_bin / "conda"),
        snakemake_command=str(workflow_bin / "snakemake"),
    )


def test_output_validation_records_validated_artifact_summary(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    workflow_bin = tmp_path / "workflow-env" / "bin"
    workflow_bin.mkdir(parents=True, exist_ok=True)
    for command in ["conda", "snakemake"]:
        path = workflow_bin / command
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)
    add_registered_tool(
        cfg,
        {
            "id": "conda-forge::observable",
            "name": "observable",
            "source": "conda-forge",
            "packageSpec": "conda-forge::observable=9.5",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "cp {input.primary:q} {output.report:q}",
                "inputs": [{"name": "primary", "type": "file", "required": True}],
                "outputs": [{"name": "report", "path": "report.txt", "kind": "log", "mimeType": "text/plain"}],
                "params": {},
                "resources": {"threads": {"default": 1}, "mem_mb": {"default": 128}},
                "log": "logs/observable.log",
                "environment": {"conda": {"channels": ["conda-forge"], "dependencies": ["conda-forge::observable=9.5"]}},
                "smokeTest": {"inputs": {"primary": {"filename": "input.txt", "content": "hello\n"}}},
            },
        },
    )

    def fake_run(cmd, **_kwargs):
        if "--version" in cmd:
            return SimpleNamespace(returncode=0, stdout="9.19.0\n", stderr="")
        if "-n" not in cmd:
            config_path = Path(cmd[cmd.index("--configfile") + 1])
            run_config = json.loads(config_path.read_text(encoding="utf-8"))
            output = Path(run_config["outputs"]["report"])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("ok\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    with patch("apps.remote_runner.tool_contract_validation.subprocess.run", fake_run):
        checked = _validate_registered_tool(cfg, "conda-forge::observable")

    output_status = checked["contractStatus"]["outputValidation"]
    assert output_status["status"] == "passed"
    assert output_status["artifactCount"] == "1"
    assert output_status["artifactNames"] == "report"
    log_path = Path(output_status["logPath"])
    assert log_path.name == "smoke-run.log"
    assert "ok" in log_path.read_text(encoding="utf-8")


def test_output_validation_failure_records_smoke_log_path(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    workflow_bin = tmp_path / "workflow-env" / "bin"
    workflow_bin.mkdir(parents=True, exist_ok=True)
    for command in ["conda", "snakemake"]:
        path = workflow_bin / command
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)
    add_registered_tool(
        cfg,
        {
            "id": "conda-forge::missing-output",
            "name": "missing-output",
            "source": "conda-forge",
            "packageSpec": "conda-forge::missing-output=9.5",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "true",
                "inputs": [{"name": "primary", "type": "file", "required": True}],
                "outputs": [{"name": "report", "path": "report.txt", "kind": "log", "mimeType": "text/plain"}],
                "params": {},
                "resources": {"threads": {"default": 1}, "mem_mb": {"default": 128}},
                "log": "logs/missing-output.log",
                "environment": {"conda": {"channels": ["conda-forge"], "dependencies": ["conda-forge::missing-output=9.5"]}},
                "smokeTest": {"inputs": {"primary": {"filename": "input.txt", "content": "hello\n"}}},
            },
        },
    )

    def fake_run(_cmd, **_kwargs):
        return SimpleNamespace(returncode=0, stdout="smoke ok\n", stderr="")

    with patch("apps.remote_runner.tool_contract_validation.subprocess.run", fake_run):
        checked = _validate_registered_tool(cfg, "conda-forge::missing-output")

    output_status = checked["contractStatus"]["outputValidation"]
    assert output_status["status"] == "failed"
    assert output_status["code"] == "OUTPUT_ARTIFACT_MISSING"
    log_path = Path(output_status["logPath"])
    assert log_path.name == "smoke-run.log"
    assert "smoke ok" in log_path.read_text(encoding="utf-8")
