from __future__ import annotations

import json
from typing import Any

from apps.remote_runner.artifact_lifecycle_controller import (
    ARTIFACT_LIFECYCLE_CONTROLLER_EVENT_TYPE,
    ARTIFACT_LIFECYCLE_CONTROLLER_MODE,
    ARTIFACT_LIFECYCLE_CONTROLLER_SCHEMA,
)
from apps.remote_runner.artifact_lifecycle_controller_read_model import (
    ARTIFACT_LIFECYCLE_CONTROLLER_TICK_READ_MODEL_SCHEMA,
    list_artifact_lifecycle_controller_ticks,
)
from apps.remote_runner.evidence_storage import append_evidence_event
from apps.remote_runner.storage_core import get_connection
from tests.helpers.reference_database import make_configured_remote_runner


def test_artifact_lifecycle_controller_tick_read_model_is_empty_without_ticks(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)

    model = list_artifact_lifecycle_controller_ticks(cfg)

    assert model == {
        "schemaVersion": ARTIFACT_LIFECYCLE_CONTROLLER_TICK_READ_MODEL_SCHEMA,
        "items": [],
    }


def test_artifact_lifecycle_controller_tick_read_model_is_newest_first_and_public(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    older = _append_controller_tick(cfg, "alct_old", evaluated_at="2099-01-01T00:00:00Z")
    newer = _append_controller_tick(cfg, "alct_new", evaluated_at="2099-01-02T00:00:00Z")

    model = list_artifact_lifecycle_controller_ticks(cfg, limit=10)

    assert model["schemaVersion"] == ARTIFACT_LIFECYCLE_CONTROLLER_TICK_READ_MODEL_SCHEMA
    assert [item["tickId"] for item in model["items"]] == ["alct_new", "alct_old"]
    assert model["items"][0]["evidenceId"] == newer["eventId"]
    assert model["items"][1]["evidenceId"] == older["eventId"]
    assert model["items"][0]["executionMode"] == "preview-only"
    assert model["items"][0]["deleteConfirmationRequired"] is True
    assert model["items"][0]["policy"] == {
        "retentionDays": 7,
        "eligibleRunStatuses": ["completed", "failed"],
        "quotaBytes": 1000,
        "maxDeleteBytesPerTick": 100,
    }
    assert model["items"][0]["gcPreview"] == {
        "planId": "agc_alct_new",
        "candidateCount": 1,
        "deleteBytes": 25,
        "protectedCount": 1,
        "protectedBytes": 50,
        "candidateArtifactCount": 1,
        "candidateRunCount": 1,
    }

    keys = _all_keys(model)
    assert not {
        "path",
        "storageUri",
        "localPath",
        "groupId",
        "candidateGroupIds",
        "candidates",
        "protected",
        "cacheKey",
        "packagePath",
        "packageUri",
    }.intersection(keys)
    serialized = json.dumps(model, sort_keys=True)
    assert "C:/secret" not in serialized
    assert "file:///secret" not in serialized
    assert "acache_secret" not in serialized


def _append_controller_tick(cfg, tick_id: str, *, evaluated_at: str) -> dict[str, Any]:
    payload = {
        "schemaVersion": ARTIFACT_LIFECYCLE_CONTROLLER_SCHEMA,
        "tickId": tick_id,
        "evaluatedAt": evaluated_at,
        "executionMode": ARTIFACT_LIFECYCLE_CONTROLLER_MODE,
        "deleteConfirmationRequired": True,
        "policy": {
            "retentionDays": 7,
            "eligibleRunStatuses": ["completed", "failed"],
            "quotaBytes": 1000,
            "maxDeleteBytesPerTick": 100,
            "reason": "C:/secret/operator-note",
        },
        "usage": {
            "activeBytes": 2000,
            "activeStorageObjectCount": 2,
            "quotaOverageBytes": 1000,
            "storageUri": "file:///secret/usage",
        },
        "policyDecision": {
            "decision": "preview_ready",
            "reasonCode": "DELETE_CONFIRMATION_REQUIRED",
            "message": "GC candidates are available, but the controller is preview-only.",
            "deletionAuthorized": False,
            "deleteConfirmationRequired": True,
            "candidateCount": 1,
            "deleteBytes": 25,
        },
        "retentionHolds": {
            "schemaVersion": "artifact-retention-hold-summary.v1",
            "protectedGroupCount": 1,
            "protectedBytes": 50,
            "reasonCount": 1,
            "reasons": [
                {
                    "reason": "export_package",
                    "groupCount": 1,
                    "artifactCount": 1,
                    "runCount": 1,
                    "bytes": 50,
                    "path": "C:/secret/held.txt",
                }
            ],
            "protected": [{"storageUri": "file:///secret/protected"}],
        },
        "batchSafety": {
            "schemaVersion": "artifact-gc-batch-safety.v1",
            "maxDeleteBytes": 100,
            "maxDeleteBytesApplied": True,
            "candidateCount": 1,
            "candidateBytes": 25,
            "candidateArtifactCount": 1,
            "candidateRunCount": 1,
            "limitedGroupCount": 1,
            "limitedBytes": 50,
        },
        "gcPreview": {
            "planId": f"agc_{tick_id}",
            "candidateCount": 1,
            "deleteBytes": 25,
            "protectedCount": 1,
            "protectedBytes": 50,
            "candidateArtifactCount": 1,
            "candidateRunCount": 1,
            "candidateGroupIds": ["grp_secret"],
            "candidates": [{"path": "C:/secret/delete.txt", "cacheKey": "acache_secret"}],
            "protected": [{"storageUri": "file:///secret/protected"}],
        },
        "path": "C:/secret/top.txt",
        "storageUri": "file:///secret/top.txt",
    }
    with get_connection(cfg) as connection:
        event = append_evidence_event(
            connection,
            event_type=ARTIFACT_LIFECYCLE_CONTROLLER_EVENT_TYPE,
            schema_name="ArtifactLifecycleControllerTick",
            subject_kind="artifact_lifecycle_controller",
            subject_id=tick_id,
            payload=payload,
            producer="artifact_lifecycle_controller",
            occurred_at=evaluated_at,
        )
        connection.commit()
    return event


def _all_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | set().union(*(_all_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_all_keys(item) for item in value))
    return set()
