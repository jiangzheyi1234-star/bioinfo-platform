from __future__ import annotations

import pytest
from pydantic import ValidationError

from apps.remote_runner.api_models import (
    ArtifactCachePinReleaseRequest,
    ArtifactCachePinRetainRequest,
    ResultPackageExportRequest,
    RunCreateRequest,
    RunRetryRequest,
    ToolManifestRequest,
    ToolProductionEvidenceRequest,
    UploadCreateRequest,
    WorkflowBackfillCancelRequest,
    WorkflowDesignDraftCompileRequest,
    WorkflowTriggerBackfillLaunchRequest,
    WorkflowTriggerBackfillPreviewRequest,
    WorkflowTriggerInboxEventRequest,
    WorkflowTriggerInboxReplayRequest,
    WorkflowTriggerReadinessEventRequest,
)


def test_remote_runner_upload_request_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError) as exc_info:
        UploadCreateRequest.model_validate(
            {
                "filename": "reads.fastq",
                "contentBase64": "QEdPQgo=",
                "mimeType": "text/plain",
                "content": "@GO\n",
            }
        )

    assert exc_info.value.errors()[0]["type"] == "extra_forbidden"


def test_remote_runner_tool_manifest_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ToolManifestRequest.model_validate(
            {
                "name": "seqkit",
                "source": "bioconda",
                "deprecatedRuleSpec": {"inputs": []},
            }
        )

    assert exc_info.value.errors()[0]["type"] == "extra_forbidden"


def test_remote_runner_tool_manifest_accepts_profile_prepare_payload_identity() -> None:
    payload = ToolManifestRequest.model_validate(
        {
            "id": "bioconda::fastqc",
            "name": "fastqc",
            "source": "bioconda",
            "sourceLabel": "Bioconda",
            "profileId": "fastqc",
            "profileVersion": 1,
            "packId": "h2ometa-metagenomics-core",
            "packageName": "fastqc",
            "validationTarget": "fastqc",
            "latestVersion": "0.12.1",
            "version": "0.12.1",
            "packageSpec": "bioconda::fastqc=0.12.1",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": {"commandTemplate": "fastqc {input.reads:q}"},
            "ruleSpecDraft": {"source": "h2ometa-tool-profile"},
        }
    )

    assert payload.profileId == "fastqc"
    assert payload.validationTarget == "fastqc"


def test_remote_runner_tool_production_evidence_accepts_scoped_attestation_fields() -> None:
    payload = ToolProductionEvidenceRequest.model_validate(
        {
            "runId": "run_real_data",
            "message": "Accepted against real remote data.",
            "evidenceType": "real-database-acceptance",
            "targetPlatform": "linux-64",
            "environmentLock": {"manager": "conda"},
            "inputScope": {"inputs": [{"role": "reads", "filename": "reads.fastq"}]},
            "artifactDigest": "sha256:abc123",
            "policyVersion": "tool-production-policy-v1",
            "databaseId": "db_real",
            "templateId": "gtdbtk",
            "role": "taxonomy",
            "artifactName": "report.txt",
            "packId": "gtdbtk-r232",
            "packChecksum": "md5:abc123",
        }
    )

    assert payload.environmentLock == {"manager": "conda"}
    assert payload.packId == "gtdbtk-r232"

    with pytest.raises(ValidationError) as exc_info:
        ToolProductionEvidenceRequest.model_validate({"runId": "run_real_data", "serverId": "srv_legacy"})

    assert exc_info.value.errors()[0]["type"] == "extra_forbidden"


def test_remote_runner_run_request_requires_top_level_server_id() -> None:
    with pytest.raises(ValidationError) as exc_info:
        RunCreateRequest.model_validate(
            {
                "requestId": "req_demo",
                "runSpec": {"pipelineId": "file-summary-v1"},
            }
        )

    assert exc_info.value.errors()[0]["loc"] == ("serverId",)


