from __future__ import annotations

import json
from pathlib import Path

from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from apps.remote_runner.executor import run_snakemake_execution
from apps.remote_runner.storage import persist_upload
from tests.generated_workflow_test_helpers import (
    generated_workflow_graph,
    generated_workflow_node,
    upsert_ready_tool,
    workflow_design_run_spec_from_graph,
)


def _cfg(tmp_path: Path) -> RemoteRunnerConfig:
    return RemoteRunnerConfig(
        token="runtime-override-token",
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


def test_generated_workflow_renders_step_runtime_overrides(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    upsert_ready_tool(
        cfg,
        {
            "id": "conda-forge::runtime-override-demo",
            "name": "runtime-override-demo",
            "source": "conda-forge",
            "sourceLabel": "conda-forge",
            "version": "9.5",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "printf '%s\\t%s\\t%s\\n' {threads} {resources.mem_mb} {resources.runtime} > {output.report:q}",
                "inputs": [{"name": "primary", "type": "file", "required": True}],
                "outputs": [{"name": "report", "path": "runtime-override.txt", "kind": "log", "mimeType": "text/plain"}],
                "threads": {"default": 4},
                "schedulerResources": {"mem_mb": {"default": 8000}, "runtime": {"default": 30}},
            },
            "status": "declared",
            "message": "Tool declared.",
        },
    )
    upload = persist_upload(cfg, filename="reads.txt", content_base64="QUJDREVGCg==", mime_type="text/plain")

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
        run_id="run_generated_runtime_override",
        request_id="req_generated_runtime_override",
        run_spec=workflow_design_run_spec_from_graph(
            cfg,
            generated_workflow_graph(
                [
                    generated_workflow_node(
                        "conda-forge::runtime-override-demo",
                        node_id="runtime_override",
                        inputs={"primary": {"fromInput": "input"}},
                        runtime={"threads": 2, "resources": {"mem_mb": 4096}},
                    )
                ],
                outputs=[{"from": {"nodeId": "runtime_override", "port": "report"}, "as": "report"}],
            ),
            upload_id=upload["uploadId"],
            draft_name="Runtime override workflow",
        ),
    )

    work_dir = Path(cfg.work_dir) / "run_generated_runtime_override"
    snakefile = (work_dir / "workflow" / "Snakefile").read_text(encoding="utf-8")
    run_config = json.loads((work_dir / "run-config.json").read_text(encoding="utf-8"))
    step_config = run_config["workflow"]["steps"][0]

    assert "    threads: 2\n" in snakefile
    assert "    resources:\n        mem_mb=4096,\n        runtime=30,\n" in snakefile
    assert "printf '%s\\t%s\\t%s\\n' 2 4096 30" in snakefile
    assert step_config["threads"] == 2
    assert step_config["resources"] == {"mem_mb": 4096, "runtime": 30}
