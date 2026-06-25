from __future__ import annotations

from pathlib import Path

import pytest

from core.app_runtime.errors import RuntimeConflictError, RuntimeServiceError
from core.app_runtime.runner_ops import RunnerOperationsMixin
from core.remote_runner.client import RemoteRunnerClientError
from core.remote_runner.manager import RemoteRunnerManagerError


ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_runtime_server_state_logic_lives_in_dedicated_mixin() -> None:
    service_source = _source("core/app_runtime/service.py")
    server_state_source = _source("core/app_runtime/server_state.py")

    assert "from core.app_runtime.server_state import RuntimeServerStateMixin" in service_source
    assert "RuntimeServerStateMixin" in service_source
    assert "class RuntimeServerStateMixin" in server_state_source
    assert "def _build_server_health(" in server_state_source
    assert "def _get_ssh_status_unlocked(" in server_state_source
    assert "def _build_server_health(" not in service_source
    assert "def _get_ssh_status_unlocked(" not in service_source


def test_runner_ensure_failure_classification_lives_outside_server_state() -> None:
    server_state_source = _source("core/app_runtime/server_state.py")
    health_path = ROOT / "core/app_runtime/server_health.py"

    assert health_path.exists()
    health_source = health_path.read_text(encoding="utf-8")
    assert len(server_state_source.splitlines()) <= 390
    assert "from core.app_runtime.server_health import (" in server_state_source
    assert "def _classify_runner_ensure_failure(" not in server_state_source
    assert "def _build_runner_ensure_failure_snapshot(" not in server_state_source
    assert "def classify_runner_ensure_failure(" in health_source
    assert "def build_runner_ensure_failure_snapshot(" in health_source
    assert "WORKFLOW_RUNTIME_MISSING" in health_source
    assert "PIPELINE_REGISTRY_NOT_READY" in health_source
    assert "SERVICE_RUNTIME_SETUP_FAILED" in health_source


def test_server_identity_and_payload_composition_live_outside_server_state() -> None:
    server_state_source = _source("core/app_runtime/server_state.py")
    payloads_path = ROOT / "core/app_runtime/server_payloads.py"

    assert payloads_path.exists()
    payloads_source = payloads_path.read_text(encoding="utf-8")

    assert len(server_state_source.splitlines()) <= 350
    assert "from core.app_runtime.server_payloads import (" in server_state_source
    for helper in (
        "_build_primary_server_identity",
        "_get_saved_readiness_snapshot",
        "_compose_server_payload",
        "_compose_runner_payload",
    ):
        assert f"def {helper}(" not in server_state_source

    for helper in (
        "build_primary_server_identity",
        "get_saved_readiness_snapshot",
        "compose_server_payload",
        "compose_runner_payload",
    ):
        assert f"def {helper}(" in payloads_source

    assert "uuid.uuid5(" in payloads_source
    assert "deploymentAction" in payloads_source
    assert "runnerVersion" in payloads_source


def test_server_state_config_access_does_not_depend_on_service_module() -> None:
    server_state_source = _source("core/app_runtime/server_state.py")
    ssh_connection_source = _source("core/app_runtime/ssh_connection.py")
    runtime_config_path = ROOT / "core/app_runtime/runtime_config.py"

    assert runtime_config_path.exists()
    runtime_config_source = runtime_config_path.read_text(encoding="utf-8")
    assert "from core.app_runtime import runtime_config" in server_state_source
    assert "from core.app_runtime import runtime_config" in ssh_connection_source
    assert "def get_runtime_config(" in runtime_config_source
    assert "def save_runtime_config(" in runtime_config_source
    assert "from core.app_runtime import service as service_module" not in server_state_source
    assert "service_module.get_config()" not in server_state_source
    assert "service_module.save_config(config)" not in server_state_source
    assert "from config import get_config" not in server_state_source
    assert "from config import get_config" not in ssh_connection_source


