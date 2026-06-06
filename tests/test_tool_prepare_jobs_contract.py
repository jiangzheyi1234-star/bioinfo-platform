from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_prepare_uses_async_job_contract_across_api_layers() -> None:
    remote_route = (ROOT / "apps" / "remote_runner" / "tool_routes.py").read_text(encoding="utf-8")
    local_route = (ROOT / "apps" / "api" / "tool_routes.py").read_text(encoding="utf-8")
    proxy = (ROOT / "core" / "remote_runner" / "proxy.py").read_text(encoding="utf-8")
    runner_ops = (ROOT / "core" / "app_runtime" / "runner_ops.py").read_text(encoding="utf-8")
    runner_tool_ops = (ROOT / "core" / "app_runtime" / "runner_tool_ops.py").read_text(encoding="utf-8")
    frontend_api = (ROOT / "apps" / "web" / "app" / "components" / "tools-page-api.ts").read_text(encoding="utf-8")
    frontend_state = (ROOT / "apps" / "web" / "app" / "components" / "use-tools-page-state.ts").read_text(encoding="utf-8")
    task_context = (ROOT / "apps" / "web" / "app" / "components" / "tool-prepare-task-context.tsx").read_text(encoding="utf-8")
    task_bar = (ROOT / "apps" / "web" / "app" / "components" / "tool-prepare-task-bar.tsx").read_text(encoding="utf-8")
    storage_schema = (ROOT / "apps" / "remote_runner" / "storage_schema.py").read_text(encoding="utf-8")
    job_storage = (ROOT / "apps" / "remote_runner" / "tool_prepare_job_storage.py").read_text(encoding="utf-8")

    assert '@router.post("/api/v1/tools/prepare-jobs", status_code=202)' in remote_route
    assert '@router.get("/api/v1/tools/prepare-jobs")' in remote_route
    assert '@router.get("/api/v1/tools/prepare-jobs/{job_id}")' in remote_route
    assert '@router.post("/api/v1/tools/prepare-jobs/{job_id}/cancel")' in remote_route

    assert '@router.post("/api/v1/tools/prepare-jobs", status_code=202)' in local_route
    assert '@router.get("/api/v1/tools/prepare-jobs/{job_id}")' in local_route
    assert '@router.post("/api/v1/tools/prepare-jobs/{job_id}/cancel")' in local_route

    assert "def create_tool_prepare_job" in proxy
    assert 'client.post_json("/api/v1/tools/prepare-jobs"' in proxy
    assert "def list_latest_tool_prepare_jobs" in proxy
    assert 'client.get_json(f"/api/v1/tools/prepare-jobs?toolIds={tool_ids}"' in proxy
    assert "def get_tool_prepare_job" in proxy
    assert 'client.get_json(f"/api/v1/tools/prepare-jobs/{kwargs' in proxy
    assert "def cancel_tool_prepare_job" in proxy

    assert "RunnerToolOperationsMixin" in runner_ops
    assert "def create_tool_prepare_job" in runner_tool_ops
    assert "def list_latest_tool_prepare_jobs" in runner_tool_ops
    assert "def get_tool_prepare_job" in runner_tool_ops
    assert "def cancel_tool_prepare_job" in runner_tool_ops

    assert "createToolPrepareJob" in frontend_api
    assert "fetchToolPrepareJob" in frontend_api
    assert "cancelToolPrepareJob" in frontend_api
    assert '"/api/v1/tools/prepare-jobs"' in frontend_api
    assert "prepareToolDependency(nextTool)" not in frontend_state
    assert "if (shouldAutoPrepareOnAdd(nextTool))" in frontend_state
    assert "function shouldAutoPrepareOnAdd(tool: AddedTool)" in frontend_state
    assert 'tool.ruleSpecDraft?.source === "h2ometa-tool-profile"' in frontend_state
    assert "tool.ruleSpecDraft?.requiresUserCompletion === false" in frontend_state
    assert "missingRuleSpecFields(tool).length === 0" in frontend_state
    assert "createToolPrepareJob(nextTool)" in frontend_state
    assert "waitForToolPrepareJob(job.jobId)" not in frontend_state
    assert "trackToolPrepareJob(job)" in frontend_state
    assert "CREATE TABLE IF NOT EXISTS tool_prepare_job_events" in storage_schema
    assert "record_tool_prepare_job_event" in job_storage
    assert "def list_latest_tool_prepare_jobs_by_tool_id" in job_storage
    assert "latest_jobs_by_tool_id" in job_storage
    assert "fetchToolPrepareJob(jobId)" in task_context
    assert "cancelToolPrepareJob(jobId)" in task_context
    assert "ToolPrepareTaskBar" in task_bar
    assert "暂无日志" in task_bar
    assert "profile_schema_validation" in task_bar
    assert "static_rulespec_validation" in task_bar
    assert "environment_resolution" in task_bar
    assert "runtime_check" in task_bar
    assert "dry_run" in task_bar
    assert "smoke_run" in task_bar
    assert "output_validation" in task_bar


