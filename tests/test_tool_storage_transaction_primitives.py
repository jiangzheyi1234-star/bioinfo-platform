from __future__ import annotations

from pathlib import Path

from apps.remote_runner.config import ensure_runtime_layout
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.tool_revisions import publish_tool_revision, publish_tool_revision_record
from apps.remote_runner.tool_storage import upsert_tool_record
from tests.helpers.reference_database import make_remote_runner_config


def test_connection_scoped_tool_publication_rolls_back_as_one_unit(tmp_path: Path) -> None:
    cfg = make_remote_runner_config(tmp_path)
    ensure_runtime_layout(cfg)

    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        revision = publish_tool_revision_record(connection, _tool_payload())
        saved = upsert_tool_record(connection, revision)

        assert saved["toolRevisionId"] == revision["toolRevisionId"]
        assert _row_count(connection, "tool_revisions") == 1
        assert _row_count(connection, "tools") == 1
        assert _row_count(connection, "tool_index") == 1
        connection.rollback()

    with get_connection(cfg) as connection:
        assert _row_count(connection, "tool_revisions") == 0
        assert _row_count(connection, "tools") == 0
        assert _row_count(connection, "tool_index") == 0


def test_tool_revision_identity_includes_derived_environment_lock(tmp_path: Path) -> None:
    cfg = make_remote_runner_config(tmp_path)
    ensure_runtime_layout(cfg)
    payload = _tool_payload()

    first = publish_tool_revision(
        cfg,
        {
            **payload,
            "environmentSpec": {"adapter": "conda", "name": "fastqc-a", "dependencies": ["fastqc=0.12.1"]},
        },
    )
    second = publish_tool_revision(
        cfg,
        {
            **payload,
            "environmentSpec": {"adapter": "conda", "name": "fastqc-b", "dependencies": ["fastqc=0.12.1"]},
        },
    )

    assert first["environmentLock"]["name"] == "fastqc-a"
    assert second["environmentLock"]["name"] == "fastqc-b"
    assert first["toolRevisionId"] != second["toolRevisionId"]
    assert first["specHash"] != second["specHash"]


def _tool_payload() -> dict[str, object]:
    return {
        "id": "bioconda::fastqc",
        "name": "FastQC",
        "source": "bioconda",
        "sourceLabel": "Bioconda",
        "version": "0.12.1",
        "packageSpec": "bioconda::fastqc=0.12.1",
        "summary": "Read quality control.",
        "targetPlatform": "linux-64",
        "targetPlatformSupported": True,
        "platforms": ["linux-64"],
    }


def _row_count(connection, table_name: str) -> int:
    return int(connection.execute(f"SELECT COUNT(*) AS count FROM {table_name}").fetchone()["count"])
