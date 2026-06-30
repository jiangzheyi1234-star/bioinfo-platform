from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REMOTE_RUNNER = ROOT / "apps" / "remote_runner"


def test_storage_schema_lives_outside_storage_module() -> None:
    schema = (REMOTE_RUNNER / "storage_schema.py").read_text(encoding="utf-8")
    storage = (REMOTE_RUNNER / "storage.py").read_text(encoding="utf-8")
    storage_core = (REMOTE_RUNNER / "storage_core.py").read_text(encoding="utf-8")
    sqlite_migrations = (REMOTE_RUNNER / "sqlite_migrations.py").read_text(encoding="utf-8")

    assert "SCHEMA_SQL" in schema
    assert "CREATE TABLE IF NOT EXISTS runs" in schema
    assert "from .storage_schema import SCHEMA_SQL" in sqlite_migrations
    assert "PRAGMA user_version" in sqlite_migrations
    assert "schema_migrations" in sqlite_migrations
    assert "configure_runtime_connection" in storage_core
    assert "ensure_runtime_schema_current" in storage_core
    assert "ensure_runtime_layout(cfg)" not in storage_core
    assert "from .storage_core import (" in storage
    assert "get_connection," in storage
    assert "now_iso," in storage
    assert 'SCHEMA_SQL = """' not in storage
    assert "ALTER TABLE" not in storage_core


def test_remote_runner_startup_runs_explicit_schema_migration_before_listening() -> None:
    run_source = (REMOTE_RUNNER / "run.py").read_text(encoding="utf-8")

    assert "from .config import ensure_runtime_layout" in run_source
    assert "ensure_runtime_layout(cfg)" in run_source
    assert run_source.index("ensure_runtime_layout(cfg)") < run_source.index("socket.socket(")


def test_tool_storage_lives_outside_general_storage_module() -> None:
    storage = (REMOTE_RUNNER / "storage.py").read_text(encoding="utf-8")
    tool_storage = (REMOTE_RUNNER / "tool_storage.py").read_text(encoding="utf-8")
    storage_core = (REMOTE_RUNNER / "storage_core.py").read_text(encoding="utf-8")

    assert len(storage.splitlines()) <= 620
    assert "def get_connection(" not in storage
    assert "def now_iso(" not in storage
    assert "from .tool_storage import (" in storage
    assert "def _tool_row_to_dict(" not in storage
    assert "def list_tools(" not in storage
    assert "def fetch_tool(" not in storage
    assert "def upsert_tool(" not in storage
    assert "def delete_tool(" not in storage
    assert "from .tool_contract import" not in storage

    assert "def _tool_row_to_dict(" in tool_storage
    assert "def list_tools(" in tool_storage
    assert "def fetch_tool(" in tool_storage
    assert "def upsert_tool(" in tool_storage
    assert "def delete_tool(" in tool_storage
    assert "from .tool_platform_storage import delete_tool_index, upsert_tool_index" in tool_storage
    assert "from .tool_contract import build_tool_contract, default_contract_status, normalize_contract_status" in tool_storage
    assert "from .storage import get_connection, now_iso" not in tool_storage
    assert "from .storage_core import get_connection, now_iso" in tool_storage

    assert "def get_connection(" in storage_core
    assert "def now_iso(" in storage_core
    assert "def _ensure_tools_columns(" in (REMOTE_RUNNER / "sqlite_migrations.py").read_text(encoding="utf-8")


def test_tool_platform_storage_lives_outside_tool_storage_module() -> None:
    tool_storage = (REMOTE_RUNNER / "tool_storage.py").read_text(encoding="utf-8")
    platform_storage_path = REMOTE_RUNNER / "tool_platform_storage.py"

    assert platform_storage_path.exists()
    platform_storage = platform_storage_path.read_text(encoding="utf-8")
    assert "def search_tool_index(" in platform_storage
    assert "def record_prepare_job_validation_result(" in platform_storage
    assert "def list_tool_validation_results(" in platform_storage
    assert "CREATE TABLE IF NOT EXISTS tool_index" in (REMOTE_RUNNER / "storage_schema.py").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS tool_validation_results" in (
        REMOTE_RUNNER / "storage_schema.py"
    ).read_text(encoding="utf-8")
    assert "def search_tool_index(" not in tool_storage
    assert "def record_prepare_job_validation_result(" not in tool_storage


