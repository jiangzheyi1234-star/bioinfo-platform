from __future__ import annotations

from typing import Any


EXPECTED_ARTIFACT_COUNT = 3


def event_details(event: dict[str, Any]) -> dict[str, Any]:
    details = event.get("detailsJson")
    if not isinstance(details, dict):
        return {}
    payload = details.get("payload")
    return payload if isinstance(payload, dict) else details


def recovery_claims(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        event_details(event)
        for event in events
        if event.get("eventType") == "run_attempt_claimed"
    ]


def validate_recovery_evidence(
    *,
    final_run: dict[str, Any],
    events: list[dict[str, Any]],
    results: dict[str, Any],
    held: dict[str, Any],
    restarted: dict[str, Any],
    snapshot: dict[str, Any],
    expected_artifact_count: int = EXPECTED_ARTIFACT_COUNT,
) -> dict[str, Any]:
    if final_run.get("status") != "completed":
        raise ValueError(f"RUN_NOT_COMPLETED: {final_run.get('status')}")
    if restarted["workerPid"] == held["workerPid"]:
        raise ValueError("WORKER_PID_DID_NOT_CHANGE")
    if restarted["workerSessionId"] == held["workerSessionId"]:
        raise ValueError("WORKER_SESSION_DID_NOT_CHANGE")

    claims = recovery_claims(events)
    if len(claims) != 2:
        raise ValueError(f"EXPECTED_TWO_ATTEMPT_CLAIMS: {len(claims)}")
    first_claim, second_claim = claims
    if first_claim.get("attemptId") != held["attemptId"]:
        raise ValueError("HELD_ATTEMPT_DOES_NOT_MATCH_FIRST_CLAIM")
    if int(first_claim.get("leaseGeneration") or 0) != int(held["leaseGeneration"]):
        raise ValueError("HELD_GENERATION_DOES_NOT_MATCH_FIRST_CLAIM")
    if int(second_claim.get("leaseGeneration") or 0) != int(held["leaseGeneration"]) + 1:
        raise ValueError("LEASE_GENERATION_DID_NOT_INCREMENT")
    if second_claim.get("workerId") != restarted.get("workerId"):
        raise ValueError("RECOVERY_CLAIMED_BY_UNEXPECTED_WORKER")
    if first_claim.get("jobId") != second_claim.get("jobId"):
        raise ValueError("RECOVERY_CLAIMS_REFERENCE_DIFFERENT_JOBS")

    fence_events = [
        event
        for event in events
        if event.get("eventType") == "run_attempt_fenced"
        and event_details(event).get("attemptId") == held["attemptId"]
    ]
    if len(fence_events) != 1:
        raise ValueError(f"EXPECTED_SINGLE_FENCE_EVENT: {len(fence_events)}")
    if event_details(fence_events[0]).get("reason") != "lease_expired":
        raise ValueError("FIRST_ATTEMPT_NOT_FENCED_FOR_LEASE_EXPIRY")
    requeue_events = [event for event in events if event.get("eventType") == "run_job_requeued"]
    if len(requeue_events) != 1:
        raise ValueError(f"EXPECTED_SINGLE_REQUEUE_EVENT: {len(requeue_events)}")
    if event_details(requeue_events[0]).get("jobId") != second_claim.get("jobId"):
        raise ValueError("REQUEUE_EVENT_REFERENCES_UNEXPECTED_JOB")

    attempts = list(snapshot.get("attempts") or [])
    if len(attempts) != 2:
        raise ValueError(f"EXPECTED_TWO_ATTEMPTS: {len(attempts)}")
    first_attempt, second_attempt = attempts
    if first_attempt.get("attempt_id") != held["attemptId"] or first_attempt.get("state") != "fenced":
        raise ValueError("FIRST_ATTEMPT_NOT_FENCED")
    if first_attempt.get("fenced_reason") != "lease_expired":
        raise ValueError("FIRST_ATTEMPT_FENCE_REASON_INVALID")
    if first_attempt.get("output_adoption_state") == "adopted":
        raise ValueError("FENCED_ATTEMPT_MARKED_ADOPTED")
    if second_attempt.get("attempt_id") != second_claim.get("attemptId") or second_attempt.get("state") != "succeeded":
        raise ValueError("SECOND_ATTEMPT_NOT_SUCCEEDED")
    if second_attempt.get("output_adoption_state") != "adopted":
        raise ValueError("SECOND_ATTEMPT_OUTPUTS_NOT_ADOPTED")

    lease = snapshot.get("lease") or {}
    if lease.get("attempt_id") != second_claim.get("attemptId"):
        raise ValueError("FINAL_LEASE_REFERENCES_UNEXPECTED_ATTEMPT")
    if int(lease.get("lease_generation") or 0) != int(second_claim.get("leaseGeneration") or 0):
        raise ValueError("FINAL_LEASE_GENERATION_MISMATCH")
    if lease.get("state") != "completed":
        raise ValueError("FINAL_LEASE_NOT_COMPLETED")

    artifacts = list(results.get("artifacts") or [])
    stored_artifacts = list(snapshot.get("artifacts") or [])
    output_edges = list(snapshot.get("outputEdges") or [])
    if len(artifacts) != expected_artifact_count or len(stored_artifacts) != expected_artifact_count:
        raise ValueError("ARTIFACT_COUNT_MISMATCH")
    api_artifacts = {item.get("artifactId"): item.get("sha256") for item in artifacts}
    db_artifacts = {item.get("artifact_id"): item.get("sha256") for item in stored_artifacts}
    if len(api_artifacts) != expected_artifact_count:
        raise ValueError("DUPLICATE_RESULT_ARTIFACT")
    if api_artifacts != db_artifacts:
        raise ValueError("API_DATABASE_ARTIFACT_MISMATCH")
    expected_path_fragment = (
        f"/attempts/{second_claim['attemptId']}/generation-{int(second_claim['leaseGeneration'])}/"
    )
    if any(expected_path_fragment not in str(item.get("path") or "").replace("\\", "/") for item in artifacts):
        raise ValueError("ARTIFACT_PATH_NOT_ATTEMPT_SCOPED")
    if len(output_edges) != expected_artifact_count:
        raise ValueError("OUTPUT_EDGE_COUNT_MISMATCH")
    if len({item.get("port_name") for item in output_edges}) != expected_artifact_count:
        raise ValueError("OUTPUT_ADOPTED_MORE_THAN_ONCE")
    if {item.get("content_hash") for item in output_edges} != set(api_artifacts.values()):
        raise ValueError("OUTPUT_EDGE_ARTIFACT_HASH_MISMATCH")
    if int(snapshot.get("lineageCount") or 0) != expected_artifact_count:
        raise ValueError("LINEAGE_COUNT_MISMATCH")
    if snapshot.get("oldProcessGroupExists") is not False:
        raise ValueError("OLD_PROCESS_GROUP_STILL_EXISTS")

    candidates = list(snapshot.get("candidates") or [])
    old_adoptions = [
        item for item in candidates
        if item.get("attempt_id") == held["attemptId"] and item.get("adopted_artifact_id")
    ]
    new_adoptions = [
        item for item in candidates
        if item.get("attempt_id") == second_claim.get("attemptId") and item.get("adopted_artifact_id")
    ]
    if old_adoptions:
        raise ValueError("FENCED_ATTEMPT_ADOPTED_OUTPUT")
    if len(new_adoptions) != expected_artifact_count:
        raise ValueError("CURRENT_ATTEMPT_ADOPTION_COUNT_MISMATCH")
    if {item.get("adopted_artifact_id") for item in new_adoptions} != set(api_artifacts):
        raise ValueError("CANDIDATE_ARTIFACT_SET_MISMATCH")
    if snapshot.get("job", {}).get("state") != "completed":
        raise ValueError("RUN_JOB_NOT_COMPLETED")
    if int(snapshot.get("job", {}).get("attempt_count") or 0) != 2:
        raise ValueError("RUN_JOB_ATTEMPT_COUNT_MISMATCH")

    return {
        "runId": final_run["runId"],
        "jobId": second_claim["jobId"],
        "oldAttemptId": held["attemptId"],
        "newAttemptId": second_claim["attemptId"],
        "oldWorkerPid": held["workerPid"],
        "newWorkerPid": restarted["workerPid"],
        "oldWorkerSessionId": held["workerSessionId"],
        "newWorkerSessionId": restarted["workerSessionId"],
        "leaseGenerations": [held["leaseGeneration"], second_claim["leaseGeneration"]],
        "artifactCount": len(artifacts),
        "lineageCount": snapshot["lineageCount"],
        "fenceEventCount": len(fence_events),
        "requeueEventCount": len(requeue_events),
    }
