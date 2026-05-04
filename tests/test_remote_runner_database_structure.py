from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REMOTE_RUNNER = ROOT / "apps" / "remote_runner"


def test_database_registry_schema_lives_outside_database_module() -> None:
    schema = (REMOTE_RUNNER / "database_registry_schema.py").read_text(encoding="utf-8")
    databases = (REMOTE_RUNNER / "databases.py").read_text(encoding="utf-8")

    assert "REFERENCE_DATABASE_SCHEMA_SQL" in schema
    assert "CREATE TABLE IF NOT EXISTS reference_databases" in schema
    assert "from .database_registry_schema import REFERENCE_DATABASE_SCHEMA_SQL" in databases
    assert '_SCHEMA_SQL = """' not in databases
