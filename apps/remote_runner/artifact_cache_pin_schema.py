from __future__ import annotations

ARTIFACT_CACHE_PIN_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS artifact_cache_pins (
    cache_pin_id TEXT PRIMARY KEY,
    cache_entry_id TEXT NOT NULL,
    cache_key TEXT NOT NULL,
    artifact_blob_id TEXT NOT NULL,
    storage_backend TEXT NOT NULL,
    storage_uri TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    pin_scope TEXT NOT NULL,
    owner_kind TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    released_at TEXT,
    expires_at TEXT,
    UNIQUE(cache_entry_id, pin_scope, owner_kind, owner_id)
);

CREATE INDEX IF NOT EXISTS idx_artifact_cache_pins_object
ON artifact_cache_pins(storage_backend, storage_uri, sha256, state);

CREATE INDEX IF NOT EXISTS idx_artifact_cache_pins_entry_state
ON artifact_cache_pins(cache_entry_id, state, created_at);
"""
