from __future__ import annotations

import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import remote_worker_crash_recovery_acceptance as acceptance  # noqa: E402


def _event(event_type: str, **details):
    return {"eventType": event_type, "detailsJson": details}


def _v2_event(event_type: str, **payload):
    return {"eventType": event_type, "detailsJson": {"payload": payload, "schema_version": "run-event.v2"}}


def _evidence():
    held = {
        "attemptId": "att_old",
        "leaseGeneration": 1,
        "workerPid": 101,
        "workerSessionId": "session_old",
    }
    restarted = {
        "workerId": "worker_1",
        "workerPid": 202,
        "workerSessionId": "session_new",
    }
    events = [
        _event(
            "run_attempt_claimed",
            jobId="job_1",
            attemptId="att_old",
            leaseGeneration=1,
            workerId="worker_1",
        ),
        _event("run_attempt_fenced", attemptId="att_old", leaseGeneration=1, reason="lease_expired"),
        _event("run_job_requeued", jobId="job_1", backoffSeconds=5, availableAt="2099-06-07T10:00:16Z"),
        _event(
            "run_control_plane_recovered",
            action="requeue_after_lease_expiry",
            reasonCode="LEASE_EXPIRED",
            jobId="job_1",
            attemptId="att_old",
            leaseGeneration=1,
            backoffSeconds=5,
            availableAt="2099-06-07T10:00:16Z",
        ),
        _event(
            "run_attempt_claimed",
            jobId="job_1",
            attemptId="att_new",
            leaseGeneration=2,
            workerId="worker_1",
        ),
    ]
    snapshot = {
        "attempts": [
            {
                "attempt_id": "att_old",
                "state": "fenced",
                "fenced_reason": "lease_expired",
                "output_adoption_state": "pending",
            },
            {
                "attempt_id": "att_new",
                "state": "succeeded",
                "fenced_reason": None,
                "output_adoption_state": "adopted",
            },
        ],
        "job": {"state": "completed", "attempt_count": 2},
        "lease": {
            "attempt_id": "att_new",
            "lease_generation": 2,
            "worker_id": "worker_1",
            "state": "completed",
        },
        "artifacts": [
            {
                "artifact_id": "art_1",
                "path": "/results/attempts/att_new/generation-2/summary.tsv",
                "sha256": "sha256:1",
            },
            {
                "artifact_id": "art_2",
                "path": "/results/attempts/att_new/generation-2/report.html",
                "sha256": "sha256:2",
            },
            {
                "artifact_id": "art_3",
                "path": "/results/attempts/att_new/generation-2/raw.log",
                "sha256": "sha256:3",
            },
        ],
        "candidates": [
            {"attempt_id": "att_new", "output_key": "summary", "adopted_artifact_id": "art_1"},
            {"attempt_id": "att_new", "output_key": "report", "adopted_artifact_id": "art_2"},
            {"attempt_id": "att_new", "output_key": "raw_log", "adopted_artifact_id": "art_3"},
        ],
        "outputEdges": [
            {"port_name": "summary", "content_hash": "sha256:1"},
            {"port_name": "report", "content_hash": "sha256:2"},
            {"port_name": "raw_log", "content_hash": "sha256:3"},
        ],
        "lineageCount": 3,
        "oldProcessGroupExists": False,
    }
    results = {
        "artifacts": [
            {
                "artifactId": "art_1",
                "path": "/results/attempts/att_new/generation-2/summary.tsv",
                "sha256": "sha256:1",
            },
            {
                "artifactId": "art_2",
                "path": "/results/attempts/att_new/generation-2/report.html",
                "sha256": "sha256:2",
            },
            {
                "artifactId": "art_3",
                "path": "/results/attempts/att_new/generation-2/raw.log",
                "sha256": "sha256:3",
            },
        ]
    }
    return held, restarted, events, snapshot, results


def test_build_run_submit_payload_pins_acceptance_run_id() -> None:
    payload = acceptance.build_run_submit_payload(
        run_id="run_acceptance",
        request_id="req_acceptance",
        server_id="srv_real",
        pipeline_id="file-summary-v1",
        upload={"uploadId": "upl_real", "filename": "sample.fastq"},
    )

    assert payload["serverId"] == "srv_real"
    assert payload["runSpec"]["runId"] == "run_acceptance"
    assert payload["runSpec"]["inputs"][0]["uploadId"] == "upl_real"
    assert payload["runSpec"]["execution"]["retryPolicy"]["backoffSeconds"] == 5


def test_validate_recovery_evidence_accepts_exactly_once_recovery() -> None:
    held, restarted, events, snapshot, results = _evidence()

    evidence = acceptance.validate_recovery_evidence(
        final_run={"runId": "run_acceptance", "status": "completed"},
        events=events,
        results=results,
        held=held,
        restarted=restarted,
        snapshot=snapshot,
    )

    assert evidence["leaseGenerations"] == [1, 2]
    assert evidence["artifactCount"] == 3
    assert evidence["fenceEventCount"] == 1
    assert evidence["retryBackoffSeconds"] == 5
    assert evidence["controlPlaneRecoveryEventCount"] == 1


def test_validate_recovery_evidence_accepts_run_event_v2_payload_shape() -> None:
    held, restarted, events, snapshot, results = _evidence()
    events = [
        _v2_event(event["eventType"], **event["detailsJson"])
        for event in events
    ]

    evidence = acceptance.validate_recovery_evidence(
        final_run={"runId": "run_acceptance", "status": "completed"},
        events=events,
        results=results,
        held=held,
        restarted=restarted,
        snapshot=snapshot,
    )

    assert evidence["newAttemptId"] == "att_new"


def test_validate_recovery_evidence_rejects_duplicate_fence_event() -> None:
    held, restarted, events, snapshot, results = _evidence()
    events.append(_event("run_attempt_fenced", attemptId="att_old", leaseGeneration=1, reason="lease_expired"))

    with pytest.raises(ValueError, match="EXPECTED_SINGLE_FENCE_EVENT"):
        acceptance.validate_recovery_evidence(
            final_run={"runId": "run_acceptance", "status": "completed"},
            events=events,
            results=results,
            held=held,
            restarted=restarted,
            snapshot=snapshot,
        )


def test_validate_recovery_evidence_rejects_missing_control_plane_recovery_event() -> None:
    held, restarted, events, snapshot, results = _evidence()
    events = [event for event in events if event["eventType"] != "run_control_plane_recovered"]

    with pytest.raises(ValueError, match="CONTROL_PLANE_RECOVERY_EVENT_MISSING"):
        acceptance.validate_recovery_evidence(
            final_run={"runId": "run_acceptance", "status": "completed"},
            events=events,
            results=results,
            held=held,
            restarted=restarted,
            snapshot=snapshot,
        )


def test_validate_recovery_evidence_rejects_fenced_attempt_adoption() -> None:
    held, restarted, events, snapshot, results = _evidence()
    snapshot["candidates"].append(
        {"attempt_id": "att_old", "output_key": "summary", "adopted_artifact_id": "art_stale"}
    )

    with pytest.raises(ValueError, match="FENCED_ATTEMPT_ADOPTED_OUTPUT"):
        acceptance.validate_recovery_evidence(
            final_run={"runId": "run_acceptance", "status": "completed"},
            events=events,
            results=results,
            held=held,
            restarted=restarted,
            snapshot=snapshot,
        )