def test_run_query_storage_lives_outside_general_storage_module() -> None:
    storage = (REMOTE_RUNNER / "storage.py").read_text(encoding="utf-8")
    run_query_path = REMOTE_RUNNER / "execution_query_storage.py"

    assert run_query_path.exists()
    run_query_storage = run_query_path.read_text(encoding="utf-8")

    assert len(storage.splitlines()) <= 430
    assert "from .execution_query_storage import (" in storage
    assert "def fetch_run(" not in storage
    assert "def require_run(" not in storage
    assert "def list_runs(" not in storage
    assert "def fetch_run_events(" not in storage
    assert "def fetch_run_results(" not in storage
    assert "def list_results(" not in storage
    assert "def fetch_result(" not in storage

    assert "def fetch_run(" in run_query_storage
    assert "def require_run(" in run_query_storage
    assert "def list_runs(" in run_query_storage
    assert "def fetch_run_events(" in run_query_storage
    assert "def fetch_run_results(" in run_query_storage
    assert "def list_results(" in run_query_storage
    assert "def fetch_result(" in run_query_storage
    assert "from .storage_core import get_connection" in run_query_storage
    assert "from .storage import" not in run_query_storage


def test_general_storage_module_is_import_facade_for_runtime_storage_domains() -> None:
    storage = (REMOTE_RUNNER / "storage.py").read_text(encoding="utf-8")
    upload_storage = (REMOTE_RUNNER / "upload_storage.py").read_text(encoding="utf-8")
    workflow_run_storage = (REMOTE_RUNNER / "workflow_run_storage.py").read_text(encoding="utf-8")
    log_storage = (REMOTE_RUNNER / "log_storage.py").read_text(encoding="utf-8")
    artifact_storage = (REMOTE_RUNNER / "artifact_storage.py").read_text(encoding="utf-8")

    assert len(storage.splitlines()) <= 100
    for import_name in (
        "from .upload_storage import (",
        "from .workflow_run_storage import (",
        "from .log_storage import (",
        "from .artifact_storage import (",
    ):
        assert import_name in storage
    for implementation_marker in (
        "def canonical_payload_hash(",
        "def persist_upload(",
        "def fetch_upload(",
        "def _estimate_base64_size(",
        "def create_run_record(",
        "def update_run_state(",
        "def append_log_lines(",
        "def fetch_log_lines(",
        "def persist_artifact(",
        "def _artifact_payload_stats(",
        "import base64",
        "import binascii",
        "import hashlib",
        "import json",
        "import uuid",
    ):
        assert implementation_marker not in storage

    assert "def persist_upload(" in upload_storage
    assert "def fetch_upload(" in upload_storage
    assert "def canonical_payload_hash(" in workflow_run_storage
    assert "def create_run_record(" in workflow_run_storage
    assert "def update_run_state(" in workflow_run_storage
    assert "def append_log_lines(" in log_storage
    assert "def fetch_log_lines(" in log_storage
    assert "def persist_artifact(" in artifact_storage