def test_runtime_config_merges_top_level_dict_patches_without_service_helper() -> None:
    from core.app_runtime.runtime_config import merge_runtime_config_patch

    result = merge_runtime_config_patch(
        {
            "ssh": {"host": "192.0.2.10", "port": 22},
            "servers": {"srv_test": {"runner_mode": "background_process"}},
        },
        {"ssh": {"user": "tester"}},
    )

    assert result == {
        "ssh": {"host": "192.0.2.10", "port": 22, "user": "tester"},
        "servers": {"srv_test": {"runner_mode": "background_process"}},
    }


def test_terminal_session_logic_lives_in_dedicated_mixin() -> None:
    service_source = _source("core/app_runtime/service.py")
    terminal_source = _source("core/app_runtime/terminal_sessions.py")

    assert "from core.app_runtime.terminal_sessions import RuntimeTerminalSessionMixin" in service_source
    assert "RuntimeTerminalSessionMixin" in service_source
    assert "class RuntimeTerminalSessionMixin" in terminal_source
    for method_name in (
        "create_terminal_session",
        "get_terminal_session",
        "send_terminal_input",
        "resize_terminal_session",
        "close_terminal_session",
        "_close_all_terminal_sessions",
    ):
        assert f"def {method_name}(" in terminal_source
        assert f"def {method_name}(" not in service_source


def test_ssh_connection_logic_lives_in_dedicated_mixin() -> None:
    service_source = _source("core/app_runtime/service.py")
    ssh_source = _source("core/app_runtime/ssh_connection.py")

    assert "from core.app_runtime.ssh_connection import RuntimeSshConnectionMixin" in service_source
    assert "RuntimeSshConnectionMixin" in service_source
    assert "class RuntimeSshConnectionMixin" in ssh_source
    for method_name in (
        "get_ssh_status",
        "connect_ssh",
        "_attempt_startup_auto_connect_in_background",
        "disconnect_ssh",
        "test_ssh_connection",
        "_ensure_ssh_connected",
        "_attempt_startup_auto_connect",
    ):
        assert f"def {method_name}(" in ssh_source
        assert f"def {method_name}(" not in service_source


def test_terminal_session_shutdown_does_not_swallow_close_errors() -> None:
    terminal_source = _source("core/app_runtime/terminal_sessions.py")

    close_sessions_source = terminal_source.split("def _close_all_terminal_sessions(", 1)[1]
    assert "except Exception" not in close_sessions_source
    assert "pass" not in close_sessions_source.split("self._terminal_sessions.clear()", 1)[0]


def test_remote_file_listing_does_not_wrap_ssh_list_directory_errors() -> None:
    file_ops_source = _source("core/app_runtime/runner_file_ops.py")

    list_files_source = file_ops_source.split("def list_remote_files(", 1)[1]
    assert "except Exception" not in list_files_source
    assert "failed to list remote files" not in list_files_source


def test_stop_remote_runner_service_does_not_wrap_ssh_run_errors() -> None:
    runner_ops_source = _source("core/app_runtime/runner_ops.py")
    runner_manager_source = _source("core/app_runtime/managers/runner.py")

    stop_source = runner_ops_source.split("def stop_remote_runner_service(", 1)[1]
    stop_source = stop_source.split("@staticmethod", 1)[0]
    assert "except Exception" not in stop_source
    assert "self.runner.stop_remote_runner_service()" in stop_source

    manager_stop_source = runner_manager_source.split("def stop_remote_runner_service(", 1)[1]
    assert "except Exception" not in manager_stop_source
    assert "ssh.run(command, timeout=30)" in manager_stop_source


