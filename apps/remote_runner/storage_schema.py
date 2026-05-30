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
    last_checked_at TEXT
);
"""