def test_remote_runner_run_request_requires_pipeline_id_in_run_spec() -> None:
    with pytest.raises(ValidationError) as exc_info:
        RunCreateRequest.model_validate(
            {
                "serverId": "srv_demo",
                "requestId": "req_demo",
                "runSpec": {"inputs": []},
            }
        )

    assert exc_info.value.errors()[0]["loc"] == ("runSpec", "pipelineId")


def test_remote_runner_run_request_rejects_legacy_run_spec_server_id_as_extra_field() -> None:
    with pytest.raises(ValidationError) as exc_info:
        RunCreateRequest.model_validate(
            {
                "serverId": "srv_demo",
                "requestId": "req_demo",
                "runSpec": {"serverId": "srv_legacy", "pipelineId": "file-summary-v1"},
            }
        )

    assert exc_info.value.errors()[0]["type"] == "extra_forbidden"
    assert exc_info.value.errors()[0]["loc"] == ("runSpec", "serverId")


def test_remote_runner_run_request_preserves_run_spec_extensions() -> None:
    request = RunCreateRequest.model_validate(
        {
            "serverId": "srv_demo",
            "requestId": "req_demo",
            "runSpec": {"pipelineId": "file-summary-v1", "inputs": [], "workflowRevisionId": "wfrev_demo"},
        }
    )

    assert request.runSpec.pipelineId == "file-summary-v1"
    assert request.model_dump()["runSpec"]["inputs"] == []
    assert request.model_dump()["runSpec"]["workflowRevisionId"] == "wfrev_demo"


def test_remote_runner_run_retry_request_is_strict() -> None:
    request = RunRetryRequest.model_validate({"scope": "run", "actor": "operator"})

    assert request.scope == "run"
    assert request.actor == "operator"

    with pytest.raises(ValidationError) as exc_info:
        RunRetryRequest.model_validate({"scope": "rule", "stepId": "node_fastqc"})

    errors = exc_info.value.errors()
    assert any(error["type"] == "literal_error" and error["loc"] == ("scope",) for error in errors)
    assert any(error["type"] == "extra_forbidden" and error["loc"] == ("stepId",) for error in errors)


def test_remote_runner_result_package_export_request_requires_explicit_payload_mode() -> None:
    request = ResultPackageExportRequest.model_validate(
        {"includeArtifacts": True, "actor": "operator"}
    )

    assert request.includeArtifacts is True
    assert request.actor == "operator"

    with pytest.raises(ValidationError) as missing:
        ResultPackageExportRequest.model_validate({"actor": "operator"})
    with pytest.raises(ValidationError) as extra:
        ResultPackageExportRequest.model_validate({"includeArtifacts": False, "mode": "metadata"})
    with pytest.raises(ValidationError) as non_boolean:
        ResultPackageExportRequest.model_validate({"includeArtifacts": 0})

    assert missing.value.errors()[0]["loc"] == ("includeArtifacts",)
    assert extra.value.errors()[0]["type"] == "extra_forbidden"
    assert extra.value.errors()[0]["loc"] == ("mode",)
    assert non_boolean.value.errors()[0]["loc"] == ("includeArtifacts",)
    assert non_boolean.value.errors()[0]["type"] == "bool_type"


def test_remote_runner_artifact_cache_pin_requests_are_strict_and_confirmation_gated() -> None:
    retain = ArtifactCachePinRetainRequest.model_validate(
        {
            "ownerId": "curator@example.test",
            "reason": "retain-for-review",
            "expiresAt": "2099-06-07T10:00:00Z",
            "actor": "curator@example.test",
        }
    )
    release = ArtifactCachePinReleaseRequest.model_validate(
        {"confirmation": "release-artifact-cache-policy-pin", "reason": "review-complete"}
    )

    assert retain.ownerId == "curator@example.test"
    assert release.confirmation == "release-artifact-cache-policy-pin"

    with pytest.raises(ValidationError) as retain_extra:
        ArtifactCachePinRetainRequest.model_validate({"reason": "retain", "legacy": True})
    with pytest.raises(ValidationError) as release_confirmation:
        ArtifactCachePinReleaseRequest.model_validate({"confirmation": "release-cache-pin"})

    assert retain_extra.value.errors()[0]["type"] == "extra_forbidden"
    assert retain_extra.value.errors()[0]["loc"] == ("legacy",)
    assert release_confirmation.value.errors()[0]["type"] == "literal_error"
    assert release_confirmation.value.errors()[0]["loc"] == ("confirmation",)


