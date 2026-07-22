from __future__ import annotations

import sqlite3


REQUIRED_TABLES = {
    "agent_events",
    "agent_approvals",
    "agent_plan_revisions",
    "agent_process_instances",
    "agent_run_authorizations",
    "agent_session_effect_budgets",
    "agent_sessions",
    "agent_workspace_proofs",
    "artifact_blobs",
    "artifact_cache_entries",
    "artifact_cache_pins",
    "artifact_lifecycle_policies",
    "artifact_materializations",
    "artifacts",
    "candidate_outputs",
    "evidence_events",
    "evidence_schemas",
    "idempotency",
    "lineage_edges",
    "reconcile_queue",
    "reference_databases",
    "resource_events",
    "resources",
    "result_package_exports",
    "run_artifact_edges",
    "run_attempts",
    "run_commands",
    "run_events",
    "run_jobs",
    "run_leases",
    "run_rule_events",
    "run_rules",
    "run_resource_allocations",
    "run_worker_slots",
    "run_workers",
    "runs",
    "schema_migrations",
    "service_state",
    "tool_index",
    "tool_prepare_job_events",
    "tool_prepare_jobs",
    "tool_revisions",
    "tool_runtime_profiles",
    "tool_validation_results",
    "tools",
    "uploads",
    "workflow_design_drafts",
    "workflow_backfill_launches",
    "workflow_backfill_partitions",
    "workflow_revisions",
    "workflow_trigger_readiness_observations",
    "workflow_trigger_inbox_events",
    "workflow_trigger_dispatches",
    "workflow_trigger_events",
    "workflow_triggers",
}

REQUIRED_INDEXES = {
    "idx_agent_events_hash_chain",
    "idx_agent_events_session_idempotency",
    "idx_agent_approvals_effective_decision",
    "idx_agent_approvals_session_plan",
    "idx_agent_plan_revisions_hash",
    "idx_agent_plan_revisions_session_generation",
    "idx_agent_process_instances_attempt_state",
    "idx_agent_process_instances_incarnation_hash",
    "idx_agent_process_instances_logical_activity_unique",
    "idx_agent_process_instances_run_ordinal",
    "idx_agent_process_instances_state_started",
    "idx_agent_run_authorizations_run",
    "idx_agent_run_authorizations_session",
    "idx_agent_run_authorizations_session_idempotency",
    "idx_agent_session_effect_budgets_session_idempotency",
    "idx_agent_sessions_project_updated",
    "idx_agent_sessions_status_updated",
    "idx_agent_workspace_proofs_authorization",
    "idx_agent_workspace_proofs_run_boundary",
    "idx_artifact_materializations_lifecycle",
    "idx_artifact_cache_entries_blob",
    "idx_artifact_cache_entries_revision",
    "idx_artifact_cache_pins_entry_state",
    "idx_artifact_cache_pins_object",
    "idx_artifacts_lifecycle",
    "idx_candidate_outputs_attempt_generation_key",
    "idx_evidence_events_chain",
    "idx_evidence_events_subject",
    "idx_evidence_events_type_seq",
    "idx_lineage_edges_object",
    "idx_lineage_edges_lifecycle",
    "idx_lineage_edges_run",
    "idx_lineage_edges_subject",
    "idx_result_package_exports_result_created",
    "idx_result_package_exports_run_lifecycle",
    "idx_run_artifact_edges_adopted_output",
    "idx_run_artifact_edges_blob",
    "idx_run_artifact_edges_lifecycle",
    "idx_run_artifact_edges_run",
    "idx_run_commands_run",
    "idx_run_events_hash_chain",
    "idx_run_events_run_seq",
    "idx_run_jobs_claimable",
    "idx_run_leases_active_expiry",
    "idx_run_rule_events_run_rule",
    "idx_run_rules_run_status",
    "idx_run_resource_allocations_active",
    "idx_run_workers_state_heartbeat",
    "idx_tool_index_search",
    "idx_tool_index_source_quality",
    "idx_tool_index_state_quality",
    "idx_tool_prepare_jobs_active_reservation",
    "idx_tool_runtime_profiles_hash",
    "idx_tool_runtime_profiles_revision",
    "idx_tool_validation_results_job",
    "idx_tool_validation_results_tool",
    "idx_workflow_trigger_dispatches_run",
    "idx_workflow_trigger_dispatches_state",
    "idx_workflow_trigger_events_external",
    "idx_workflow_trigger_events_trigger_created",
    "idx_workflow_trigger_inbox_state",
    "idx_workflow_trigger_inbox_trigger_event",
    "idx_workflow_trigger_inbox_trigger_received",
    "idx_workflow_trigger_readiness_observations_event",
    "idx_workflow_trigger_readiness_observations_state",
    "idx_workflow_triggers_source_enabled",
    "idx_workflow_backfill_launches_state",
    "idx_workflow_backfill_launches_trigger_created",
    "idx_workflow_backfill_partitions_event",
    "idx_workflow_backfill_partitions_launch_state",
    "idx_workflow_backfill_partitions_run",
}

