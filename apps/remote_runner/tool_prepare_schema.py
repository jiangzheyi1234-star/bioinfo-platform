from __future__ import annotations


TOOL_PREPARE_SCHEMA_SQL = """CREATE TABLE IF NOT EXISTS tool_prepare_jobs (
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

"""