def test_runner_operations_keep_stop_script_and_call_translation_in_helpers() -> None:
    runner_ops_source = _source("core/app_runtime/runner_ops.py")
    runner_manager_source = _source("core/app_runtime/managers/runner.py")
    stop_source = _source("core/app_runtime/remote_runner_stop.py")
    call_source = _source("core/app_runtime/remote_runner_call.py")

    assert len(runner_ops_source.splitlines()) <= 700
    assert "from core.app_runtime.managers.runner import RunnerManager" in _source("core/app_runtime/service.py")
    assert "self.runner = RunnerManager(self)" in _source("core/app_runtime/service.py")
    assert "from core.app_runtime.remote_runner_stop import STOP_REMOTE_RUNNER_COMMAND" in runner_manager_source
    assert "from core.app_runtime.remote_runner_call import call_remote_runner" in runner_ops_source
    assert "_STOP_REMOTE_RUNNER_COMMAND" not in runner_ops_source
    assert "REMOTE_STOP_SYSTEMD_OUTPUT" not in runner_ops_source
    assert "REMOTE_STOP_SCRIPT_OUTPUT" not in runner_ops_source
    assert "REMOTE_STOP_PROCESS_OUTPUT" not in runner_ops_source
    assert "RemoteRunnerClientError" not in runner_ops_source
    assert "RemoteRunnerConflictError" not in runner_ops_source
    assert "RemoteRunnerManagerError" not in runner_ops_source

    assert "STOP_REMOTE_RUNNER_COMMAND" in stop_source
    assert "class RunnerManager(BaseRuntimeManager)" in runner_manager_source
    assert "REMOTE_STOP_SYSTEMD_OUTPUT" in stop_source
    assert "def call_remote_runner(" in call_source
    assert "except RemoteRunnerConflictError as exc:" in call_source
    assert "except RemoteRunnerClientError as exc:" in call_source
    assert "except RemoteRunnerManagerError as exc:" in call_source


def test_runtime_database_operations_live_in_dedicated_mixin() -> None:
    runner_ops_source = _source("core/app_runtime/runner_ops.py")
    database_ops_source = _source("core/app_runtime/runner_database_ops.py")

    assert "from core.app_runtime.runner_database_ops import RunnerDatabaseOperationsMixin" in runner_ops_source
    assert "RunnerDatabaseOperationsMixin" in runner_ops_source
    assert "class RunnerDatabaseOperationsMixin" in database_ops_source
    for method_name in (
        "list_databases",
        "list_database_templates",
        "list_database_packs",
        "add_database",
        "delete_database",
        "update_database",
        "check_database",
    ):
        assert f"def {method_name}(" in database_ops_source
        assert f"def {method_name}(" not in runner_ops_source


def test_runtime_database_operations_delegate_to_database_manager() -> None:
    service_source = _source("core/app_runtime/service.py")
    database_ops_source = _source("core/app_runtime/runner_database_ops.py")
    database_manager_path = ROOT / "core/app_runtime/managers/database.py"

    assert database_manager_path.exists()

    database_manager_source = database_manager_path.read_text(encoding="utf-8")

    assert "from core.app_runtime.managers.database import DatabaseManager" in service_source
    assert "self.databases = DatabaseManager(self)" in service_source
    assert "class DatabaseManager(BaseRuntimeManager)" in database_manager_source
    assert "self._call_remote_runner(" not in database_ops_source
    assert "self._require_existing_runner_ready(" not in database_ops_source
    assert "self.databases.list_database_packs(" in database_ops_source
    assert "self.databases.add_database(" in database_ops_source


def test_runtime_tool_operations_live_in_dedicated_mixin() -> None:
    runner_ops_source = _source("core/app_runtime/runner_ops.py")
    tool_ops_source = _source("core/app_runtime/runner_tool_ops.py")

    assert "from core.app_runtime.runner_tool_ops import RunnerToolOperationsMixin" in runner_ops_source
    assert "RunnerToolOperationsMixin" in runner_ops_source
    assert "class RunnerToolOperationsMixin" in tool_ops_source
    for method_name in (
        "list_tools",
        "list_tool_index",
        "add_tool",
        "create_tool_prepare_job",
        "list_latest_tool_prepare_jobs",
        "get_tool_prepare_job",
        "cancel_tool_prepare_job",
        "update_tool_rule_template",
        "delete_tool",
        "mark_tool_production_enabled",
    ):
        assert f"def {method_name}(" in tool_ops_source
        assert f"def {method_name}(" not in runner_ops_source


