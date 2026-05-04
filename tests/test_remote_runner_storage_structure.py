from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REMOTE_RUNNER = ROOT / "apps" / "remote_runner"


def test_storage_schema_lives_outside_storage_module() -> None:
    schema = (REMOTE_RUNNER / "storage_schema.py").read_text(encoding="utf-8")
    storage = (REMOTE_RUNNER / "storage.py").read_text(encoding="utf-8")

    assert "SCHEMA_SQL" in schema
    assert "CREATE TABLE IF NOT EXISTS runs" in schema
    assert "from .storage_schema import SCHEMA_SQL" in storage
    assert 'SCHEMA_SQL = """' not in storage
