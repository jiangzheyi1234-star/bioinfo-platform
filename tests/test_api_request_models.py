from __future__ import annotations

import pytest
from pydantic import ValidationError

from apps.api.models import (
    ArtifactCachePinReleaseRequest,
    ArtifactCachePinRetainRequest,
    ArtifactLifecycleControllerRunOnceRequest,
    ResultPackageByteDeleteRequest,
    ResultPackageExportRequest,
    ResultPackageRetireRequest,
    RunResumeRequest,
    RunRuleCacheRestoreAdoptionApplyRequest,
    RunRuleCacheRestoreAdoptionPrepareRequest,
    RunRuleCacheRestoreFinalOutputApplyRequest,
    RunRuleCacheRestoreFinalOutputPrepareRequest,
    RunRuleCacheRestorePinApplyRequest,
    RunRuleCacheRestorePinPrepareRequest,
    RunRuleCacheRestoreStagedFileApplyRequest,
    RunRuleCacheRestoreStagedFilePrepareRequest,
    RunSubmitRequest,
    RunRetryRequest,
    RunRuleOutputInvalidationApplyRequest,
    RunRuleRetryRequest,
    TERMINAL_CLIENT_MESSAGE_ADAPTER,
    TerminalInputMessage,
    TerminalPingMessage,
    TerminalResizeMessage,
    TerminalSessionSnapshot,
    ToolManifestRequest,
    ToolProductionEvidenceRequest,
    UploadSubmitRequest,
    WorkflowBackfillCancelRequest,
    WorkflowDesignDraftCreateRequest,
    WorkflowDesignDraftCompileRequest,
    WorkflowTriggerBackfillLaunchRequest,
    WorkflowTriggerBackfillPreviewRequest,
    WorkflowTriggerCreateRequest,
    WorkflowTriggerEventRequest,
    WorkflowTriggerInboxEventRequest,
    WorkflowTriggerInboxReplayRequest,
    WorkflowTriggerReadinessEventRequest,
    WorkflowTriggerSchedulerRunOnceRequest,
)


def test_upload_submit_request_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError) as exc_info:
        UploadSubmitRequest.model_validate(
            {
                "serverId": "srv_demo",
                "filename": "reads.fastq",
                "contentBase64": "QEdPQgo=",
                "mimeType": "text/plain",
                "content": "@GO\n",
            }
        )

    assert exc_info.value.errors()[0]["type"] == "extra_forbidden"


def test_tool_manifest_request_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ToolManifestRequest.model_validate(
            {
                "serverId": "srv_demo",
                "name": "seqkit",
                "source": "bioconda",
                "deprecatedRuleSpec": {"inputs": []},
            }
        )

    assert exc_info.value.errors()[0]["type"] == "extra_forbidden"


