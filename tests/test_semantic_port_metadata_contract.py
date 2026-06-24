from __future__ import annotations

from pathlib import Path

from apps.api.capability_graph_service import CapabilityGraphService
from core.contracts.rule_ports import port_compatibility_decision


ROOT = Path(__file__).resolve().parents[1]


def test_rule_port_contract_keeps_operation_advisory_and_resource_hard() -> None:
    input_spec = {
        "type": "file",
        "data": "EDAM:data_2044",
        "format": "EDAM:format_1930",
        "operation": "operation_0335",
        "resource": "reference_sequence",
    }
    output_spec = {
        "type": "file",
        "data": "sequence_reads",
        "format": "fastq",
        "operation": "operation_2421",
        "resource": "reference_sequence",
    }

    decision = port_compatibility_decision(input_spec, output_spec)

    assert decision["compatible"] is True
    assert "resource" in decision["matchedFields"]
    assert decision["advisoryFields"] == []
    assert decision["advisoryChecks"] == []

    matched_operation = port_compatibility_decision(
        input_spec,
        {**output_spec, "operation": "EDAM:operation_0335"},
    )
    assert matched_operation["compatible"] is True
    assert matched_operation["advisoryFields"] == ["operation"]
    assert matched_operation["advisoryChecks"] == ["operation:advisory-compatible"]

    resource_conflict = port_compatibility_decision(
        input_spec,
        {**output_spec, "resource": "taxonomy_database"},
    )
    assert resource_conflict["compatible"] is False
    assert resource_conflict["mismatchedField"] == "resource"
    assert "resource:conflict" in resource_conflict["hardChecks"]


def test_capability_bundle_preserves_operation_and_resource_port_metadata() -> None:
    snapshot = CapabilityGraphService().snapshot(
        registered_tools=[_ready_semantic_tool()],
        catalog=_empty_catalog(),
    )

    bundle = snapshot["capabilityBundles"][0]

    assert bundle["inputs"][0]["operation"] == "EDAM:operation_0335"
    assert bundle["inputs"][0]["resource"] == "reference_sequence"
    assert bundle["outputs"][0]["operation"] == "operation_2421"
    assert bundle["outputs"][0]["resource"] == "sequence_report"
    assert snapshot["agentSelectableTools"][0]["capabilityBundle"]["inputs"][0]["operation"] == "EDAM:operation_0335"


def test_frontend_semantic_port_metadata_contract_is_visible_to_recommendations() -> None:
    core_model = (ROOT / "apps/web/app/components/tools-page-core-model.ts").read_text(encoding="utf-8")
    workflow_api = (ROOT / "apps/web/app/components/workflows-page-api.ts").read_text(encoding="utf-8")
    port_contract = (ROOT / "apps/web/app/components/generated-workflow-port-contract.ts").read_text(encoding="utf-8")
    recommendation_contract = (
        ROOT / "apps/web/app/components/generated-workflow-recommendation-contract.ts"
    ).read_text(encoding="utf-8")

    for field in ("operation?: string", "resource?: string", "edamOperation?: string", "edamResource?: string"):
        assert field in core_model
    assert "operation?: string" in workflow_api
    assert "resource?: string" in workflow_api
    assert "mimeType: String(inputPort.mimeType || \"\")" in workflow_api
    assert "operation: String(inputPort.operation || \"\")" in workflow_api
    assert "resource: String(inputPort.resource || \"\")" in workflow_api
    assert "advisoryChecks: string[]" in port_contract
    assert "advisoryCompatibilityChecks(advisoryFields)" in port_contract
    assert "`${field}:advisory-compatible`" in port_contract
    assert "advisoryEvidence(compatibilityDecision.advisoryChecks)" in recommendation_contract
    assert "辅助语义匹配" in recommendation_contract


def _ready_semantic_tool() -> dict[str, object]:
    return {
        "id": "bioconda::semantic-tool",
        "name": "semantic-tool",
        "source": "bioconda",
        "version": "1.0.0",
        "packageSpec": "bioconda::semantic-tool=1.0.0",
        "targetPlatform": "linux-64",
        "toolRevisionId": "bioconda::semantic-tool@1.0.0",
        "ruleTemplate": {
            "commandTemplate": "semantic-tool {input.reads:q} > {output.report:q}",
            "inputs": [
                {
                    "name": "reads",
                    "type": "file",
                    "edamData": "EDAM:data_2044",
                    "edamFormat": "EDAM:format_1930",
                    "edamOperation": "EDAM:operation_0335",
                    "edamResource": "reference_sequence",
                    "required": True,
                }
            ],
            "outputs": [
                {
                    "name": "report",
                    "type": "file",
                    "data": "data_3671",
                    "format": "tsv",
                    "operation": "operation_2421",
                    "resource": "sequence_report",
                    "path": "results/report.tsv",
                }
            ],
            "params": {},
            "resources": {"threads": {"default": 1}},
            "environment": {
                "conda": {
                    "channels": ["conda-forge", "bioconda"],
                    "dependencies": ["{packageSpec}"],
                }
            },
            "smokeTest": {
                "inputs": {
                    "reads": {
                        "filename": "reads.fastq",
                        "content": "@read\nACGT\n+\nFFFF\n",
                        "mimeType": "text/plain",
                    }
                },
                "expectedArtifacts": [{"path": "results/report.tsv"}],
            },
        },
        "validationSummary": {
            "latestResultId": "toolval_semantic_tool",
            "latestStatus": "passed",
            "evidenceId": "evid_semantic_tool",
            "updatedAt": "2026-06-14T00:00:00Z",
        },
        "toolContract": {
            "state": "WorkflowReady",
            "workflowReady": True,
            "package": {
                "packageSpec": "bioconda::semantic-tool=1.0.0",
                "source": "bioconda",
                "version": "1.0.0",
                "targetPlatform": "linux-64",
                "targetPlatformSupported": True,
            },
            "validation": {
                "dryRun": {"status": "passed"},
                "smokeRun": {"status": "passed"},
                "outputValidation": {"status": "passed"},
            },
        },
    }


def _empty_catalog() -> dict[str, object]:
    return {
        "items": [],
        "total": 0,
        "page": 1,
        "pageSize": 0,
        "hasMore": False,
        "sourceCounts": {"condaPackages": 0, "snakemakeWrappers": 0, "toolProfiles": 0},
        "addableDraftCounts": {"total": 0},
        "qualityCounts": {},
    }
