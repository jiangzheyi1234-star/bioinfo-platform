from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_prepare_uses_async_job_contract_across_api_layers() -> None:
    remote_route = (ROOT / "apps" / "remote_runner" / "tool_routes.py").read_text(encoding="utf-8")
    local_main = (ROOT / "apps" / "api" / "main.py").read_text(encoding="utf-8")
    proxy = (ROOT / "core" / "remote_runner" / "proxy.py").read_text(encoding="utf-8")
    runner_ops = (ROOT / "core" / "app_runtime" / "runner_ops.py").read_text(encoding="utf-8")
    frontend_api = (ROOT / "apps" / "web" / "app" / "components" / "tools-page-api.ts").read_text(encoding="utf-8")
    frontend_state = (ROOT / "apps" / "web" / "app" / "components" / "use-tools-page-state.ts").read_text(encoding="utf-8")
    task_context = (ROOT / "apps" / "web" / "app" / "components" / "tool-prepare-task-context.tsx").read_text(encoding="utf-8")
    task_bar = (ROOT / "apps" / "web" / "app" / "components" / "tool-prepare-task-bar.tsx").read_text(encoding="utf-8")
    storage_schema = (ROOT / "apps" / "remote_runner" / "storage_schema.py").read_text(encoding="utf-8")
    job_storage = (ROOT / "apps" / "remote_runner" / "tool_prepare_job_storage.py").read_text(encoding="utf-8")

    assert '@router.post("/api/v1/tools/prepare-jobs", status_code=202)' in remote_route
    assert '@router.get("/api/v1/tools/prepare-jobs/{job_id}")' in remote_route
    assert '@router.post("/api/v1/tools/prepare-jobs/{job_id}/cancel")' in remote_route

    assert '@app.post("/api/v1/tools/prepare-jobs", status_code=202)' in local_main
    assert '@app.get("/api/v1/tools/prepare-jobs/{job_id}")' in local_main
    assert '@app.post("/api/v1/tools/prepare-jobs/{job_id}/cancel")' in local_main

    assert "def create_tool_prepare_job" in proxy
    assert 'client.post_json("/api/v1/tools/prepare-jobs"' in proxy
    assert "def get_tool_prepare_job" in proxy
    assert 'client.get_json(f"/api/v1/tools/prepare-jobs/{kwargs' in proxy
    assert "def cancel_tool_prepare_job" in proxy

    assert "def create_tool_prepare_job" in runner_ops
    assert "def get_tool_prepare_job" in runner_ops
    assert "def cancel_tool_prepare_job" in runner_ops

    assert "createToolPrepareJob" in frontend_api
    assert "fetchToolPrepareJob" in frontend_api
    assert "cancelToolPrepareJob" in frontend_api
    assert '"/api/v1/tools/prepare-jobs"' in frontend_api
    assert "prepareToolDependency(nextTool)" not in frontend_state
    assert "createToolPrepareJob(nextTool)" in frontend_state
    assert "waitForToolPrepareJob(job.jobId)" not in frontend_state
    assert "trackToolPrepareJob(job)" in frontend_state
    assert "CREATE TABLE IF NOT EXISTS tool_prepare_job_events" in storage_schema
    assert "record_tool_prepare_job_event" in job_storage
    assert "fetchToolPrepareJob(jobId)" in task_context
    assert "cancelToolPrepareJob(jobId)" in task_context
    assert "ToolPrepareTaskBar" in task_bar
    assert "暂无日志" in task_bar
