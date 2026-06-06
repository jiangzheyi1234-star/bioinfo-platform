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
    from_status TEXT,
    to_status TEXT,
    stage TEXT NOT NULL,
    state_version INTEGER NOT NULL,
    message TEXT NOT NULL,
    request_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    details_json TEXT
);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    created_at TEXT NOT NULL
);

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

CREATE TABLE IF NOT EXISTS tool_prepare_jobs (
    job_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    stage TEXT NOT NULL,
    message TEXT NOT NULL,
    tool_id TEXT NOT NULL,
    request_json TEXT NOT NULL,
    result_json TEXT,
    error_code TEXT,
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