def test_runtime_tool_operations_delegate_to_tool_manager() -> None:
    service_source = _source("core/app_runtime/service.py")
    tool_ops_source = _source("core/app_runtime/runner_tool_ops.py")
    base_manager_path = ROOT / "core/app_runtime/managers/base.py"
    tool_manager_path = ROOT / "core/app_runtime/managers/tool.py"

    assert base_manager_path.exists()
    assert tool_manager_path.exists()

    base_manager_source = base_manager_path.read_text(encoding="utf-8")
    tool_manager_source = tool_manager_path.read_text(encoding="utf-8")

    assert "from core.app_runtime.managers.tool import ToolManager" in service_source
    assert "self.tools = ToolManager(self)" in service_source
    assert "class BaseRuntimeManager" in base_manager_source
    assert "def call_existing_runner(" in base_manager_source
    assert "def _existing_runner_context(" in base_manager_source
    assert "class ToolManager(BaseRuntimeManager)" in tool_manager_source
    assert "self._service._call_remote_runner(" in base_manager_source
    assert "self._service._require_existing_runner_ready(" in base_manager_source
    assert "self._call_remote_runner(" not in tool_ops_source
    assert "self._require_existing_runner_ready(" not in tool_ops_source
    assert "self.tools.create_tool_prepare_job(" in tool_ops_source
    assert "self.tools.list_tool_index(" in tool_ops_source
    assert "self.tools.list_latest_tool_prepare_jobs(" in tool_ops_source


def test_runtime_workflow_design_operations_live_in_dedicated_mixin() -> None:
    runner_ops_source = _source("core/app_runtime/runner_ops.py")
    workflow_ops_source = _source("core/app_runtime/runner_workflow_design_ops.py")

    assert "from core.app_runtime.runner_workflow_design_ops import RunnerWorkflowDesignOperationsMixin" in runner_ops_source
    assert "RunnerWorkflowDesignOperationsMixin" in runner_ops_source
    assert "class RunnerWorkflowDesignOperationsMixin" in workflow_ops_source
    for method_name in (
        "list_workflow_design_drafts",
        "create_workflow_design_draft",
        "get_workflow_design_draft",
        "update_workflow_design_draft",
        "fork_workflow_design_draft",
        "delete_workflow_design_draft",
        "plan_workflow_design_draft",
        "compile_workflow_design_draft",
    ):
        assert f"def {method_name}(" in workflow_ops_source
        assert f"def {method_name}(" not in runner_ops_source


def test_runtime_workflow_design_operations_delegate_to_workflow_manager() -> None:
    service_source = _source("core/app_runtime/service.py")
    workflow_ops_source = _source("core/app_runtime/runner_workflow_design_ops.py")
    workflow_manager_path = ROOT / "core/app_runtime/managers/workflow.py"

    assert workflow_manager_path.exists()

    workflow_manager_source = workflow_manager_path.read_text(encoding="utf-8")

    assert "from core.app_runtime.managers.workflow import WorkflowManager" in service_source
    assert "self.workflows = WorkflowManager(self)" in service_source
    assert "class WorkflowManager(BaseRuntimeManager)" in workflow_manager_source
    assert "WORKFLOW_DESIGN_PLAN_UNSUPPORTED_FIELD" in workflow_manager_source
    assert "WORKFLOW_DESIGN_COMPILE_UNSUPPORTED_FIELD" in workflow_manager_source
    assert "self._call_remote_runner(" not in workflow_ops_source
    assert "self._require_existing_runner_ready(" not in workflow_ops_source
    assert "self.workflows.compile_workflow_design_draft(" in workflow_ops_source


