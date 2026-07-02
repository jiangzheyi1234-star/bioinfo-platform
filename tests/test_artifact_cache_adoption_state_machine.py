from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from apps.remote_runner.artifact_cache_adoption import try_adopt_cached_outputs
from apps.remote_runner.run_execution_storage import claim_next_run_job
from apps.remote_runner.storage import create_run_record, persist_artifact
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.workflow_revision_storage import create_or_fetch_workflow_revision
from tests.helpers.reference_database import make_configured_remote_runner


def test_artifact_cache_adoption_cannot_complete_terminal_run(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    revision = _create_revision(cfg)
    source_spec = _run_spec("run_cache_terminal_source", revision["workflowRevisionId"])
    target_spec = _run_spec("run_cache_terminal_target", revision["workflowRevisionId"])
    _create_terminal_run(cfg, source_spec)
    persist_artifact(
        cfg,
        run_id="run_cache_terminal_source",
        kind="report",
        path=_managed_report(cfg, "run_cache_terminal_source", b"terminal cache\n"),
        mime_type="text/plain",
        artifact_key="report",
        step_id="summarize",
    )
    claim = _create_active_attempt(cfg, target_spec)
    with get_connection(cfg) as connection:
        connection.execute(
            """
            UPDATE runs
            SET status = 'failed', stage = 'execute', state_version = 2,
                message = 'Terminal failure.'
            WHERE run_id = ?
            """,
            ("run_cache_terminal_target",),
        )
        connection.commit()

    with pytest.raises(ValueError, match="RUN_STATUS_TERMINAL_IMMUTABLE: failed -> completed"):
        try_adopt_cached_outputs(
            cfg,
            run_id="run_cache_terminal_target",
            request_id="req_run_cache_terminal_target",
            run_spec=target_spec,
            output_schema=_output_schema(),
            outputs={"report": str(Path(cfg.results_dir) / "run_cache_terminal_target" / "report.txt")},
            attempt_id=claim["attemptId"],
            lease_generation=claim["leaseGeneration"],
            result_dir=str(Path(cfg.results_dir) / "run_cache_terminal_target"),
        )

    with get_connection(cfg) as connection:
        run = connection.execute(
            "SELECT status, stage, state_version, message FROM runs WHERE run_id = ?",
            ("run_cache_terminal_target",),
        ).fetchone()
        status_events = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM run_events
            WHERE run_id = ? AND event_type = 'status-transition'
            """,
            ("run_cache_terminal_target",),
        ).fetchone()["count"]
    assert dict(run) == {
        "status": "failed",
        "stage": "execute",
        "state_version": 2,
        "message": "Terminal failure.",
    }
    assert status_events == 0


def _create_revision(cfg) -> dict[str, Any]:
    return create_or_fetch_workflow_revision(
        cfg,
        draft_id="draft_cache_state_machine",
        draft_revision=1,
        manifest={"files": [{"path": "workflow/Snakefile", "sha256": "snake"}]},
        graph_snapshot={"nodes": [{"id": "summarize", "toolRevisionId": "tool#1"}]},
        runtime_lock={"snakemake": "9.23.1", "python": "3.12"},
        compiler={"name": "h2ometa", "version": "cache-state-machine-test"},
    )


def _run_spec(run_id: str, workflow_revision_id: str) -> dict[str, Any]:
    return {
        "runId": run_id,
        "projectId": "proj_cache",
        "pipelineId": "pipeline_cache",
        "pipelineVersion": "0.1.0",
        "workflowRevisionId": workflow_revision_id,
        "inputs": [{"name": "reads", "sha256": "sha256:reads"}],
        "params": {"threshold": 3},
    }


def _output_schema() -> dict[str, Any]:
    return {
        "artifacts": [
            {"key": "report", "kind": "report", "mimeType": "text/plain", "stepId": "summarize"}
        ]
    }


def _create_terminal_run(cfg, run_spec: dict[str, Any]) -> None:
    create_run_record(
        cfg,
        server_id="srv_cache",
        request_id=f"req_{run_spec['runId']}",
        run_spec=run_spec,
        idempotency_key=f"idem_{run_spec['runId']}",
        payload_hash=f"hash_{run_spec['runId']}",
    )
    with get_connection(cfg) as connection:
        connection.execute(
            """
            UPDATE runs
            SET status = 'completed',
                stage = 'complete',
                finished_at = '2025-01-01T00:00:00Z',
                last_updated_at = '2025-01-01T00:00:00Z'
            WHERE run_id = ?
            """,
            (run_spec["runId"],),
        )
        connection.execute(
            "UPDATE run_jobs SET state = 'completed', updated_at = '2025-01-01T00:00:00Z' WHERE run_id = ?",
            (run_spec["runId"],),
        )
        connection.commit()


def _create_active_attempt(cfg, run_spec: dict[str, Any]) -> dict[str, Any]:
    create_run_record(
        cfg,
        server_id="srv_cache",
        request_id=f"req_{run_spec['runId']}",
        run_spec=run_spec,
        idempotency_key=f"idem_{run_spec['runId']}",
        payload_hash=f"hash_{run_spec['runId']}",
    )
    claim = claim_next_run_job(
        cfg,
        worker_id="worker_cache",
        now="2099-06-07T10:00:00Z",
        lease_seconds=30,
    )
    assert claim is not None
    return claim


def _managed_report(cfg, run_id: str, payload: bytes) -> Path:
    path = Path(cfg.results_dir) / run_id / "report.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path
