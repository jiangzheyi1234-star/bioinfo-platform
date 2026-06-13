from __future__ import annotations

from pathlib import Path

import pytest

from apps.remote_runner.config import ensure_runtime_layout
from apps.remote_runner.tool_prepare_job_storage import create_tool_prepare_job, fetch_tool_prepare_job
from apps.remote_runner.tool_prepare_jobs import run_tool_prepare_job
from tests.test_tool_contract_pipeline import _cfg


def test_tool_prepare_job_does_not_mask_unexpected_validation_errors(monkeypatch, tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    job = create_tool_prepare_job(cfg, {"id": "bioconda::crash", "name": "crash"})

    def fail_validation(*_args, **_kwargs):
        raise RuntimeError("prepare validation adapter crashed")

    monkeypatch.setattr("apps.remote_runner.tool_prepare_jobs.validate_registered_tool_for_publish", fail_validation)

    with pytest.raises(RuntimeError, match="prepare validation adapter crashed"):
        run_tool_prepare_job(cfg, job["jobId"])

    finished = fetch_tool_prepare_job(cfg, job["jobId"])
    assert finished is not None
    assert finished["status"] == "running"
    assert finished["errorCode"] is None
    assert [event["stage"] for event in finished["events"]] == ["queued", "validating_spec"]


def test_tool_prepare_is_exposed_through_api_layers() -> None:
    root = Path(__file__).resolve().parents[1]
    remote_route = (root / "apps" / "remote_runner" / "tool_routes.py").read_text(encoding="utf-8")
    local_route = (root / "apps" / "api" / "tool_routes.py").read_text(encoding="utf-8")
    proxy = (root / "core" / "remote_runner" / "proxy.py").read_text(encoding="utf-8")
    runner_ops = (root / "core" / "app_runtime" / "runner_ops.py").read_text(encoding="utf-8")
    runner_tool_ops = (root / "core" / "app_runtime" / "runner_tool_ops.py").read_text(encoding="utf-8")
    frontend_api = (root / "apps" / "web" / "app" / "components" / "tools-page-api.ts").read_text(encoding="utf-8")
    frontend_state = (root / "apps" / "web" / "app" / "components" / "use-tools-page-state.ts").read_text(
        encoding="utf-8"
    )
    assert '@router.post("/api/v1/tools/prepare-jobs", status_code=202)' in remote_route
    assert '@router.post("/api/v1/tools/prepare-jobs", status_code=202)' in local_route
    assert "def create_tool_prepare_job" in proxy
    assert 'client.post_json("/api/v1/tools/prepare-jobs"' in proxy
    assert "RunnerToolOperationsMixin" in runner_ops
    assert "def create_tool_prepare_job" in runner_tool_ops
    assert '"/api/v1/tools/prepare-jobs"' in frontend_api
    assert '"/api/v1/tools"' in frontend_api
    assert "addToolDependency(nextTool)" in frontend_state
    assert "createToolPrepareJob(nextTool)" in frontend_state