def test_runtime_execution_operations_live_in_dedicated_mixin() -> None:
    runner_ops_source = _source("core/app_runtime/runner_ops.py")
    execution_ops_source = _source("core/app_runtime/runner_execution_ops.py")

    assert "from core.app_runtime.runner_execution_ops import RunnerExecutionOperationsMixin" in runner_ops_source
    assert "RunnerExecutionOperationsMixin" in runner_ops_source
    assert "class RunnerExecutionOperationsMixin" in execution_ops_source
    for method_name in (
        "list_runs",
        "submit_run",
        "list_workflow_triggers",
        "create_workflow_trigger",
        "submit_workflow_trigger_event",
        "submit_workflow_trigger_inbox_event",
        "replay_workflow_trigger_inbox_event",
        "submit_workflow_trigger_readiness_event",
        "launch_workflow_trigger_backfill",
        "preview_workflow_trigger_backfill",
        "list_workflow_trigger_events",
        "get_workflow_trigger_readiness_observation",
        "list_workflow_trigger_inbox_events",
        "list_workflow_backfill_launches",
        "get_workflow_backfill_launch",
        "cancel_workflow_backfill_launch",
        "get_run",
        "retry_run",
        "apply_rule_output_invalidation",
        "prepare_rule_cache_restore_staged_files",
        "apply_rule_cache_restore_staged_files",
        "prepare_rule_cache_restore_final_outputs",
        "apply_rule_cache_restore_final_outputs",
        "prepare_rule_cache_restore_adoption",
        "apply_rule_cache_restore_adoption",
        "get_run_events",
        "get_run_execution_context",
        "get_run_attempts",
        "get_run_logs",
        "get_run_results",
        "get_run_rules",
        "list_results",
        "get_result",
        "get_result_preview",
        "get_result_audit",
        "export_result_package",
        "list_result_package_exports",
        "download_result_package",
        "retire_result_package",
        "delete_result_package_bytes",
    ):
        assert f"def {method_name}(" in execution_ops_source
        assert f"def {method_name}(" not in runner_ops_source


