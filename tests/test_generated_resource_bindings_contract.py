from __future__ import annotations

from pathlib import Path

from apps.remote_runner.config import RemoteRunnerConfig
from apps.remote_runner.generated_workflow import GENERATED_TOOL_RUN_PIPELINE_ID, prepare_generated_tool_workflow


def test_generated_workflow_rejects_legacy_database_bindings(tmp_path: Path) -> None:
    cfg = RemoteRunnerConfig(
        token="generated-resource-bindings-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(Path.cwd() / "apps" / "remote_runner"),
    )

    try:
        prepare_generated_tool_workflow(
            cfg,
            run_id="run_legacy_database",
            request_id="req_legacy_database",
            run_spec={
                "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
                "tool": {"id": "conda-forge::coreutils"},
                "databases": [{"id": "db_demo", "role": "taxonomy"}],
            },
            resolved_inputs=[{"path": str(tmp_path / "reads.txt")}],
            work_dir=tmp_path / "work",
            result_dir=tmp_path / "results",
        )
    except ValueError as exc:
        assert str(exc) == "RESOURCE_BINDINGS_REQUIRED"
    else:
        raise AssertionError("legacy generated workflow databases should be rejected")
