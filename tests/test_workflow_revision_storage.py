from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from apps.remote_runner.workflow_revision_read_service import _public_workflow_revision
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.workflow_revision_storage import (
    create_or_fetch_workflow_revision,
    fetch_workflow_revision,
)
from tests.helpers.reference_database import make_configured_remote_runner


def _manifest(entrypoint_hash: str = "sha256:snakefile-a") -> dict:
    return {
        "schemaVersion": "workflow-revision-manifest.v1",
        "entrypoint": "Snakefile",
        "files": [{"path": "Snakefile", "sha256": entrypoint_hash}],
        "toolRevisions": [{"toolRevisionId": "toolrev_fastqc_1"}],
    }


def _graph_snapshot() -> dict:
    return {
        "schemaVersion": "workflow-graph.v1",
        "nodes": [{"stepId": "fastqc", "toolRevisionId": "toolrev_fastqc_1"}],
        "edges": [],
    }


def _runtime_lock() -> dict:
    return {
        "schemaVersion": "runtime-lock.v1",
        "platform": "linux-64",
        "environmentSha256": "runtime-lock-sha256",
    }


def _compiler() -> dict:
    return {
        "name": "h2ometa-workflow-design-compiler",
        "version": "2026.6.7",
    }


def test_create_or_fetch_workflow_revision_is_deterministic_and_immutable(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)

    first = create_or_fetch_workflow_revision(
        cfg,
        draft_id="wfd_demo",
        draft_revision=3,
        manifest=_manifest(),
        graph_snapshot=_graph_snapshot(),
        runtime_lock=_runtime_lock(),
        compiler=_compiler(),
        created_by="agent-a",
        created_at="2099-06-07T10:00:00Z",
    )
    replay = create_or_fetch_workflow_revision(
        cfg,
        draft_id="wfd_demo",
        draft_revision=3,
        manifest=_manifest(),
        graph_snapshot=_graph_snapshot(),
        runtime_lock=_runtime_lock(),
        compiler=_compiler(),
        created_by="agent-b",
        created_at="2099-06-07T10:05:00Z",
    )
    changed = create_or_fetch_workflow_revision(
        cfg,
        draft_id="wfd_demo",
        draft_revision=3,
        manifest=_manifest("sha256:snakefile-b"),
        graph_snapshot=_graph_snapshot(),
        runtime_lock=_runtime_lock(),
        compiler=_compiler(),
        created_by="agent-a",
        created_at="2099-06-07T10:10:00Z",
    )

    assert first["created"] is True
    assert replay["created"] is False
    assert replay["workflowRevisionId"] == first["workflowRevisionId"]
    assert replay["contentHash"] == first["contentHash"]
    assert replay["createdBy"] == "agent-a"
    assert changed["workflowRevisionId"] != first["workflowRevisionId"]
    assert changed["contentHash"] != first["contentHash"]

    fetched = fetch_workflow_revision(cfg, first["workflowRevisionId"])
    assert fetched == {key: value for key, value in first.items() if key != "created"}

    with get_connection(cfg) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="WORKFLOW_REVISION_IMMUTABLE"):
            connection.execute(
                "UPDATE workflow_revisions SET manifest_json = ? WHERE workflow_revision_id = ?",
                ("{}", first["workflowRevisionId"]),
            )


def test_workflow_revision_content_hash_includes_draft_revision(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)

    first = create_or_fetch_workflow_revision(
        cfg,
        draft_id="wfd_demo",
        draft_revision=1,
        manifest=_manifest(),
        graph_snapshot=_graph_snapshot(),
        runtime_lock=_runtime_lock(),
        compiler=_compiler(),
    )
    second = create_or_fetch_workflow_revision(
        cfg,
        draft_id="wfd_demo",
        draft_revision=2,
        manifest=_manifest(),
        graph_snapshot=_graph_snapshot(),
        runtime_lock=_runtime_lock(),
        compiler=_compiler(),
    )

    assert second["workflowRevisionId"] != first["workflowRevisionId"]
    assert second["contentHash"] != first["contentHash"]


def test_public_workflow_revision_redacts_runtime_paths_and_hashes_original_lock() -> None:
    runtime_lock = {
        "schemaVersion": "workflow-runtime-lock.v1",
        "platform": "linux-64",
        "snakemakeCommand": "/secret/workflow-env/bin/snakemake",
        "releaseDir": "/secret/release",
    }
    public = _public_workflow_revision(
        {
            "workflowRevisionId": "wfrev_demo",
            "contentHash": "a" * 64,
            "draftId": "wfd_demo",
            "draftRevision": 1,
            "manifest": _manifest(),
            "graphSnapshot": _graph_snapshot(),
            "runtimeLock": runtime_lock,
            "compiler": _compiler(),
            "createdBy": "agent-a",
            "createdAt": "2099-06-07T10:00:00Z",
        }
    )

    expected_runtime_hash = hashlib.sha256(
        json.dumps(runtime_lock, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert public["runtimeLockSha256"] == expected_runtime_hash
    assert public["runtimeLock"] == {
        "schemaVersion": "workflow-runtime-lock.v1",
        "platform": "linux-64",
    }
    assert "snakemakeCommand" not in public["runtimeLock"]
    assert "releaseDir" not in public["runtimeLock"]


def test_workflow_revision_read_route_is_registered() -> None:
    root = Path(__file__).resolve().parents[1]
    route_source = (root / "apps/remote_runner/workflow_revision_routes.py").read_text(encoding="utf-8")
    service_source = (root / "apps/remote_runner/workflow_revision_read_service.py").read_text(encoding="utf-8")
    main_source = (root / "apps/remote_runner/main.py").read_text(encoding="utf-8")

    assert "operation_id=REMOTE_ENDPOINTS[WORKFLOW_REVISION_READ].operation_id" in route_source
    assert "get_workflow_revision_from_request" in route_source
    assert 'action="workflow_revision.read"' in service_source
    assert "await authorized_config(" not in service_source
    assert "workflow_revision_router" in main_source
    assert "app.include_router(workflow_revision_router)" in main_source