def test_runtime_execution_operations_delegate_to_execution_manager() -> None:
    service_source = _source("core/app_runtime/service.py")
    execution_ops_source = _source("core/app_runtime/runner_execution_ops.py")
    base_manager_source = _source("core/app_runtime/managers/base.py")
    execution_manager_path = ROOT / "core/app_runtime/managers/execution.py"

    assert execution_manager_path.exists()

    execution_manager_source = execution_manager_path.read_text(encoding="utf-8")

    assert "from core.app_runtime.managers.execution import ExecutionManager" in service_source
    assert "self.execution = ExecutionManager(self)" in service_source
    assert "class ExecutionManager(BaseRuntimeManager)" in execution_manager_source
    assert "def _runner_context(" in base_manager_source
    assert "def call_runner(" in base_manager_source
    assert "serverId is required" in execution_manager_source
    assert "pipelineId is required" in execution_manager_source
    assert "self._call_remote_runner(" not in execution_ops_source
    assert "self._require_runner_ready(" not in execution_ops_source
    assert "self.execution.submit_run(" in execution_ops_source
    assert "self.execution.create_workflow_trigger(" in execution_ops_source
    assert "self.execution.submit_workflow_trigger_inbox_event(" in execution_ops_source
    assert "self.execution.replay_workflow_trigger_inbox_event(" in execution_ops_source
    assert "self.execution.submit_workflow_trigger_readiness_event(" in execution_ops_source
    assert "self.execution.launch_workflow_trigger_backfill(" in execution_ops_source
    assert "self.execution.preview_workflow_trigger_backfill(" in execution_ops_source
    assert "self.execution.cancel_workflow_backfill_launch(" in execution_ops_source
    assert "self.execution.list_workflow_backfill_launches(" in execution_ops_source
    assert "self.execution.list_workflow_trigger_inbox_events(" in execution_ops_source
    assert "self.execution.get_workflow_trigger_readiness_observation(" in execution_ops_source
    assert "self.execution.get_workflow_backfill_launch(" in execution_ops_source
    assert "self.execution.retry_run(" in execution_ops_source
    assert "self.execution.retry_run_rules(" in execution_ops_source
    assert "self.execution.apply_rule_output_invalidation(" in execution_ops_source
    assert "self.execution.prepare_rule_cache_restore_staged_files(" in execution_ops_source
    assert "self.execution.apply_rule_cache_restore_staged_files(" in execution_ops_source
    assert "self.execution.prepare_rule_cache_restore_final_outputs(" in execution_ops_source
    assert "self.execution.apply_rule_cache_restore_final_outputs(" in execution_ops_source
    assert "self.execution.prepare_rule_cache_restore_adoption(" in execution_ops_source
    assert "self.execution.apply_rule_cache_restore_adoption(" in execution_ops_source
    assert "self.execution.resume_run(" in execution_ops_source
    assert "self.execution.get_run_execution_context(" in execution_ops_source
    assert "self.execution.get_run_attempts(" in execution_ops_source
    assert "manager.submit_workflow_trigger_event" in execution_manager_source
    assert "manager.submit_workflow_trigger_inbox_event" in execution_manager_source
    assert "manager.replay_workflow_trigger_inbox_event" in execution_manager_source
    assert "manager.submit_workflow_trigger_readiness_event" in execution_manager_source
    assert "manager.launch_workflow_trigger_backfill" in execution_manager_source
    assert "manager.preview_workflow_trigger_backfill" in execution_manager_source
    assert "manager.cancel_workflow_backfill_launch" in execution_manager_source
    assert 'self.call_runner(\n                "list_workflow_backfill_launches",' in execution_manager_source
    assert 'self.call_runner(\n                "list_workflow_trigger_inbox_events",' in execution_manager_source
    assert 'self.call_runner(\n                "get_workflow_trigger_readiness_observation",' in execution_manager_source
    assert 'self.call_runner(\n                "get_workflow_backfill_launch",' in execution_manager_source
    assert "self.execution.get_result_audit(" in execution_ops_source
    assert "self.execution.export_result_package(" in execution_ops_source
    assert "self.execution.list_result_package_exports(" in execution_ops_source
    assert "self.execution.download_result_package(" in execution_ops_source
    assert "self.execution.retire_result_package(" in execution_ops_source
    assert "self.execution.delete_result_package_bytes(" in execution_ops_source
    assert "self.call_runner(\"get_run_execution_context\"" in execution_manager_source
    assert "self.call_runner(\"get_run_attempts\"" in execution_manager_source
    assert "self.call_runner(\"retry_run\"" in execution_manager_source
    assert "self.call_runner(\"retry_run_rules\"" in execution_manager_source
    assert "self.call_runner(\n                \"apply_rule_output_invalidation\"," in execution_manager_source
    assert "self.call_runner(\n                \"prepare_rule_cache_restore_staged_files\"," in execution_manager_source
    assert "self.call_runner(\n                \"apply_rule_cache_restore_staged_files\"," in execution_manager_source
    assert "self.call_runner(\n                \"prepare_rule_cache_restore_final_outputs\"," in execution_manager_source
    assert "self.call_runner(\n                \"apply_rule_cache_restore_final_outputs\"," in execution_manager_source
    assert "self.call_runner(\n                \"prepare_rule_cache_restore_adoption\"," in execution_manager_source
    assert "self.call_runner(\n                \"apply_rule_cache_restore_adoption\"," in execution_manager_source
    assert "self.call_runner(\"resume_run\"" in execution_manager_source
    assert "self.call_runner(\"get_result_audit\"" in execution_manager_source
    assert 'self.call_runner(\n                "export_result_package",' in execution_manager_source
    assert 'self.call_runner(\n                "list_result_package_exports",' in execution_manager_source
    assert 'self.call_runner(\n            "download_result_package",' in execution_manager_source
    assert 'self.call_runner(\n            "retire_result_package",' in execution_manager_source
    assert 'self.call_runner(\n            "delete_result_package_bytes",' in execution_manager_source
    assert "preferred_server_id=server_id" in execution_manager_source