def test_remote_runner_workflow_trigger_inbox_event_request_is_strict() -> None:
    request = WorkflowTriggerInboxEventRequest.model_validate(
        {
            "eventType": "dataset.ready",
            "source": "instrument-qc",
            "eventId": "evt_001",
            "correlationId": "batch_42",
            "actor": "instrument-agent",
            "payload": {"dataset": "reads.fastq"},
        }
    )

    assert request.source == "instrument-qc"
    assert request.eventId == "evt_001"
    assert request.payload == {"dataset": "reads.fastq"}

    with pytest.raises(ValidationError) as exc_info:
        WorkflowTriggerInboxEventRequest.model_validate({"eventId": "evt_001", "legacyPayload": {}})

    errors = exc_info.value.errors()
    assert any(error["type"] == "missing" and error["loc"] == ("source",) for error in errors)
    assert any(error["type"] == "extra_forbidden" and error["loc"] == ("legacyPayload",) for error in errors)


def test_remote_runner_workflow_trigger_inbox_replay_request_requires_confirmation() -> None:
    request = WorkflowTriggerInboxReplayRequest.model_validate(
        {
            "confirmation": "replay-dead-lettered-inbox-event",
            "actor": "operator",
            "reason": "queue restored",
        }
    )

    assert request.confirmation == "replay-dead-lettered-inbox-event"
    assert request.actor == "operator"

    with pytest.raises(ValidationError) as exc_info:
        WorkflowTriggerInboxReplayRequest.model_validate(
            {
                "confirmation": "retry",
                "force": True,
            }
        )

    errors = exc_info.value.errors()
    assert any(error["type"] == "literal_error" and error["loc"] == ("confirmation",) for error in errors)
    assert any(error["type"] == "extra_forbidden" and error["loc"] == ("force",) for error in errors)


def test_remote_runner_workflow_trigger_backfill_preview_request_is_strict() -> None:
    request = WorkflowTriggerBackfillPreviewRequest.model_validate(
        {
            "rangeStart": "2026-06-01T00:00:00Z",
            "rangeEnd": "2026-06-01T03:00:00Z",
            "partitionUnit": "hour",
            "timezone": "UTC",
            "maxPartitions": 2,
            "concurrencyLimit": 1,
            "runOrder": "backward",
            "reprocessBehavior": "completed",
            "params": {"sampleBatch": "batch_42"},
        }
    )

    assert request.partitionUnit == "hour"
    assert request.runOrder == "backward"
    assert request.reprocessBehavior == "completed"
    assert request.maxPartitions == 2

    with pytest.raises(ValidationError) as exc_info:
        WorkflowTriggerBackfillPreviewRequest.model_validate(
            {
                "rangeStart": "2026-06-01",
                "rangeEnd": "2026-06-04",
                "partitionUnit": "week",
                "runOrder": "reverse",
                "reprocessBehavior": "always",
                "maxPartitions": 0,
                "concurrencyLimit": 101,
                "legacyLaunch": {},
            }
        )

    errors = exc_info.value.errors()
    assert any(error["type"] == "literal_error" and error["loc"] == ("partitionUnit",) for error in errors)
    assert any(error["type"] == "literal_error" and error["loc"] == ("runOrder",) for error in errors)
    assert any(error["type"] == "literal_error" and error["loc"] == ("reprocessBehavior",) for error in errors)
    assert any(error["type"] == "greater_than_equal" and error["loc"] == ("maxPartitions",) for error in errors)
    assert any(error["type"] == "less_than_equal" and error["loc"] == ("concurrencyLimit",) for error in errors)
    assert any(error["type"] == "extra_forbidden" and error["loc"] == ("legacyLaunch",) for error in errors)