def test_prepare_job_service_schedules_only_new_prepare_jobs() -> None:
    service_source = (ROOT / "apps" / "remote_runner" / "tool_service.py").read_text(encoding="utf-8")
    storage_source = (ROOT / "apps" / "remote_runner" / "tool_prepare_job_storage.py").read_text(encoding="utf-8")

    assert 'job["reusedExisting"] = True' in storage_source
    assert 'job["reusedExisting"] = False' in storage_source
    assert 'if not job.get("reusedExisting"):' in service_source
    assert "background_tasks.add_task(run_tool_prepare_job, cfg, job[\"jobId\"])" in service_source


def test_prepare_task_status_lives_in_bottom_status_bar() -> None:
    shell = (ROOT / "apps" / "web" / "app" / "components" / "ssh-shell.tsx").read_text(encoding="utf-8")
    shell_ui = (ROOT / "apps" / "web" / "app" / "components" / "ssh-shell-ui.tsx").read_text(encoding="utf-8")
    task_bar = (ROOT / "apps" / "web" / "app" / "components" / "tool-prepare-task-bar.tsx").read_text(encoding="utf-8")

    assert 'import { ToolPrepareTaskBar } from "./tool-prepare-task-bar";' in shell_ui
    assert "<ToolPrepareTaskBar />" in shell_ui
    assert 'import { ToolPrepareTaskBar } from "./tool-prepare-task-bar";' not in shell
    assert "<ToolPrepareTaskBar />" not in shell
    assert "absolute bottom-3 right-3" not in task_bar
    assert "if (tasks.length === 0 || !latest) return null;" not in task_bar
    assert "w-56" in task_bar
    assert "w-[520px]" in task_bar
    assert "没有工具任务" in task_bar
    assert "aria-label=\"关闭任务面板\"" in task_bar
    assert "aria-label=\"取消工具验证任务\"" in task_bar
    assert "aria-label=\"移除工具验证任务\"" in task_bar


def test_terminal_prepare_job_refreshes_tool_cache_for_workflow_builder() -> None:
    frontend_state = (ROOT / "apps" / "web" / "app" / "components" / "use-tools-page-state.ts").read_text(encoding="utf-8")
    task_context = (ROOT / "apps" / "web" / "app" / "components" / "tool-prepare-task-context.tsx").read_text(encoding="utf-8")
    frontend_api = (ROOT / "apps" / "web" / "app" / "components" / "tools-page-api.ts").read_text(encoding="utf-8")

    assert "invalidateWorkflowToolCaches" in frontend_api
    assert "if (isTerminalJob(job))" in task_context
    assert "invalidateWorkflowToolCaches();" in task_context
    assert "lastPrepareRefreshRef" in frontend_state
    assert "isTerminalJob(task)" in frontend_state
    assert "loadAddedTools({ forceRefresh: true, silent: true })" in frontend_state


def test_waiting_resource_prepare_job_is_terminal_and_visible() -> None:
    job_storage = (ROOT / "apps" / "remote_runner" / "tool_prepare_job_storage.py").read_text(encoding="utf-8")
    task_context = (ROOT / "apps" / "web" / "app" / "components" / "tool-prepare-task-context.tsx").read_text(encoding="utf-8")
    task_bar = (ROOT / "apps" / "web" / "app" / "components" / "tool-prepare-task-bar.tsx").read_text(encoding="utf-8")
    frontend_state = (ROOT / "apps" / "web" / "app" / "components" / "use-tools-page-state.ts").read_text(encoding="utf-8")
    model = (ROOT / "apps" / "web" / "app" / "components" / "tools-page-model.ts").read_text(encoding="utf-8")

    assert '"waiting_resource"' in job_storage
    assert 'job.status === "waiting_resource"' in task_context
    assert 'status === "waiting_resource"' in task_bar
    assert "isTerminalJob(task)" in frontend_state
    assert "isActiveJob(task)" in frontend_state
    assert '"waiting_resource"' in model


def test_waiting_resource_database_details_are_visible_in_tools_ui() -> None:
    model = (ROOT / "apps" / "web" / "app" / "components" / "tools-page-model.ts").read_text(encoding="utf-8")
    state = (ROOT / "apps" / "web" / "app" / "components" / "use-tools-page-state.ts").read_text(encoding="utf-8")
    page = (ROOT / "apps" / "web" / "app" / "components" / "tools-page.tsx").read_text(encoding="utf-8")
    library = (ROOT / "apps" / "web" / "app" / "components" / "tools-page-library-section.tsx").read_text(encoding="utf-8")
    task_bar = (ROOT / "apps" / "web" / "app" / "components" / "tool-prepare-task-bar.tsx").read_text(encoding="utf-8")
    readiness = (ROOT / "apps" / "web" / "app" / "components" / "tool-rule-readiness.ts").read_text(encoding="utf-8")

    assert "export type MissingToolResource" in model
    assert "missingResources?: MissingToolResource[]" in model
    assert '"waiting_resource"' in model
    assert '"waiting-resource"' in readiness
    assert '"等待数据库"' in readiness

    assert "waitingResourceJobsByToolId" in state
    assert "waitingResourceJobsByToolId={state.waitingResourceJobsByToolId}" in page
    assert "waitingResourceJob?: ToolPrepareJob" in library
    assert "WaitingResourcePanel" in library
    assert "等待数据库" in library
    assert "绑定后可重试 prepare" in library
    assert "candidateCountLabel" in library

    assert "job.missingResources" in task_bar
    assert "WaitingResourceDetails" in task_bar
    assert "候选" in task_bar
