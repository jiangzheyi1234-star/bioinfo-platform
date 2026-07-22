from __future__ import annotations

import asyncio
import json
from pathlib import Path

from apps.remote_runner.api_models import UploadCreateRequest
from apps.remote_runner.config import ensure_runtime_layout, load_remote_runner_config
from apps.remote_runner.execution_query_routes import get_result_preview_api
from apps.remote_runner.submission_routes import create_upload
from core.contracts.runner_protocol import RUNNER_PROTOCOL_VERSION
from core.contracts.runner_protocol_runtime import CURRENT_RUNNER_PROTOCOL_FINGERPRINT


def _write_config(tmp_path: Path, *, roles: list[str] | None = None) -> Path:
    config_path = tmp_path / "runner.json"
    payload = {
        "token": "phase2-token",
        "runner_protocol_version": RUNNER_PROTOCOL_VERSION,
        "runner_protocol_fingerprint": CURRENT_RUNNER_PROTOCOL_FINGERPRINT,
        "data_root": str(tmp_path / "shared"),
        "db_path": str(tmp_path / "shared" / "data" / "runner.db"),
        "uploads_dir": str(tmp_path / "shared" / "uploads"),
        "results_dir": str(tmp_path / "shared" / "results"),
        "work_dir": str(tmp_path / "shared" / "work"),
        "logs_dir": str(tmp_path / "shared" / "logs"),
    }
    if roles is not None:
        payload["api_token_roles"] = roles
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    return config_path


def test_remote_runner_upload_rejects_oversized_payload(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = _write_config(tmp_path)
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))
    monkeypatch.setattr("apps.remote_runner.upload_storage.MAX_UPLOAD_BYTES", 8)
    payload = UploadCreateRequest(
        filename="reads.fastq",
        contentBase64="QUJDREVGR0hJSg==",
        mimeType="text/plain",
    )

    try:
        asyncio.run(create_upload(payload, authorization="Bearer phase2-token"))
    except ValueError as exc:
        assert str(exc) == "UPLOAD_TOO_LARGE"
    else:
        raise AssertionError("oversized upload should be rejected")


def test_result_preview_truncates_large_text_payload(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = _write_config(tmp_path, roles=["artifact-curator"])
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))
    ensure_runtime_layout(load_remote_runner_config())

    cfg = load_remote_runner_config()
    run_id = "run_preview_large"
    result_dir = Path(cfg.results_dir) / run_id
    result_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = result_dir / "raw-log.txt"
    artifact_path.write_text("x" * (300 * 1024), encoding="utf-8")

    from apps.remote_runner.storage import (
        fetch_result,
        get_connection,
        persist_artifact,
        update_run_state,
    )

    with get_connection(cfg) as connection:
        connection.execute(
            """
            INSERT INTO runs (
                run_id, server_id, project_id, pipeline_id, pipeline_version, run_spec_version,
                status, stage, state_version, message, started_at, finished_at, result_dir,
                last_error_json, last_updated_at, request_id, submitted_at, run_spec_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                "srv_demo",
                "proj_demo",
                "taxonomy-v1",
                "0.1.0",
                "2026-04-21",
                "running",
                "submitted",
                1,
                "Run accepted",
                None,
                None,
                "",
                None,
                "2026-04-21T12:00:00Z",
                "req_preview_large",
                "2026-04-21T12:00:00Z",
                "{}",
            ),
        )
        connection.commit()

    update_run_state(
        cfg,
        run_id=run_id,
        status="completed",
        stage="finalize",
        message="done",
        request_id="req_preview_large",
        result_dir=str(result_dir),
    )
    artifact = persist_artifact(
        cfg,
        run_id=run_id,
        kind="log",
        path=artifact_path,
        mime_type="text/plain",
    )
    result_id = fetch_result(cfg, f"res_{run_id}")["resultId"]
    preview = asyncio.run(
        get_result_preview_api(
            result_id,
            artifact_id=artifact["artifactId"],
            authorization="Bearer phase2-token",
        )
    )["data"]["preview"]

    assert preview["kind"] == "text"
    assert preview["truncated"] is True
    assert len(preview["content"]) <= 256 * 1024
