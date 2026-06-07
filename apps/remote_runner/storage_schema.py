from __future__ import annotations


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS service_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS uploads (
    upload_id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    uploaded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    server_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    pipeline_id TEXT NOT NULL,
    pipeline_version TEXT NOT NULL,
    run_spec_version TEXT NOT NULL,
    workflow_revision_id TEXT,
    status TEXT NOT NULL,
    stage TEXT NOT NULL,
    state_version INTEGER NOT NULL,
    message TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    result_dir TEXT NOT NULL,
    last_error_json TEXT,
    last_updated_at TEXT NOT NULL,
    request_id TEXT NOT NULL,
    submitted_at TEXT NOT NULL,
    run_spec_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_events (
    event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    seq INTEGER NOT NULL DEFAULT 0,
    schema_version TEXT NOT NULL DEFAULT '',
    from_status TEXT,
    to_status TEXT,
    stage TEXT NOT NULL,
    state_version INTEGER NOT NULL,
    message TEXT NOT NULL,
    request_id TEXT NOT NULL,
    command_id TEXT,
    correlation_id TEXT,
    actor TEXT,
    payload_hash TEXT NOT NULL DEFAULT '',
    event_hash TEXT NOT NULL DEFAULT '',
    prev_event_hash TEXT,
    created_at TEXT NOT NULL,
    details_json TEXT
);

CREATE TABLE IF NOT EXISTS run_commands (
    command_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    command_type TEXT NOT NULL,
    idempotency_key TEXT,
    actor TEXT,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    requested_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_run_commands_run
ON run_commands(run_id, requested_at);

CREATE TABLE IF NOT EXISTS run_jobs (
    job_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    state TEXT NOT NULL,
    queue_name TEXT NOT NULL DEFAULT 'default',
    priority INTEGER NOT NULL DEFAULT 0,
    available_at TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    retry_policy_json TEXT NOT NULL DEFAULT '{}',
    timeout_policy_json TEXT NOT NULL DEFAULT '{}',
    dead_lettered_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(run_id)
);

CREATE TABLE IF NOT EXISTS run_attempts (
    attempt_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    lease_generation INTEGER NOT NULL,
    attempt_number INTEGER NOT NULL DEFAULT 1,
    state TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    work_dir TEXT NOT NULL,
    process_pid INTEGER,
    process_group_id TEXT,
    cancel_requested_at TEXT,
    killed_at TEXT,
    output_adoption_state TEXT NOT NULL DEFAULT 'pending',
    started_at TEXT,
    finished_at TEXT,
    exit_code INTEGER,
    fenced_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_leases (
    run_id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL,
    lease_generation INTEGER NOT NULL,
    worker_id TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    state TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_run_jobs_claimable
ON run_jobs(state, available_at, priority, created_at);

CREATE INDEX IF NOT EXISTS idx_run_leases_active_expiry
ON run_leases(state, expires_at);

CREATE TABLE IF NOT EXISTS run_workers (
    worker_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    pid INTEGER NOT NULL,
    hostname TEXT NOT NULL,
    state TEXT NOT NULL,
    queue_name TEXT NOT NULL DEFAULT 'default',
    concurrency_limit INTEGER NOT NULL DEFAULT 1,
    current_attempt_id TEXT,
    heartbeat_at TEXT NOT NULL,
    last_error_json TEXT NOT NULL DEFAULT '{}',
    drain_requested_at TEXT,
    started_at TEXT NOT NULL,
    stopped_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS candidate_outputs (
    candidate_output_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    output_key TEXT NOT NULL,
    path TEXT NOT NULL,
    size_bytes INTEGER,
    sha256 TEXT,
    observed_at TEXT NOT NULL,
    verification_state TEXT NOT NULL,
    verification_json TEXT NOT NULL DEFAULT '{}',
    adopted_artifact_id TEXT,
    adopted_at TEXT,
    UNIQUE(run_id, attempt_id, output_key)
);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    path TEXT NOT NULL,
    storage_backend TEXT NOT NULL DEFAULT 'local',
    storage_uri TEXT NOT NULL DEFAULT '',
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifact_blobs (
    artifact_blob_id TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL UNIQUE,
    blake3 TEXT,
    size_bytes INTEGER NOT NULL,
    media_type TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifact_materializations (
    materialization_id TEXT PRIMARY KEY,
    artifact_blob_id TEXT NOT NULL,
    storage_backend TEXT NOT NULL,
    storage_uri TEXT NOT NULL,
    local_path TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(artifact_blob_id, storage_backend, storage_uri)
);

CREATE TABLE IF NOT EXISTS run_artifact_edges (
    edge_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    artifact_blob_id TEXT NOT NULL,
    role TEXT NOT NULL,
    port_name TEXT,
    step_id TEXT,
    content_hash TEXT NOT NULL,
    upstream_run_id TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_run_artifact_edges_run
ON run_artifact_edges(run_id, role, port_name, step_id);

CREATE INDEX IF NOT EXISTS idx_run_artifact_edges_blob
ON run_artifact_edges(artifact_blob_id);

CREATE TABLE IF NOT EXISTS lineage_edges (
    lineage_edge_id TEXT PRIMARY KEY,
    subject_kind TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object_kind TEXT NOT NULL,
    object_id TEXT NOT NULL,
    run_id TEXT,
    attempt_id TEXT,
    workflow_revision_id TEXT,
    evidence_event_id TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    content_hash TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lineage_edges_subject
ON lineage_edges(subject_kind, subject_id, predicate);

CREATE INDEX IF NOT EXISTS idx_lineage_edges_object
ON lineage_edges(object_kind, object_id, predicate);

CREATE INDEX IF NOT EXISTS idx_lineage_edges_run
ON lineage_edges(run_id, created_at);

CREATE TABLE IF NOT EXISTS idempotency (
    server_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    canonical_payload_hash TEXT NOT NULL,
    run_id TEXT NOT NULL,
    status TEXT NOT NULL,
    PRIMARY KEY (server_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS tools (
    tool_id TEXT PRIMARY KEY,
    tool_revision_id TEXT NOT NULL DEFAULT '',
    revision INTEGER NOT NULL DEFAULT 0,
    name TEXT NOT NULL,
    source TEXT NOT NULL,
    source_label TEXT NOT NULL,
    version TEXT NOT NULL,
    package_spec TEXT NOT NULL,
    summary TEXT NOT NULL,
    target_platform TEXT NOT NULL,
    target_platform_supported INTEGER NOT NULL,
    platforms_json TEXT NOT NULL,
    source_url TEXT NOT NULL,
    test_command TEXT NOT NULL,
    rule_template_json TEXT NOT NULL DEFAULT '{}',
    rule_spec_draft_json TEXT NOT NULL DEFAULT '{}',
    capabilities_json TEXT NOT NULL DEFAULT '[]',
    snakemake_wrappers_json TEXT NOT NULL DEFAULT '[]',
    contract_status_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    published_at TEXT,
    last_checked_at TEXT
);

CREATE TABLE IF NOT EXISTS tool_revisions (
    tool_revision_id TEXT PRIMARY KEY,
    tool_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    tool_json TEXT NOT NULL,
    published_at TEXT NOT NULL,
    UNIQUE(tool_id, revision)
);

CREATE TABLE IF NOT EXISTS tool_runtime_profiles (
    runtime_profile_id TEXT PRIMARY KEY,
    tool_revision_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    engine TEXT NOT NULL,
    environment_lock_json TEXT NOT NULL,
    resource_profile_json TEXT NOT NULL,
    security_policy_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_tool_runtime_profiles_hash
ON tool_runtime_profiles(content_hash);

CREATE INDEX IF NOT EXISTS idx_tool_runtime_profiles_revision
ON tool_runtime_profiles(tool_revision_id, created_at DESC);

CREATE TABLE IF NOT EXISTS tool_validation_results (
    validation_result_id TEXT PRIMARY KEY,
    tool_id TEXT NOT NULL,
    tool_revision_id TEXT NOT NULL DEFAULT '',
    runtime_profile_id TEXT,
    job_id TEXT,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    evidence_id TEXT,
    logs_json TEXT NOT NULL DEFAULT '[]',
    artifacts_json TEXT NOT NULL DEFAULT '[]',
    failure_code TEXT,
    duration_ms INTEGER,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tool_validation_results_tool
ON tool_validation_results(tool_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_tool_validation_results_job
ON tool_validation_results(job_id);

CREATE TABLE IF NOT EXISTS evidence_schemas (
    schema_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    json_schema_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(name, version),
    UNIQUE(content_hash)
);

CREATE TABLE IF NOT EXISTS evidence_events (
    event_id TEXT PRIMARY KEY,
    seq INTEGER NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    event_schema_id TEXT NOT NULL,
    subject_kind TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    producer TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    event_hash TEXT NOT NULL UNIQUE,
    prev_event_hash TEXT NOT NULL DEFAULT '',
    occurred_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_evidence_events_subject
ON evidence_events(subject_kind, subject_id, seq);

CREATE INDEX IF NOT EXISTS idx_evidence_events_type_seq
ON evidence_events(event_type, seq);

CREATE INDEX IF NOT EXISTS idx_evidence_events_chain
ON evidence_events(seq, event_hash);

CREATE TABLE IF NOT EXISTS tool_index (
    tool_id TEXT PRIMARY KEY,
    latest_stable_revision_id TEXT,
    name TEXT NOT NULL,
    source TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT '',
    package_spec TEXT NOT NULL,
    searchable_text TEXT NOT NULL,
    facets_json TEXT NOT NULL,
    validation_summary_json TEXT NOT NULL,
    quality_score INTEGER NOT NULL,
    upgrade_available INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tool_index_search
ON tool_index(searchable_text);

CREATE INDEX IF NOT EXISTS idx_tool_index_source_quality
ON tool_index(source, quality_score DESC, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_tool_index_state_quality
ON tool_index(state, quality_score DESC, updated_at DESC);

CREATE TABLE IF NOT EXISTS tool_prepare_jobs (
    job_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    stage TEXT NOT NULL,
    message TEXT NOT NULL,
    tool_id TEXT NOT NULL,
    reservation_key TEXT NOT NULL DEFAULT '',
    reservation_package_spec TEXT NOT NULL DEFAULT '',
    reservation_validation_target TEXT NOT NULL DEFAULT '',
    request_json TEXT NOT NULL,
    result_json TEXT,
    error_code TEXT,
    claimed_by TEXT NOT NULL DEFAULT '',
    claimed_until TEXT,
    heartbeat_at TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    next_attempt_at TEXT,
    exhausted_at TEXT,
    backoff_seconds INTEGER NOT NULL DEFAULT 30,
    last_worker_error_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    cancelled_at TEXT
);

CREATE TABLE IF NOT EXISTS tool_prepare_job_events (
    event_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workflow_design_drafts (
    draft_id TEXT PRIMARY KEY,
    parent_draft_id TEXT,
    contract_version TEXT NOT NULL,
    engine TEXT NOT NULL,
    name TEXT NOT NULL,
    project_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    draft_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workflow_revisions (
    workflow_revision_id TEXT PRIMARY KEY,
    draft_id TEXT,
    draft_revision INTEGER,
    content_hash TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    graph_snapshot_json TEXT NOT NULL,
    runtime_lock_json TEXT NOT NULL,
    compiler_json TEXT NOT NULL,
    created_by TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(content_hash)
);

CREATE TRIGGER IF NOT EXISTS workflow_revisions_no_update
BEFORE UPDATE ON workflow_revisions
BEGIN
    SELECT RAISE(ABORT, 'WORKFLOW_REVISION_IMMUTABLE');
END;

CREATE TABLE IF NOT EXISTS resources (
    resource_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    desired_json TEXT NOT NULL,
    observed_json TEXT NOT NULL,
    status TEXT NOT NULL,
    owner_kind TEXT,
    owner_id TEXT,
    finalizers_json TEXT NOT NULL DEFAULT '[]',
    deletion_timestamp TEXT,
    conditions_json TEXT NOT NULL DEFAULT '[]',
    generation INTEGER NOT NULL,
    observed_generation INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(kind, name)
);

CREATE TABLE IF NOT EXISTS resource_events (
    event_id TEXT PRIMARY KEY,
    resource_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    UNIQUE(resource_id, seq)
);

CREATE TABLE IF NOT EXISTS reconcile_queue (
    item_id TEXT PRIMARY KEY,
    resource_id TEXT NOT NULL,
    dedup_key TEXT NOT NULL,
    reason TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    available_at TEXT NOT NULL,
    claimed_by TEXT,
    claimed_until TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    backoff_seconds INTEGER NOT NULL DEFAULT 1,
    max_attempts INTEGER NOT NULL DEFAULT 12,
    jitter_seed TEXT NOT NULL,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(dedup_key)
);
"""
