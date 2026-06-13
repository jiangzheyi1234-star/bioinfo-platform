from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.storage_schema import SCHEMA_SQL
from tests.helpers.reference_database import make_configured_remote_runner


def test_output_edge_uniqueness_migration_preserves_legacy_duplicates(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    with sqlite3.connect(cfg.db_path) as legacy:
        legacy.executescript(SCHEMA_SQL)
        legacy.executemany(
            """
            INSERT INTO run_artifact_edges (
                edge_id, run_id, artifact_blob_id, role, port_name, step_id,
                content_hash, upstream_run_id, created_at
            ) VALUES (?, 'run_legacy', ?, ?, 'report', 'summarize', ?, NULL, ?)
            """,
            [
                ("aredge_first", "ablob_first", "output", "sha256:first", "2099-06-07T10:00:00Z"),
                ("aredge_later", "ablob_later", "output", "sha256:later", "2099-06-07T10:00:01Z"),
                ("aredge_input_1", "ablob_input_1", "input", "sha256:input1", "2099-06-07T10:00:02Z"),
                ("aredge_input_2", "ablob_input_2", "input", "sha256:input2", "2099-06-07T10:00:03Z"),
            ],
        )

    with get_connection(cfg) as migrated:
        rows = migrated.execute(
            """
            SELECT edge_id, role, port_name
            FROM run_artifact_edges
            WHERE run_id = 'run_legacy'
            ORDER BY created_at, edge_id
            """
        ).fetchall()
        index = migrated.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'index' AND name = 'idx_run_artifact_edges_adopted_output'
            """
        ).fetchone()

    assert [dict(row) for row in rows] == [
        {"edge_id": "aredge_first", "role": "output", "port_name": "report"},
        {
            "edge_id": "aredge_later",
            "role": "output",
            "port_name": "report#legacy-aredge_later",
        },
        {"edge_id": "aredge_input_1", "role": "input", "port_name": "report"},
        {"edge_id": "aredge_input_2", "role": "input", "port_name": "report"},
    ]
    assert index is not None
    assert "WHERE role = 'output' AND port_name IS NOT NULL" in index["sql"]

    with get_connection(cfg) as replay:
        replayed_port_name = replay.execute(
            "SELECT port_name FROM run_artifact_edges WHERE edge_id = 'aredge_later'"
        ).fetchone()["port_name"]
        with pytest.raises(sqlite3.IntegrityError):
            replay.execute(
                """
                INSERT INTO run_artifact_edges (
                    edge_id, run_id, artifact_blob_id, role, port_name, step_id,
                    content_hash, upstream_run_id, created_at
                ) VALUES (
                    'aredge_rejected', 'run_legacy', 'ablob_rejected', 'output',
                    'report', 'summarize', 'sha256:rejected', NULL, '2099-06-07T10:00:04Z'
                )
                """
            )
    assert replayed_port_name == "report#legacy-aredge_later"