def test_remote_runner_workflow_trigger_backfill_launch_request_requires_confirmation() -> None:
    request = WorkflowTriggerBackfillLaunchRequest.model_validate(
        {
            "rangeStart": "2026-06-01",
            "rangeEnd": "2026-06-02",
            "confirmation": "launch-backfill",
            "actor": "operator",
        }
    )

    assert request.confirmation == "launch-backfill"
    assert request.actor == "operator"

    with pytest.raises(ValidationError) as exc_info:
        WorkflowTriggerBackfillLaunchRequest.model_validate(
            {
                "rangeStart": "2026-06-01",
                "rangeEnd": "2026-06-02",
                "confirmation": "launch",
                "legacyLaunch": True,
            }
        )

    errors = exc_info.value.errors()
    assert any(error["type"] == "literal_error" and error["loc"] == ("confirmation",) for error in errors)
    assert any(error["type"] == "extra_forbidden" and error["loc"] == ("legacyLaunch",) for error in errors)


def test_remote_runner_workflow_backfill_cancel_request_requires_confirmation() -> None:
    request = WorkflowBackfillCancelRequest.model_validate(
        {
            "confirmation": "cancel-backfill",
            "actor": "operator",
        }
    )

    assert request.confirmation == "cancel-backfill"
    assert request.actor == "operator"

    with pytest.raises(ValidationError) as exc_info:
        WorkflowBackfillCancelRequest.model_validate(
            {
                "confirmation": "cancel",
                "legacyCancel": True,
            }
        )

    errors = exc_info.value.errors()
    assert any(error["type"] == "literal_error" and error["loc"] == ("confirmation",) for error in errors)
    assert any(error["type"] == "extra_forbidden" and error["loc"] == ("legacyCancel",) for error in errors)


def test_remote_runner_workflow_trigger_readiness_event_request_is_strict() -> None:
    request = WorkflowTriggerReadinessEventRequest.model_validate(
        {
            "source": "watcher",
            "eventId": "evt_file_ready_001",
            "resourceType": "file",
            "resourceId": "file:/incoming/reads.fastq",
            "state": "ready",
            "cursor": "file:/incoming/reads.fastq@sha256:abc",
            "payload": {"size": 128},
        }
    )

    assert request.resourceType == "file"
    assert request.cursor == "file:/incoming/reads.fastq@sha256:abc"
    assert request.payload == {"size": 128}

    with pytest.raises(ValidationError) as exc_info:
        WorkflowTriggerReadinessEventRequest.model_validate(
            {
                "source": "watcher",
                "eventId": "evt_file_ready_001",
                "resourceType": "directory",
                "resourceId": "file:/incoming/reads.fastq",
                "state": "missing",
                "legacyPayload": {},
            }
        )

    errors = exc_info.value.errors()
    assert any(error["type"] == "literal_error" and error["loc"] == ("resourceType",) for error in errors)
    assert any(error["type"] == "literal_error" and error["loc"] == ("state",) for error in errors)
    assert any(error["type"] == "extra_forbidden" and error["loc"] == ("legacyPayload",) for error in errors)


def test_remote_runner_workflow_design_compile_request_rejects_server_id() -> None:
    request = WorkflowDesignDraftCompileRequest.model_validate({})

    assert request.model_dump() == {}

    with pytest.raises(ValidationError) as exc_info:
        WorkflowDesignDraftCompileRequest.model_validate({"serverId": "srv_demo"})

    assert exc_info.value.errors()[0]["type"] == "extra_forbidden"