def test_run_execution_state_machine_owns_core_status_decisions() -> None:
    state_machine_path = REMOTE_RUNNER / "run_execution_state_machine.py"
    run_execution_storage = (REMOTE_RUNNER / "run_execution_storage.py").read_text(encoding="utf-8")
    workflow_run_storage = (REMOTE_RUNNER / "workflow_run_storage.py").read_text(encoding="utf-8")
    execution_retry_storage = (REMOTE_RUNNER / "execution_retry_storage.py").read_text(encoding="utf-8")
    reconciler_actions = (REMOTE_RUNNER / "reconciler_actions.py").read_text(encoding="utf-8")
    run_worker = (REMOTE_RUNNER / "run_worker.py").read_text(encoding="utf-8")

    assert state_machine_path.exists()
    state_machine = state_machine_path.read_text(encoding="utf-8")

    assert "class RunExecutionStateMachine" in state_machine
    assert "class RunAttemptFenceDecision" in state_machine
    assert "def fence_attempt(" in state_machine
    assert "TERMINAL_RUN_STATUSES =" in state_machine
    assert "RETRYABLE_RUN_STATUSES =" in state_machine
    assert "RELEASED_LEASE_STATES =" in state_machine
    assert "from .run_execution_state_machine import RunExecutionStateMachine" in run_execution_storage
    assert "from .run_execution_state_machine import RunExecutionStateMachine" in workflow_run_storage
    assert "from .run_execution_state_machine import RunExecutionStateMachine" in execution_retry_storage
    assert "from .run_execution_state_machine import RunExecutionStateMachine" in reconciler_actions
    assert "from .run_execution_state_machine import RunExecutionStateMachine" in run_worker

    assert "TERMINAL_RUN_STATUSES =" not in run_execution_storage
    assert "RELEASED_LEASE_STATES =" not in run_execution_storage
    assert "RETRYABLE_RUN_STATUSES =" not in execution_retry_storage
    assert "def _terminal_job_state_for_attempt_state(" not in run_execution_storage
    assert "def _attempt_state_for_run_status(" not in run_worker
    assert "RunExecutionStateMachine.fence_attempt(" in run_execution_storage
    assert "RunExecutionStateMachine.fence_attempt(" in reconciler_actions
    assert '"expired" if reason == "lease_expired" else "fenced"' not in run_execution_storage
    assert '"expired" if reason == "lease_expired" else "fenced"' not in reconciler_actions
    assert 'event_type="run_attempt_fenced"' not in run_execution_storage
    assert 'event_type="run_attempt_fenced"' not in reconciler_actions
    assert "Run attempt fenced" not in run_execution_storage
    assert "Run attempt fenced" not in reconciler_actions
    assert '("fenced", reason' not in run_execution_storage
    assert '("fenced", reason' not in reconciler_actions


def test_workflow_backfill_state_machine_owns_backfill_status_decisions() -> None:
    state_machine_path = REMOTE_RUNNER / "workflow_backfill_state_machine.py"
    backfill_storage = (REMOTE_RUNNER / "workflow_backfill_storage.py").read_text(encoding="utf-8")
    backfill_controller = (REMOTE_RUNNER / "workflow_backfill_controller.py").read_text(encoding="utf-8")
    trigger_service = (REMOTE_RUNNER / "trigger_service.py").read_text(encoding="utf-8")
    trigger_storage = (REMOTE_RUNNER / "trigger_storage.py").read_text(encoding="utf-8")

    assert state_machine_path.exists()
    state_machine = state_machine_path.read_text(encoding="utf-8")

    assert len(backfill_storage.splitlines()) <= 800
    assert "class WorkflowBackfillStateMachine" in state_machine
    assert "RunExecutionStateMachine" in state_machine
    assert "from .workflow_backfill_state_machine import WorkflowBackfillStateMachine" in backfill_storage
    assert "from .workflow_backfill_state_machine import WorkflowBackfillStateMachine" in backfill_controller
    assert "from .workflow_backfill_state_machine import WorkflowBackfillStateMachine" in trigger_service
    assert "from .run_execution_state_machine import TERMINAL_RUN_STATUSES" in trigger_storage

    assert "BACKFILL_RUN_ORDERS =" not in backfill_storage
    assert "ADVANCEABLE_LAUNCH_STATES =" not in backfill_storage
    assert "BACKFILL_PARTITION_CANCELABLE_STATES =" not in backfill_storage
    assert "def _partition_has_active_run(" not in backfill_storage
    assert "def _partition_has_cancellable_run(" not in backfill_storage
    assert "def _backfill_run_order(" not in backfill_storage
    assert "BACKFILL_CANCEL_SKIP_STATUSES =" not in trigger_service
    assert "TRIGGER_ACTIVE_RUN_TERMINAL_STATUSES =" not in trigger_storage


