from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from apps.remote_runner.executor import run_snakemake_execution
from apps.remote_runner.generated_workflow import GENERATED_TOOL_RUN_PIPELINE_ID
from apps.remote_runner.storage import create_run_record, fetch_run, persist_upload, upsert_tool
from apps.remote_runner.tool_revisions import publish_tool_revision
from apps.remote_runner.tools import add_registered_tool


def _cfg(tmp_path: Path) -> RemoteRunnerConfig:
    return RemoteRunnerConfig(
        token="tool-contract-executor-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(Path.cwd() / "apps" / "remote_runner"),
        snakemake_command=str(tmp_path / "workflow-env" / "bin" / "snakemake"),
    )


def test_executor_rejects_generated_tool_run_when_contract_not_workflow_ready(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    upload = persist_upload(cfg, filename="input.txt", content_base64="c21va2UK", mime_type="text/plain")
    tool = add_registered_tool(
        cfg,
        {
            "id": "conda-forge::coreutils",
            "name": "coreutils",
            "source": "conda-forge",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "cp {input.primary:q} {output.report:q}",
                "inputs": [{"name": "primary", "type": "file", "required": True}],
                "outputs": [{"name": "report", "path": "report.txt", "kind": "log", "mimeType": "text/plain"}],
                "params": {},
                "resources": {"threads": {"default": 1}, "mem_mb": {"default": 128}},
                "log": "logs/coreutils.log",
                "environment": {
                    "conda": {"channels": ["conda-forge", "bioconda"], "dependencies": ["conda-forge::coreutils=9.5"]}
                },
                "smokeTest": {"inputs": {"primary": {"filename": "input.txt", "content": "smoke\n"}}},
            },
        },
    )
    revision = publish_tool_revision(cfg, tool)
    revision["status"] = "published"
    tool = upsert_tool(cfg, revision)
    run_spec = {
        "runId": "run_executor_contract_gate",
        "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
        "inputs": [{"uploadId": upload["uploadId"], "filename": "input.txt", "role": "input"}],
        "workflow": {
            "contractVersion": "rule-contract-v1",
            "nodes": [
                {
                    "id": "run_tool",
                    "toolRevisionId": tool["toolRevisionId"],
                    "inputs": {"primary": {"fromInput": "input"}},
                }
            ],
            "edges": [],
        },
    }
    create_run_record(
        cfg,
        server_id="srv_executor_contract",
        request_id="req_executor_contract",
        run_spec=run_spec,
        idempotency_key="idem_executor_contract",
        payload_hash="hash_executor_contract",
    )
    snakemake_calls: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        snakemake_calls.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    with patch("apps.remote_runner.executor.subprocess.run", fake_run):
        run_snakemake_execution(
            cfg,
            run_id="run_executor_contract_gate",
            request_id="req_executor_contract",
            run_spec=run_spec,
        )

    run = fetch_run(cfg, "run_executor_contract_gate")
    assert run is not None
    assert run["status"] == "failed"
    assert run["lastError"]["code"] == "WORKFLOW_TOOL_NOT_READY: SnakemakeRenderable"
    assert snakemake_calls == []
