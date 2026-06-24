from __future__ import annotations

from pathlib import Path

import pytest

from apps.remote_runner.result_preview_service import build_result_preview_data
from apps.remote_runner.storage import create_run_record, persist_artifact
from apps.remote_runner.storage_core import get_connection
from tests.helpers.reference_database import make_configured_remote_runner


def test_result_preview_blocks_corrupted_local_artifact(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_preview_corrupt")
    artifact_path = Path(cfg.results_dir) / "run_preview_corrupt" / "report.txt"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text("accepted\n", encoding="utf-8")
    artifact = persist_artifact(
        cfg,
        run_id="run_preview_corrupt",
        kind="report",
        path=artifact_path,
        mime_type="text/plain",
    )
    artifact_path.write_text("tampered\n", encoding="utf-8")

    with pytest.raises(ValueError, match="RESULT_ARTIFACT_CHECKSUM_AUDIT_FAILED"):
        build_result_preview_data(cfg, "res_run_preview_corrupt", artifact["artifactId"])


def test_result_preview_requires_checksum_metadata(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_preview_missing_metadata")
    artifact_path = Path(cfg.results_dir) / "run_preview_missing_metadata" / "report.txt"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text("accepted\n", encoding="utf-8")
    artifact = persist_artifact(
        cfg,
        run_id="run_preview_missing_metadata",
        kind="report",
        path=artifact_path,
        mime_type="text/plain",
    )
    with get_connection(cfg) as connection:
        connection.execute(
            "UPDATE artifacts SET sha256 = '' WHERE artifact_id = ?",
            (artifact["artifactId"],),
        )
        connection.commit()

    with pytest.raises(ValueError, match="RESULT_ARTIFACT_METADATA_INCOMPLETE: sha256"):
        build_result_preview_data(cfg, "res_run_preview_missing_metadata", artifact["artifactId"])


def test_result_preview_rejects_unmanaged_local_artifact_path(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_preview_unmanaged")
    artifact_path = tmp_path / "outside-managed.txt"
    artifact_path.write_text("outside\n", encoding="utf-8")
    artifact = persist_artifact(
        cfg,
        run_id="run_preview_unmanaged",
        kind="report",
        path=artifact_path,
        mime_type="text/plain",
    )

    with pytest.raises(ValueError, match="RESULT_ARTIFACT_STORAGE_UNMANAGED: unmanaged_local_path"):
        build_result_preview_data(cfg, "res_run_preview_unmanaged", artifact["artifactId"])


def _create_run(cfg, run_id: str) -> None:
    create_run_record(
        cfg,
        server_id="srv_preview",
        request_id=f"req_{run_id}",
        run_spec={
            "runId": run_id,
            "projectId": "proj_preview",
            "pipelineId": "pipeline_preview",
            "pipelineVersion": "0.1.0",
            "runSpecVersion": "2026-04-21",
        },
        idempotency_key=f"idem_{run_id}",
        payload_hash=f"hash_{run_id}",
    )
