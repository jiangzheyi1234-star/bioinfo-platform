from __future__ import annotations

import pytest
from pydantic import ValidationError

from apps.remote_runner.api_models import (
    RunCreateRequest,
    ToolManifestRequest,
    ToolProductionEvidenceRequest,
    UploadCreateRequest,
    WorkflowDesignDraftCompileRequest,
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


def test_remote_runner_workflow_design_compile_request_rejects_server_id() -> None:
    request = WorkflowDesignDraftCompileRequest.model_validate({})

    assert request.model_dump() == {}

    with pytest.raises(ValidationError) as exc_info:
        WorkflowDesignDraftCompileRequest.model_validate({"serverId": "srv_demo"})

    assert exc_info.value.errors()[0]["type"] == "extra_forbidden"
