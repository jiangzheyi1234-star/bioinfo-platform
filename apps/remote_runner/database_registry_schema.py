from __future__ import annotations


REFERENCE_DATABASE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reference_databases (
    database_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    db_type TEXT NOT NULL,
    version TEXT NOT NULL,
    path TEXT NOT NULL,
    description TEXT NOT NULL,
    source TEXT NOT NULL,
    manifest_path TEXT NOT NULL,
    size_bytes INTEGER,
    checksum TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_checked_at TEXT
);
"""
