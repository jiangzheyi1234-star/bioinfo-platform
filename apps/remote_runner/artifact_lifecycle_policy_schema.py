from __future__ import annotations


ARTIFACT_LIFECYCLE_POLICY_SCHEMA_SQL = """

CREATE TABLE IF NOT EXISTS artifact_lifecycle_policies (
    policy_id TEXT PRIMARY KEY,
    policy_version INTEGER NOT NULL,
    policy_json TEXT NOT NULL,
    policy_fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL DEFAULT '',
    update_reason TEXT NOT NULL DEFAULT ''
);

"""