def test_runtime_file_operations_live_in_dedicated_mixin() -> None:
    runner_ops_source = _source("core/app_runtime/runner_ops.py")
    file_ops_source = _source("core/app_runtime/runner_file_ops.py")

    assert "from core.app_runtime.runner_file_ops import RunnerFileOperationsMixin" in runner_ops_source
    assert "RunnerFileOperationsMixin" in runner_ops_source
    assert "class RunnerFileOperationsMixin" in file_ops_source
    for method_name in ("upload_file", "list_remote_files"):
        assert f"def {method_name}(" in file_ops_source
        assert f"def {method_name}(" not in runner_ops_source


def test_runtime_file_operations_delegate_to_file_manager() -> None:
    service_source = _source("core/app_runtime/service.py")
    file_ops_source = _source("core/app_runtime/runner_file_ops.py")
    file_manager_path = ROOT / "core/app_runtime/managers/file.py"

    assert file_manager_path.exists()

    file_manager_source = file_manager_path.read_text(encoding="utf-8")

    assert "from core.app_runtime.managers.file import FileManager" in service_source
    assert "self.files = FileManager(self)" in service_source
    assert "class FileManager(BaseRuntimeManager)" in file_manager_source
    assert 'self.call_runner(\n            "upload_content"' in file_manager_source
    assert "ssh.list_directory(" in file_manager_source
    assert "self._call_remote_runner(" not in file_ops_source
    assert "self._require_runner_ready(" not in file_ops_source
    assert "self._ensure_ssh_connected(" not in file_ops_source
    assert "self.files.upload_file(" in file_ops_source


def test_remote_listening_ports_does_not_wrap_ssh_run_errors() -> None:
    service_source = _source("core/app_runtime/service.py")

    ports_source = service_source.split("def list_remote_listening_ports(", 1)[1]
    ports_source = ports_source.split("def ensure_remote_runner_ready(", 1)[0]
    assert "except Exception" not in ports_source
    assert "failed to list remote listening ports" not in ports_source
    assert "ssh.run(command, timeout=15)" in ports_source


def test_runner_ready_health_check_errors_are_not_swallowed() -> None:
    server_state_source = _source("core/app_runtime/server_state.py")

    ready_source = server_state_source.split("def _require_runner_ready(", 1)[1]
    ready_source = ready_source.split("def _build_server_health(", 1)[0]
    assert "self._call_remote_runner(" in ready_source
    assert "except RuntimeServiceError" not in ready_source
    assert "pass" not in ready_source


def test_remote_database_candidate_errors_become_runtime_conflicts() -> None:
    from core.remote_runner.client import RemoteRunnerConflictError

    def fail_with_candidates(**_kwargs):
        raise RemoteRunnerConflictError({"items": [{"id": "db_candidate"}]})

    with pytest.raises(RuntimeConflictError) as raised:
        RunnerOperationsMixin._call_remote_runner(fail_with_candidates)

    assert raised.value.payload == {"items": [{"id": "db_candidate"}]}
    assert raised.value.status_code == 409


def test_remote_runner_http_status_survives_runtime_service_boundary() -> None:
    def fail_with_remote_http_status(**_kwargs):
        raise RemoteRunnerClientError(
            "runner http error 409: TOOL_PRODUCTION_REQUIRES_WORKFLOW_READY",
            status_code=409,
            detail="TOOL_PRODUCTION_REQUIRES_WORKFLOW_READY",
        )

    with pytest.raises(RuntimeServiceError) as raised:
        RunnerOperationsMixin._call_remote_runner(fail_with_remote_http_status)

    assert raised.value.status_code == 409
    assert raised.value.detail == "TOOL_PRODUCTION_REQUIRES_WORKFLOW_READY"


def test_remote_runner_manager_http_status_survives_runtime_service_boundary() -> None:
    def fail_with_manager_http_status(**_kwargs):
        raise RemoteRunnerManagerError(
            "runner http error 422: DATABASE_PATH_REQUIRED",
            status_code=422,
            detail="DATABASE_PATH_REQUIRED",
        )

    with pytest.raises(RuntimeServiceError) as raised:
        RunnerOperationsMixin._call_remote_runner(fail_with_manager_http_status)

    assert raised.value.status_code == 422
    assert raised.value.detail == "DATABASE_PATH_REQUIRED"
