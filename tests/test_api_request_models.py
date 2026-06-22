from __future__ import annotations

import pytest
from pydantic import ValidationError

from apps.api.models import (
    RunSubmitRequest,
    TERMINAL_CLIENT_MESSAGE_ADAPTER,
    TerminalInputMessage,
    TerminalPingMessage,
    TerminalResizeMessage,
    TerminalSessionSnapshot,
    ToolManifestRequest,
    ToolProductionEvidenceRequest,
    UploadSubmitRequest,
    WorkflowDesignDraftCompileRequest,
    WorkflowTriggerCreateRequest,
    WorkflowTriggerEventRequest,
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


def test_workflow_trigger_create_request_is_strict_and_keeps_run_spec_nested() -> None:
    request = WorkflowTriggerCreateRequest.model_validate(
        {
            "serverId": "srv_demo",
            "name": "Nightly summary",
            "sourceType": "cron",
            "triggerSpec": {"cron": "0 2 * * *", "timezone": "UTC"},
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


def test_workflow_design_compile_request_is_strict() -> None:
    request = WorkflowDesignDraftCompileRequest.model_validate({"serverId": "srv_demo"})

    assert request.serverId == "srv_demo"

    with pytest.raises(ValidationError) as exc_info:
        WorkflowDesignDraftCompileRequest.model_validate({"serverId": "srv_demo", "legacyRunSpec": {}})

    assert exc_info.value.errors()[0]["type"] == "extra_forbidden"


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