def test_run_execution_state_machine_owns_shared_run_status_sets() -> None:
    artifact_lifecycle_storage = (REMOTE_RUNNER / "artifact_lifecycle_storage.py").read_text(encoding="utf-8")
    artifact_lifecycle_service = (REMOTE_RUNNER / "artifact_lifecycle_service.py").read_text(encoding="utf-8")
    execution_resume_plan = (REMOTE_RUNNER / "execution_resume_plan.py").read_text(encoding="utf-8")
    run_execution_context_storage = (REMOTE_RUNNER / "run_execution_context_storage.py").read_text(encoding="utf-8")
    rule_partial_rerun_lifecycle = (REMOTE_RUNNER / "rule_partial_rerun_lifecycle.py").read_text(encoding="utf-8")
    backfill_reprocessing = (REMOTE_RUNNER / "workflow_backfill_reprocessing.py").read_text(encoding="utf-8")

    assert "from .run_execution_state_machine import TERMINAL_RUN_STATUSES" in artifact_lifecycle_storage
    assert "from .run_execution_state_machine import TERMINAL_RUN_STATUSES" in artifact_lifecycle_service
    assert "from .run_execution_state_machine import RETRYABLE_RUN_STATUSES, TERMINAL_RUN_STATUSES" in (
        execution_resume_plan
    )
    assert "from .run_execution_state_machine import RETRYABLE_RUN_STATUSES, TERMINAL_RUN_STATUSES" in (
        run_execution_context_storage
    )
    assert "from .run_execution_state_machine import RELEASED_LEASE_STATES, RETRYABLE_RUN_STATUSES" in (
        rule_partial_rerun_lifecycle
    )
    assert "from .run_execution_state_machine import RunExecutionStateMachine" in backfill_reprocessing

    assert "TERMINAL_RUN_STATUSES =" not in artifact_lifecycle_storage
    assert "TERMINAL_RUN_STATUSES =" not in execution_resume_plan
    assert "TERMINAL_RUN_STATUSES =" not in run_execution_context_storage
    assert "RESUMABLE_RUN_STATUSES =" not in execution_resume_plan
    assert "RETRYABLE_TERMINAL_RUN_STATUSES =" not in run_execution_context_storage
    assert "RETRYABLE_TERMINAL_RUN_STATUSES =" not in rule_partial_rerun_lifecycle
    assert "RELEASED_LEASE_STATES =" not in rule_partial_rerun_lifecycle
    assert "TERMINAL_RUN_STATUSES =" not in backfill_reprocessing


def test_tool_prepare_job_records_live_outside_storage_mutation_module() -> None:
    storage = (REMOTE_RUNNER / "tool_prepare_job_storage.py").read_text(encoding="utf-8")
    records_path = REMOTE_RUNNER / "tool_prepare_job_records.py"

    assert records_path.exists()
    records = records_path.read_text(encoding="utf-8")

    assert "from .storage_core import get_connection, now_iso" in storage
    assert "from .storage import get_connection, now_iso" not in storage
    assert "from .tool_prepare_job_records import (" in storage
    assert "def _job_row_to_dict(" not in storage
    assert "def _event_row_to_dict(" not in storage
    assert "def _missing_resources_from_events(" not in storage
    assert "def _missing_resource_from_details(" not in storage
    assert "def _string_list(" not in storage
    assert "def _candidate_list(" not in storage

    assert "def job_row_to_dict(" in records
    assert "def event_row_to_dict(" in records
    assert "def missing_resources_from_events(" in records
    assert "def missing_resource_from_details(" in records