REQUIRED_TRIGGERS = {
    "agent_bound_runs_no_delete",
    "agent_events_no_delete",
    "agent_events_no_update",
    "agent_approvals_no_delete",
    "agent_approvals_no_update",
    "agent_plan_revisions_no_delete",
    "agent_plan_revisions_no_update",
    "agent_process_instances_event_binding",
    "agent_process_instances_envelope_guard",
    "agent_process_instances_event_role_unique_insert",
    "agent_process_instances_event_role_unique_update",
    "agent_process_instances_exited_shape",
    "agent_process_instances_insert_guard",
    "agent_process_instances_intent_immutable",
    "agent_process_instances_no_delete",
    "agent_process_instances_run_events_no_delete",
    "agent_process_instances_run_events_no_update",
    "agent_process_instances_spawn_failed_shape",
    "agent_process_instances_started_identity_immutable",
    "agent_process_instances_started_shape",
    "agent_process_instances_stopped_shape",
    "agent_process_instances_transition_guard",
    "agent_run_authorizations_no_delete",
    "agent_run_authorizations_no_update",
    "agent_session_effect_budgets_no_delete",
    "agent_session_effect_budgets_no_update",
    "agent_workspace_proofs_no_delete",
    "agent_workspace_proofs_no_update",
    "workflow_revisions_no_update",
}

REQUIRED_FOREIGN_KEYS = {
    (
        "agent_process_instances",
        "attempt_id",
        "run_attempts",
        "attempt_id",
        "RESTRICT",
    ),
    (
        "agent_process_instances",
        "authorization_id",
        "agent_run_authorizations",
        "authorization_id",
        "RESTRICT",
    ),
    (
        "agent_process_instances",
        "run_id",
        "runs",
        "run_id",
        "RESTRICT",
    ),
    (
        "agent_process_instances",
        "spawn_intent_event_id",
        "run_events",
        "event_id",
        "RESTRICT",
    ),
    (
        "agent_process_instances",
        "started_event_id",
        "run_events",
        "event_id",
        "RESTRICT",
    ),
    (
        "agent_process_instances",
        "terminal_event_id",
        "run_events",
        "event_id",
        "RESTRICT",
    ),
    (
        "agent_process_instances",
        "workspace_proof_id",
        "agent_workspace_proofs",
        "workspace_proof_id",
        "RESTRICT",
    ),
    ("agent_run_authorizations", "plan_revision_id", "agent_plan_revisions", "plan_revision_id", "RESTRICT"),
    ("agent_run_authorizations", "run_id", "runs", "run_id", "RESTRICT"),
    ("agent_run_authorizations", "session_id", "agent_sessions", "session_id", "RESTRICT"),
    (
        "agent_run_authorizations",
        "workflow_revision_id",
        "workflow_revisions",
        "workflow_revision_id",
        "RESTRICT",
    ),
    ("agent_session_effect_budgets", "session_id", "agent_sessions", "session_id", "RESTRICT"),
    (
        "agent_workspace_proofs",
        "attempt_id",
        "run_attempts",
        "attempt_id",
        "RESTRICT",
    ),
    (
        "agent_workspace_proofs",
        "authorization_id",
        "agent_run_authorizations",
        "authorization_id",
        "RESTRICT",
    ),
    ("agent_workspace_proofs", "run_id", "runs", "run_id", "RESTRICT"),
    (
        "agent_workspace_proofs",
        "source_attempt_id",
        "run_attempts",
        "attempt_id",
        "RESTRICT",
    ),
    (
        "agent_workspace_proofs",
        "workflow_revision_id",
        "workflow_revisions",
        "workflow_revision_id",
        "RESTRICT",
    ),
}


def missing_required_schema_objects(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        """
        SELECT type, name
        FROM sqlite_master
        WHERE type IN ('table', 'index', 'trigger')
        """
    ).fetchall()
    existing = {(str(row[0]), str(row[1])) for row in rows}
    missing: list[str] = []
    missing.extend(f"table:{name}" for name in sorted(REQUIRED_TABLES) if ("table", name) not in existing)
    missing.extend(f"index:{name}" for name in sorted(REQUIRED_INDEXES) if ("index", name) not in existing)
    missing.extend(f"trigger:{name}" for name in sorted(REQUIRED_TRIGGERS) if ("trigger", name) not in existing)

    foreign_keys_by_table = {
        table_name: {
            (
                str(row[3]),
                str(row[2]),
                str(row[4]),
                str(row[6]).upper(),
            )
            for row in connection.execute(f"PRAGMA foreign_key_list({table_name})").fetchall()
        }
        for table_name in {item[0] for item in REQUIRED_FOREIGN_KEYS}
    }
    for table_name, column, parent_table, parent_column, on_delete in sorted(REQUIRED_FOREIGN_KEYS):
        expected = (column, parent_table, parent_column, on_delete)
        if expected not in foreign_keys_by_table[table_name]:
            missing.append(
                f"foreign-key:{table_name}.{column}->{parent_table}.{parent_column}:{on_delete}"
            )
    return missing