def test_tool_manifest_request_accepts_profile_prepare_payload_identity() -> None:
    payload = ToolManifestRequest.model_validate(
        {
            "serverId": "srv_demo",
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


def test_tool_production_evidence_request_accepts_scoped_attestation_fields() -> None:
    payload = ToolProductionEvidenceRequest.model_validate(
        {
            "serverId": "srv_demo",
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

    assert payload.inputScope == {"inputs": [{"role": "reads", "filename": "reads.fastq"}]}
    assert payload.packChecksum == "md5:abc123"

    with pytest.raises(ValidationError) as exc_info:
        ToolProductionEvidenceRequest.model_validate({"runId": "run_real_data", "legacyEvidence": {}})

    assert exc_info.value.errors()[0]["type"] == "extra_forbidden"


def test_run_submit_request_rejects_top_level_pipeline_id_as_extra_field() -> None:
    with pytest.raises(ValidationError) as exc_info:
        RunSubmitRequest.model_validate(
            {
                "serverId": "srv_demo",
                "pipelineId": "file-summary-v1",
                "runSpec": {"inputs": []},
            }
        )

    errors = exc_info.value.errors()
    assert any(error["type"] == "extra_forbidden" and error["loc"] == ("pipelineId",) for error in errors)
    assert any(error["type"] == "missing" and error["loc"] == ("runSpec", "pipelineId") for error in errors)


def test_run_submit_request_rejects_legacy_run_spec_server_id_as_extra_field() -> None:
    with pytest.raises(ValidationError) as exc_info:
        RunSubmitRequest.model_validate(
            {
                "serverId": "srv_demo",
                "runSpec": {"serverId": "srv_legacy", "pipelineId": "file-summary-v1"},
            }
        )

    assert exc_info.value.errors()[0]["type"] == "extra_forbidden"
    assert exc_info.value.errors()[0]["loc"] == ("runSpec", "serverId")


def test_run_submit_request_accepts_pipeline_id_inside_run_spec() -> None:
    request = RunSubmitRequest.model_validate(
        {
            "serverId": "srv_demo",
            "runSpec": {"pipelineId": "file-summary-v1", "inputs": [], "workflowRevisionId": "wfrev_demo"},
        }
    )

    assert request.serverId == "srv_demo"
    assert request.runSpec.pipelineId == "file-summary-v1"
    assert request.model_dump()["runSpec"]["inputs"] == []
    assert request.model_dump()["runSpec"]["workflowRevisionId"] == "wfrev_demo"


def test_run_submit_request_accepts_explicit_execution_queue() -> None:
    request = RunSubmitRequest.model_validate(
        {
            "serverId": "srv_demo",
            "runSpec": {
                "pipelineId": "file-summary-v1",
                "execution": {"queueName": "short"},
            },
        }
    )

    assert request.model_dump()["runSpec"]["execution"] == {"queueName": "short"}


def test_run_retry_request_is_strict_and_run_scoped() -> None:
    request = RunRetryRequest.model_validate(
        {
            "scope": "run",
            "actor": "operator",
            "reason": "rerun after fixing input",
        }
    )

    assert request.scope == "run"
    assert request.actor == "operator"

    with pytest.raises(ValidationError) as exc_info:
        RunRetryRequest.model_validate({"scope": "rule", "ruleName": "align_reads"})

    errors = exc_info.value.errors()
    assert any(error["type"] == "literal_error" and error["loc"] == ("scope",) for error in errors)
    assert any(error["type"] == "extra_forbidden" and error["loc"] == ("ruleName",) for error in errors)


def test_run_rule_retry_request_requires_confirmation_and_plan_hash() -> None:
    request = RunRuleRetryRequest.model_validate(
        {
            "confirmation": "retry-failed-rules",
            "planHash": "a" * 64,
            "actor": "operator",
            "reason": "operator approved safe retry plan",
        }
    )

    assert request.confirmation == "retry-failed-rules"
    assert request.planHash == "a" * 64

    with pytest.raises(ValidationError) as wrong_confirmation:
        RunRuleRetryRequest.model_validate({"confirmation": "retry-rule", "planHash": "a" * 64})
    with pytest.raises(ValidationError) as short_hash:
        RunRuleRetryRequest.model_validate({"confirmation": "retry-failed-rules", "planHash": "abc"})
    with pytest.raises(ValidationError) as extra:
        RunRuleRetryRequest.model_validate(
            {"confirmation": "retry-failed-rules", "planHash": "a" * 64, "ruleName": "align_reads"}
        )

    assert any(
        error["type"] == "literal_error" and error["loc"] == ("confirmation",)
        for error in wrong_confirmation.value.errors()
    )
    assert any(error["type"] == "string_too_short" and error["loc"] == ("planHash",) for error in short_hash.value.errors())
    assert any(error["type"] == "extra_forbidden" and error["loc"] == ("ruleName",) for error in extra.value.errors())


def test_run_rule_output_invalidation_apply_request_requires_confirmation_and_plan_hash() -> None:
    request = RunRuleOutputInvalidationApplyRequest.model_validate(
        {
            "confirmation": "apply-rule-output-invalidation",
            "planHash": "c" * 64,
            "actor": "operator",
            "reason": "operator reviewed output scope",
        }
    )

    assert request.confirmation == "apply-rule-output-invalidation"
    assert request.planHash == "c" * 64

    with pytest.raises(ValidationError) as wrong_confirmation:
        RunRuleOutputInvalidationApplyRequest.model_validate(
            {"confirmation": "invalidate-output", "planHash": "c" * 64}
        )
    with pytest.raises(ValidationError) as short_hash:
        RunRuleOutputInvalidationApplyRequest.model_validate(
            {"confirmation": "apply-rule-output-invalidation", "planHash": "abc"}
        )
    with pytest.raises(ValidationError) as extra:
        RunRuleOutputInvalidationApplyRequest.model_validate(
            {
                "confirmation": "apply-rule-output-invalidation",
                "planHash": "c" * 64,
                "deleteArtifactPayloads": True,
            }
        )

    assert any(
        error["type"] == "literal_error" and error["loc"] == ("confirmation",)
        for error in wrong_confirmation.value.errors()
    )
    assert any(error["type"] == "string_too_short" and error["loc"] == ("planHash",) for error in short_hash.value.errors())
    assert any(
        error["type"] == "extra_forbidden" and error["loc"] == ("deleteArtifactPayloads",)
        for error in extra.value.errors()
    )


def test_run_rule_cache_restore_pin_requests_require_confirmation_plan_hash_and_lease() -> None:
    prepare = RunRuleCacheRestorePinPrepareRequest.model_validate(
        {"confirmation": "prepare-rule-cache-restore-pins", "planHash": "d" * 64, "attemptId": "att_1", "leaseGeneration": 1}
    )
    apply = RunRuleCacheRestorePinApplyRequest.model_validate(
        {"confirmation": "apply-rule-cache-restore-pins", "planHash": "e" * 64, "attemptId": "att_1", "leaseGeneration": 1}
    )
    assert prepare.confirmation == "prepare-rule-cache-restore-pins"
    assert apply.confirmation == "apply-rule-cache-restore-pins"
    for model, confirmation in (
        (RunRuleCacheRestorePinPrepareRequest, "prepare-rule-cache-restore-pins"),
        (RunRuleCacheRestorePinApplyRequest, "apply-rule-cache-restore-pins"),
    ):
        with pytest.raises(ValidationError):
            model.model_validate({"confirmation": "restore-pins", "planHash": "f" * 64, "attemptId": "att_1", "leaseGeneration": 1})
        with pytest.raises(ValidationError):
            model.model_validate({"confirmation": confirmation, "planHash": "abc", "attemptId": "att_1", "leaseGeneration": 1})
        with pytest.raises(ValidationError):
            model.model_validate({"confirmation": confirmation, "planHash": "f" * 64, "attemptId": "att_1", "leaseGeneration": 0})
        with pytest.raises(ValidationError):
            model.model_validate({"confirmation": confirmation, "planHash": "f" * 64, "attemptId": "att_1", "leaseGeneration": 1, "pinIds": []})


def test_run_rule_cache_restore_staged_file_requests_require_confirmation_plan_hash_and_lease() -> None:
    prepare = RunRuleCacheRestoreStagedFilePrepareRequest.model_validate(
        {
            "confirmation": "prepare-rule-cache-restore-staged-files",
            "planHash": "d" * 64,
            "attemptId": "att_1",
            "leaseGeneration": 1,
        }
    )
    apply = RunRuleCacheRestoreStagedFileApplyRequest.model_validate(
        {
            "confirmation": "apply-rule-cache-restore-staged-files",
            "planHash": "e" * 64,
            "attemptId": "att_1",
            "leaseGeneration": 1,
        }
    )
    assert prepare.confirmation == "prepare-rule-cache-restore-staged-files"
    assert apply.confirmation == "apply-rule-cache-restore-staged-files"
    for model, confirmation in (
        (RunRuleCacheRestoreStagedFilePrepareRequest, "prepare-rule-cache-restore-staged-files"),
        (RunRuleCacheRestoreStagedFileApplyRequest, "apply-rule-cache-restore-staged-files"),
    ):
        with pytest.raises(ValidationError):
            model.model_validate(
                {
                    "confirmation": "restore-staged-files",
                    "planHash": "f" * 64,
                    "attemptId": "att_1",
                    "leaseGeneration": 1,
                }
            )
        with pytest.raises(ValidationError):
            model.model_validate(
                {"confirmation": confirmation, "planHash": "abc", "attemptId": "att_1", "leaseGeneration": 1}
            )
        with pytest.raises(ValidationError):
            model.model_validate(
                {"confirmation": confirmation, "planHash": "f" * 64, "attemptId": "att_1", "leaseGeneration": 0}
            )
        with pytest.raises(ValidationError):
            model.model_validate(
                {
                    "confirmation": confirmation,
                    "planHash": "f" * 64,
                    "attemptId": "att_1",
                    "leaseGeneration": 1,
                    "targetPath": "leak",
                }
            )


def test_run_rule_cache_restore_final_output_requests_require_confirmation_plan_hash_and_lease() -> None:
    prepare = RunRuleCacheRestoreFinalOutputPrepareRequest.model_validate(
        {
            "confirmation": "prepare-rule-cache-restore-final-outputs",
            "planHash": "d" * 64,
            "attemptId": "att_1",
            "leaseGeneration": 1,
        }
    )
    apply = RunRuleCacheRestoreFinalOutputApplyRequest.model_validate(
        {
            "confirmation": "apply-rule-cache-restore-final-outputs",
            "planHash": "e" * 64,
            "attemptId": "att_1",
            "leaseGeneration": 1,
        }
    )
    assert prepare.confirmation == "prepare-rule-cache-restore-final-outputs"
    assert apply.confirmation == "apply-rule-cache-restore-final-outputs"
    for model, confirmation in (
        (RunRuleCacheRestoreFinalOutputPrepareRequest, "prepare-rule-cache-restore-final-outputs"),
        (RunRuleCacheRestoreFinalOutputApplyRequest, "apply-rule-cache-restore-final-outputs"),
    ):
        with pytest.raises(ValidationError):
            model.model_validate(
                {
                    "confirmation": "promote-final-outputs",
                    "planHash": "f" * 64,
                    "attemptId": "att_1",
                    "leaseGeneration": 1,
                }
            )
        with pytest.raises(ValidationError):
            model.model_validate(
                {"confirmation": confirmation, "planHash": "abc", "attemptId": "att_1", "leaseGeneration": 1}
            )
        with pytest.raises(ValidationError):
            model.model_validate(
                {"confirmation": confirmation, "planHash": "f" * 64, "attemptId": "att_1", "leaseGeneration": 0}
            )
        with pytest.raises(ValidationError):
            model.model_validate(
                {
                    "confirmation": confirmation,
                    "planHash": "f" * 64,
                    "attemptId": "att_1",
                    "leaseGeneration": 1,
                    "targetPath": "leak",
                }
            )


def test_run_rule_cache_restore_adoption_requests_require_confirmation_plan_hash_and_lease() -> None:
    prepare = RunRuleCacheRestoreAdoptionPrepareRequest.model_validate(
        {
            "confirmation": "prepare-rule-cache-restore-adoption",
            "planHash": "d" * 64,
            "attemptId": "att_1",
            "leaseGeneration": 1,
        }
    )
    apply = RunRuleCacheRestoreAdoptionApplyRequest.model_validate(
        {
            "confirmation": "apply-rule-cache-restore-adoption",
            "planHash": "e" * 64,
            "attemptId": "att_1",
            "leaseGeneration": 1,
        }
    )
    assert prepare.confirmation == "prepare-rule-cache-restore-adoption"
    assert apply.confirmation == "apply-rule-cache-restore-adoption"
    for model, confirmation in (
        (RunRuleCacheRestoreAdoptionPrepareRequest, "prepare-rule-cache-restore-adoption"),
        (RunRuleCacheRestoreAdoptionApplyRequest, "apply-rule-cache-restore-adoption"),
    ):
        with pytest.raises(ValidationError):
            model.model_validate(
                {
                    "confirmation": "adopt-cache-outputs",
                    "planHash": "f" * 64,
                    "attemptId": "att_1",
                    "leaseGeneration": 1,
                }
            )
        with pytest.raises(ValidationError):
            model.model_validate(
                {"confirmation": confirmation, "planHash": "abc", "attemptId": "att_1", "leaseGeneration": 1}
            )
        with pytest.raises(ValidationError):
            model.model_validate(
                {"confirmation": confirmation, "planHash": "f" * 64, "attemptId": "att_1", "leaseGeneration": 0}
            )
        with pytest.raises(ValidationError):
            model.model_validate(
                {
                    "confirmation": confirmation,
                    "planHash": "f" * 64,
                    "attemptId": "att_1",
                    "leaseGeneration": 1,
                    "artifactId": "leak",
                }
            )


def test_run_resume_request_requires_confirmation_and_plan_hash() -> None:
    request = RunResumeRequest.model_validate(
        {
            "confirmation": "resume-run",
            "planHash": "b" * 64,
            "actor": "operator",
            "reason": "operator approved resume plan",
        }
    )

    assert request.confirmation == "resume-run"
    assert request.planHash == "b" * 64

    with pytest.raises(ValidationError) as wrong_confirmation:
        RunResumeRequest.model_validate({"confirmation": "resume", "planHash": "b" * 64})
    with pytest.raises(ValidationError) as short_hash:
        RunResumeRequest.model_validate({"confirmation": "resume-run", "planHash": "abc"})
    with pytest.raises(ValidationError) as extra:
        RunResumeRequest.model_validate(
            {"confirmation": "resume-run", "planHash": "b" * 64, "legacyResume": True}
        )

    assert any(
        error["type"] == "literal_error" and error["loc"] == ("confirmation",)
        for error in wrong_confirmation.value.errors()
    )
    assert any(error["type"] == "string_too_short" and error["loc"] == ("planHash",) for error in short_hash.value.errors())
    assert any(error["type"] == "extra_forbidden" and error["loc"] == ("legacyResume",) for error in extra.value.errors())


def test_result_package_export_request_requires_explicit_payload_mode_and_is_strict() -> None:
    request = ResultPackageExportRequest.model_validate(
        {"serverId": "srv_demo", "includeArtifacts": False, "actor": "operator"}
    )

    assert request.includeArtifacts is False
    assert request.serverId == "srv_demo"

    with pytest.raises(ValidationError) as missing:
        ResultPackageExportRequest.model_validate({"actor": "operator"})
    with pytest.raises(ValidationError) as extra:
        ResultPackageExportRequest.model_validate({"includeArtifacts": True, "legacyMode": "full"})
    with pytest.raises(ValidationError) as non_boolean:
        ResultPackageExportRequest.model_validate({"includeArtifacts": "false"})

    assert missing.value.errors()[0]["loc"] == ("includeArtifacts",)
    assert extra.value.errors()[0]["type"] == "extra_forbidden"
    assert extra.value.errors()[0]["loc"] == ("legacyMode",)
    assert non_boolean.value.errors()[0]["loc"] == ("includeArtifacts",)
    assert non_boolean.value.errors()[0]["type"] == "bool_type"


def test_result_package_retire_request_is_confirmation_gated_and_strict() -> None:
    request = ResultPackageRetireRequest.model_validate(
        {
            "serverId": "srv_demo",
            "confirmation": "retire-result-package-export",
            "actor": "operator",
            "reason": "superseded",
        }
    )

    assert request.serverId == "srv_demo"
    assert request.confirmation == "retire-result-package-export"

    with pytest.raises(ValidationError) as missing:
        ResultPackageRetireRequest.model_validate({"actor": "operator"})
    with pytest.raises(ValidationError) as wrong:
        ResultPackageRetireRequest.model_validate({"confirmation": "delete-result-package"})
    with pytest.raises(ValidationError) as extra:
        ResultPackageRetireRequest.model_validate(
            {"confirmation": "retire-result-package-export", "deletePayload": True}
        )

    assert missing.value.errors()[0]["loc"] == ("confirmation",)
    assert wrong.value.errors()[0]["type"] == "literal_error"
    assert extra.value.errors()[0]["type"] == "extra_forbidden"


def test_result_package_byte_delete_request_is_confirmation_gated_and_strict() -> None:
    request = ResultPackageByteDeleteRequest.model_validate(
        {
            "serverId": "srv_demo",
            "confirmation": "delete-result-package-export-bytes",
            "actor": "operator",
            "reason": "storage quota",
        }
    )

    assert request.serverId == "srv_demo"
    assert request.confirmation == "delete-result-package-export-bytes"

    with pytest.raises(ValidationError) as missing:
        ResultPackageByteDeleteRequest.model_validate({"actor": "operator"})
    with pytest.raises(ValidationError) as wrong:
        ResultPackageByteDeleteRequest.model_validate({"confirmation": "delete-result-package"})
    with pytest.raises(ValidationError) as extra:
        ResultPackageByteDeleteRequest.model_validate(
            {"confirmation": "delete-result-package-export-bytes", "deleteMetadata": True}
        )

    assert missing.value.errors()[0]["loc"] == ("confirmation",)
    assert wrong.value.errors()[0]["type"] == "literal_error"
    assert extra.value.errors()[0]["type"] == "extra_forbidden"


def test_artifact_cache_pin_requests_are_strict_and_confirmation_gated() -> None:
    retain = ArtifactCachePinRetainRequest.model_validate(
        {
            "serverId": "srv_demo",
            "ownerId": "curator@example.test",
            "reason": "retain-for-review",
            "expiresAt": "2099-06-07T10:00:00Z",
            "actor": "curator@example.test",
        }
    )
    release = ArtifactCachePinReleaseRequest.model_validate(
        {
            "serverId": "srv_demo",
            "confirmation": "release-artifact-cache-policy-pin",
            "reason": "review-complete",
        }
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


def test_workflow_trigger_create_request_is_strict_and_keeps_run_spec_nested() -> None:
    request = WorkflowTriggerCreateRequest.model_validate(
        {
            "serverId": "srv_demo",
            "name": "Nightly summary",
            "sourceType": "cron",
            "triggerSpec": {"cron": "0 2 * * *", "timezone": "UTC", "concurrencyPolicy": "Forbid"},
            "runSpec": {
                "pipelineId": "file-summary-standard-v1",
                "inputs": [{"uploadId": "upl_reads"}],
            },
        }
    )

    assert request.sourceType == "cron"
    assert request.runSpec.pipelineId == "file-summary-standard-v1"

    with pytest.raises(ValidationError) as exc_info:
        WorkflowTriggerCreateRequest.model_validate(
            {
                "serverId": "srv_demo",
                "name": "Legacy summary",
                "sourceType": "manual",
                "pipelineId": "file-summary-standard-v1",
                "runSpec": {"inputs": []},
            }
        )

    assert any(error["type"] == "extra_forbidden" and error["loc"] == ("pipelineId",) for error in exc_info.value.errors())


def test_workflow_trigger_event_request_rejects_unknown_delivery_fields() -> None:
    request = WorkflowTriggerEventRequest.model_validate(
        {
            "eventType": "manual",
            "externalEventId": "evt_ready",
            "idempotencyKey": "manual:evt_ready",
            "cursor": "ready:evt_ready",
            "payload": {"dataset": "reads.fastq"},
        }
    )

    assert request.payload == {"dataset": "reads.fastq"}

    with pytest.raises(ValidationError) as exc_info:
        WorkflowTriggerEventRequest.model_validate({"eventType": "manual", "legacyPayload": {}})

    assert exc_info.value.errors()[0]["type"] == "extra_forbidden"


def test_workflow_trigger_inbox_event_request_is_strict_and_requires_event_identity() -> None:
    request = WorkflowTriggerInboxEventRequest.model_validate(
        {
            "eventType": "dataset.ready",
            "source": "instrument-qc",
            "eventId": "evt_001",
            "correlationId": "batch_42",
            "actor": "instrument-agent",
            "cursor": "batch_42:evt_001",
            "payload": {"dataset": "reads.fastq"},
        }
    )

    assert request.source == "instrument-qc"
    assert request.eventId == "evt_001"
    assert request.correlationId == "batch_42"
    assert request.payload == {"dataset": "reads.fastq"}

    with pytest.raises(ValidationError) as exc_info:
        WorkflowTriggerInboxEventRequest.model_validate({"source": "instrument-qc", "legacyPayload": {}})

    errors = exc_info.value.errors()
    assert any(error["type"] == "missing" and error["loc"] == ("eventId",) for error in errors)
    assert any(error["type"] == "extra_forbidden" and error["loc"] == ("legacyPayload",) for error in errors)


def test_workflow_trigger_inbox_replay_request_requires_confirmation() -> None:
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


def test_workflow_trigger_backfill_preview_request_is_strict_and_bounded() -> None:
    request = WorkflowTriggerBackfillPreviewRequest.model_validate(
        {
            "rangeStart": "2026-06-01",
            "rangeEnd": "2026-06-04",
            "partitionUnit": "day",
            "timezone": "UTC",
            "maxPartitions": 50,
            "concurrencyLimit": 4,
            "runOrder": "forward",
            "reprocessBehavior": "failed",
            "params": {"sampleBatch": "batch_42"},
        }
    )

    assert request.partitionUnit == "day"
    assert request.runOrder == "forward"
    assert request.reprocessBehavior == "failed"
    assert request.params == {"sampleBatch": "batch_42"}

    with pytest.raises(ValidationError) as exc_info:
        WorkflowTriggerBackfillPreviewRequest.model_validate(
            {
                "rangeStart": "2026-06-01",
                "rangeEnd": "2026-06-04",
                "partitionUnit": "week",
                "runOrder": "reverse",
                "reprocessBehavior": "always",
                "maxPartitions": 1001,
                "concurrencyLimit": 0,
                "launch": True,
            }
        )

    errors = exc_info.value.errors()
    assert any(error["type"] == "literal_error" and error["loc"] == ("partitionUnit",) for error in errors)
    assert any(error["type"] == "literal_error" and error["loc"] == ("runOrder",) for error in errors)
    assert any(error["type"] == "literal_error" and error["loc"] == ("reprocessBehavior",) for error in errors)
    assert any(error["type"] == "less_than_equal" and error["loc"] == ("maxPartitions",) for error in errors)
    assert any(error["type"] == "greater_than_equal" and error["loc"] == ("concurrencyLimit",) for error in errors)
    assert any(error["type"] == "extra_forbidden" and error["loc"] == ("launch",) for error in errors)


def test_workflow_trigger_backfill_launch_request_requires_confirmation() -> None:
    request = WorkflowTriggerBackfillLaunchRequest.model_validate(
        {
            "previewId": "bfprev_demo",
            "rangeStart": "2026-06-01",
            "rangeEnd": "2026-06-02",
            "confirmation": "launch-backfill",
            "actor": "operator",
        }
    )

    assert request.previewId == "bfprev_demo"
    assert request.confirmation == "launch-backfill"
    assert request.actor == "operator"

    with pytest.raises(ValidationError) as exc_info:
        WorkflowTriggerBackfillLaunchRequest.model_validate(
            {
                "previewId": "bfprev_demo",
                "rangeStart": "2026-06-01",
                "rangeEnd": "2026-06-02",
                "confirmation": "preview-only",
                "legacyMode": True,
            }
        )

    errors = exc_info.value.errors()
    assert any(error["type"] == "literal_error" and error["loc"] == ("confirmation",) for error in errors)
    assert any(error["type"] == "extra_forbidden" and error["loc"] == ("legacyMode",) for error in errors)

    with pytest.raises(ValidationError) as missing_preview:
        WorkflowTriggerBackfillLaunchRequest.model_validate(
            {
                "rangeStart": "2026-06-01",
                "rangeEnd": "2026-06-02",
                "confirmation": "launch-backfill",
            }
        )

    assert any(error["type"] == "missing" and error["loc"] == ("previewId",) for error in missing_preview.value.errors())


def test_workflow_trigger_scheduler_run_once_request_requires_confirmation_and_bounds() -> None:
    request = WorkflowTriggerSchedulerRunOnceRequest.model_validate(
        {
            "serverId": "srv_primary",
            "confirmation": "run-scheduler-once",
            "limit": 12,
            "actor": "operator",
            "reason": "manual scheduler drain",
        }
    )

    assert request.confirmation == "run-scheduler-once"
    assert request.limit == 12
    assert request.serverId == "srv_primary"

    with pytest.raises(ValidationError) as exc_info:
        WorkflowTriggerSchedulerRunOnceRequest.model_validate(
            {
                "confirmation": "run-now",
                "limit": 101,
                "now": "2026-06-23T02:00:00Z",
            }
        )

    errors = exc_info.value.errors()
    assert any(error["type"] == "literal_error" and error["loc"] == ("confirmation",) for error in errors)
    assert any(error["type"] == "less_than_equal" and error["loc"] == ("limit",) for error in errors)
    assert any(error["type"] == "extra_forbidden" and error["loc"] == ("now",) for error in errors)


def test_artifact_lifecycle_controller_run_once_request_requires_confirmation_and_bounds() -> None:
    request = ArtifactLifecycleControllerRunOnceRequest.model_validate(
        {
            "serverId": "srv_primary",
            "confirmation": "run-artifact-lifecycle-controller-once",
            "retentionDays": 7,
            "eligibleRunStatuses": ["completed", "failed"],
            "quotaBytes": 0,
            "maxDeleteBytesPerTick": 1024,
            "actor": "operator",
            "reason": "manual lifecycle preview",
        }
    )

    assert request.serverId == "srv_primary"
    assert request.confirmation == "run-artifact-lifecycle-controller-once"
    assert request.retentionDays == 7
    assert request.quotaBytes == 0
    assert request.maxDeleteBytesPerTick == 1024

    with pytest.raises(ValidationError) as exc_info:
        ArtifactLifecycleControllerRunOnceRequest.model_validate(
            {
                "confirmation": "delete-artifact-payloads",
                "retentionDays": -1,
                "eligibleRunStatuses": [],
                "maxDeleteBytesPerTick": 0,
                "planFingerprint": "agcfp_unsafe",
            }
        )

    errors = exc_info.value.errors()
    assert any(error["type"] == "literal_error" and error["loc"] == ("confirmation",) for error in errors)
    assert any(error["type"] == "greater_than_equal" and error["loc"] == ("retentionDays",) for error in errors)
    assert any(error["type"] == "too_short" and error["loc"] == ("eligibleRunStatuses",) for error in errors)
    assert any(error["type"] == "greater_than_equal" and error["loc"] == ("maxDeleteBytesPerTick",) for error in errors)
    assert any(error["type"] == "extra_forbidden" and error["loc"] == ("planFingerprint",) for error in errors)


def test_workflow_backfill_cancel_request_requires_confirmation() -> None:
    request = WorkflowBackfillCancelRequest.model_validate(
        {
            "serverId": "srv_primary",
            "confirmation": "cancel-backfill",
            "actor": "operator",
        }
    )

    assert request.serverId == "srv_primary"
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


def test_workflow_trigger_readiness_event_request_is_strict_and_typed() -> None:
    request = WorkflowTriggerReadinessEventRequest.model_validate(
        {
            "source": "lakehouse",
            "eventId": "evt_dataset_ready_001",
            "resourceType": "dataset",
            "resourceId": "dataset:reads",
            "state": "ready",
            "uri": "s3://lab-bucket/reads.fastq",
            "version": "2026-06-24",
            "checksum": "sha256:abc123",
            "observedAt": "2026-06-24T02:00:00Z",
            "actor": "lakehouse-agent",
            "labels": {"assay": "rna-seq"},
            "payload": {"partition": "2026-06-24"},
        }
    )

    assert request.resourceType == "dataset"
    assert request.state == "ready"
    assert request.labels == {"assay": "rna-seq"}

    with pytest.raises(ValidationError) as exc_info:
        WorkflowTriggerReadinessEventRequest.model_validate(
            {
                "source": "lakehouse",
                "eventId": "evt_dataset_ready_001",
                "resourceType": "table",
                "resourceId": "dataset:reads",
                "state": "changed",
                "launch": True,
            }
        )

    errors = exc_info.value.errors()
    assert any(error["type"] == "literal_error" and error["loc"] == ("resourceType",) for error in errors)
    assert any(error["type"] == "literal_error" and error["loc"] == ("state",) for error in errors)
    assert any(error["type"] == "extra_forbidden" and error["loc"] == ("launch",) for error in errors)


def test_workflow_design_compile_request_is_strict() -> None:
    request = WorkflowDesignDraftCompileRequest.model_validate({"serverId": "srv_demo"})

    assert request.serverId == "srv_demo"

    with pytest.raises(ValidationError) as exc_info:
        WorkflowDesignDraftCompileRequest.model_validate({"serverId": "srv_demo", "legacyRunSpec": {}})

    assert exc_info.value.errors()[0]["type"] == "extra_forbidden"


def test_workflow_design_create_runtime_payload_omits_local_default_input_semantics() -> None:
    request = WorkflowDesignDraftCreateRequest.model_validate(
        {
            "serverId": "srv_demo",
            "draft": {
                "contractVersion": "workflow-design-draft-v1",
                "engine": "snakemake",
                "metadata": {"name": "QC workflow"},
                "inputs": [
                    {
                        "id": "reads",
                        "role": "input",
                        "path": "inputs/reads.fastq",
                        "filename": "reads.fastq",
                        "mimeType": "text/plain",
                    }
                ],
            },
        }
    )

    payload = request.runtime_payload()
    assert payload["serverId"] == "srv_demo"
    assert payload["draft"]["inputs"][0] == {
        "id": "reads",
        "role": "input",
        "path": "inputs/reads.fastq",
        "filename": "reads.fastq",
        "mimeType": "text/plain",
    }
    for local_default in ("type", "kind", "data", "format", "operation", "resource"):
        assert local_default not in payload["draft"]["inputs"][0]


def test_terminal_client_message_adapter_uses_pydantic_discriminated_models() -> None:
    input_message = TERMINAL_CLIENT_MESSAGE_ADAPTER.validate_python({"type": "input", "data": "ls\n"})
    resize_message = TERMINAL_CLIENT_MESSAGE_ADAPTER.validate_python({"type": "resize", "cols": 132, "rows": 33})
    ping_message = TERMINAL_CLIENT_MESSAGE_ADAPTER.validate_python({"type": "ping"})

    assert isinstance(input_message, TerminalInputMessage)
    assert input_message.data == "ls\n"
    assert isinstance(resize_message, TerminalResizeMessage)
    assert resize_message.cols == 132
    assert resize_message.rows == 33
    assert isinstance(ping_message, TerminalPingMessage)


def test_terminal_client_message_adapter_rejects_unknown_message_type() -> None:
    with pytest.raises(ValidationError) as exc_info:
        TERMINAL_CLIENT_MESSAGE_ADAPTER.validate_python({"type": "legacy-input", "data": "ls\n"})

    assert exc_info.value.errors()[0]["type"] == "union_tag_invalid"


def test_terminal_session_snapshot_normalizes_runtime_dict() -> None:
    snapshot = TerminalSessionSnapshot.model_validate(
        {
            "session_id": "term_1",
            "cursor": 12,
            "output": "hello",
            "connected": True,
            "input_enabled": True,
            "closed": False,
            "message": "",
            "created_at": 1780470000.0,
            "closed_at": None,
        }
    )

    assert snapshot.cursor == 12
    assert snapshot.output == "hello"
    assert snapshot.state_key == (True, True, "")


def test_terminal_session_snapshot_rejects_unknown_runtime_fields() -> None:
    with pytest.raises(ValidationError) as exc_info:
        TerminalSessionSnapshot.model_validate(
            {
                "session_id": "term_1",
                "cursor": 12,
                "output": "hello",
                "connected": True,
                "input_enabled": True,
                "closed": False,
                "message": "",
                "created_at": 1780470000.0,
                "closed_at": None,
                "legacyState": "connected",
            }
        )

    assert exc_info.value.errors()[0]["type"] == "extra_forbidden"
