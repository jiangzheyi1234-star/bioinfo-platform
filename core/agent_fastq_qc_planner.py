"""Shared deterministic FASTQ QC proposal construction."""

from __future__ import annotations

from typing import Any

from core.contracts.agent_fastq_qc import (
    AGENT_FASTQ_QC_ADAPTER_ID,
    AGENT_FASTQ_QC_ADAPTER_VERSION,
    AGENT_FASTQ_QC_MODEL_REF,
    AGENT_FASTQ_QC_TOOL_VERSIONS,
    AgentFastqQcGoalContext,
    fastq_qc_manifest_digest,
)
from core.contracts.agent_session import AgentPlanProposal, AgentSessionRecord
from core.contracts.capability_bundle import CAPABILITY_BUNDLE_VERSION
from core.contracts.rule_ports import port_compatibility_decision
from core.contracts.workflow_design import WorkflowDesignDraftV1


FASTQ_QC_CAPABILITY_PACK_ID = "h2ometa-metagenomics-core"


def fastq_qc_capability_id(profile_id: str, tool_revision_id: str) -> str:
    revision = str(tool_revision_id).replace(":", "_").replace("/", "_")
    return (
        f"{CAPABILITY_BUNDLE_VERSION}:{FASTQ_QC_CAPABILITY_PACK_ID}:"
        f"{profile_id}:{revision}"
    )


def build_fastq_qc_plan_proposal_from_capabilities(
    *,
    session: AgentSessionRecord | dict[str, Any],
    fastqc: dict[str, Any],
    multiqc: dict[str, Any],
) -> AgentPlanProposal:
    """Build the one canonical proposal from two exact, trusted capabilities."""

    normalized_session = AgentSessionRecord.model_validate(session)
    context = AgentFastqQcGoalContext.model_validate(normalized_session.goal.context)
    _validate_capability(normalized_session, fastqc, profile_id="fastqc")
    _validate_capability(normalized_session, multiqc, profile_id="multiqc")
    fastqc_reads = _required_port(fastqc, "inputs", "reads")
    fastqc_html = _required_port(fastqc, "outputs", "html")
    fastqc_zip = _required_port(fastqc, "outputs", "zip")
    multiqc_input = _required_port(multiqc, "inputs", "fastqc_data")
    multiqc_report = _required_port(multiqc, "outputs", "report")
    compatibility = port_compatibility_decision(multiqc_input, fastqc_zip)
    if compatibility["compatible"] is not True:
        mismatch = str(compatibility.get("mismatchedField") or "semantic contract")
        raise ValueError(f"WORKFLOW_FASTQ_QC_PORT_INCOMPATIBLE: {mismatch}")
    parameters = multiqc.get("parameters")
    if not isinstance(parameters, dict) or "use_input_files_only" not in parameters:
        raise ValueError("WORKFLOW_FASTQ_QC_MULTIQC_PARAMETER_REQUIRED")

    input_item = context.inputs[0]
    manifest_digest = fastq_qc_manifest_digest(context)
    draft = WorkflowDesignDraftV1.model_validate(
        {
            "contractVersion": "workflow-design-draft-v1",
            "engine": "snakemake",
            "metadata": {
                "name": f"FASTQ QC: {input_item.filename}",
                "description": "Single-sample FastQC analysis with a MultiQC HTML summary.",
                "projectId": normalized_session.projectId,
                "tags": ["agent", "fastq-qc", "single-sample"],
            },
            "inputs": [
                {
                    "id": "reads_input",
                    "role": "reads",
                    "path": f"inputs/{input_item.filename}",
                    "filename": input_item.filename,
                    "type": str(fastqc_reads.get("type") or "file"),
                    "kind": str(fastqc_reads.get("kind") or "sequence_reads"),
                    "mimeType": str(fastqc_reads.get("mimeType") or "text/plain"),
                    "data": str(fastqc_reads.get("data") or ""),
                    "format": str(fastqc_reads.get("format") or ""),
                    "operation": str(fastqc_reads.get("operation") or ""),
                    "resource": str(fastqc_reads.get("resource") or ""),
                    "metadata": {
                        "uploadId": input_item.uploadId,
                        "sha256": input_item.sha256,
                        "sizeBytes": input_item.sizeBytes,
                        "materializedMimeType": input_item.mimeType,
                        "materialized": True,
                        "manifestDigest": manifest_digest,
                    },
                }
            ],
            "nodes": [
                _fastqc_node(fastqc, fastqc_html=fastqc_html, fastqc_zip=fastqc_zip),
                _multiqc_node(multiqc, report=multiqc_report),
            ],
            "edges": [
                {
                    "id": "fastqc_zip_to_multiqc",
                    "from": {"nodeId": "fastqc", "port": "zip"},
                    "to": {"nodeId": "multiqc", "port": "fastqc_data"},
                    "audit": {
                        "source": CAPABILITY_BUNDLE_VERSION,
                        "decision": "connect-compatible-ports",
                        "confidence": 1.0,
                        "reason": "FastQC QC archive feeds the MultiQC report input.",
                        "hardChecks": "type,kind,mimeType,data,format",
                    },
                }
            ],
            "resources": {
                "bindings": {},
                "metadata": {
                    "selectionMode": "agent-capability-bundle",
                    "singleSampleOnly": True,
                    "adapterId": AGENT_FASTQ_QC_ADAPTER_ID,
                },
            },
            "outputs": [
                {
                    "from": {"nodeId": "fastqc", "port": "html"},
                    "as": "fastqc_html",
                    "metadata": {"audience": "operator"},
                },
                {
                    "from": {"nodeId": "fastqc", "port": "zip"},
                    "as": "fastqc_archive",
                    "metadata": {"audience": "workflow"},
                },
                {
                    "from": {"nodeId": "multiqc", "port": "report"},
                    "as": "multiqc_report",
                    "metadata": {"audience": "operator"},
                },
            ],
            "provenance": {
                "createdBy": AGENT_FASTQ_QC_ADAPTER_ID,
                "adapterId": AGENT_FASTQ_QC_ADAPTER_ID,
                "adapterVersion": AGENT_FASTQ_QC_ADAPTER_VERSION,
                "capabilityBundleVersion": CAPABILITY_BUNDLE_VERSION,
                "inputManifestDigest": manifest_digest,
            },
        }
    )
    return AgentPlanProposal.model_validate(
        {
            "draft": draft.runtime_payload(),
            "planner": {
                "adapterId": AGENT_FASTQ_QC_ADAPTER_ID,
                "adapterVersion": AGENT_FASTQ_QC_ADAPTER_VERSION,
                "modelRef": AGENT_FASTQ_QC_MODEL_REF,
            },
        }
    )


def _validate_capability(
    session: AgentSessionRecord,
    capability: dict[str, Any],
    *,
    profile_id: str,
) -> None:
    revision_id = str(capability.get("toolRevisionId") or "").strip()
    expected_version = AGENT_FASTQ_QC_TOOL_VERSIONS[profile_id]
    expected_capability_id = fastq_qc_capability_id(profile_id, revision_id)
    allowed = set(session.constraints.allowedToolRevisionIds)
    if (
        capability.get("profileId") != profile_id
        or str(capability.get("version") or "").strip() != expected_version
        or not revision_id
        or (allowed and revision_id not in allowed)
        or capability.get("capabilityId") != expected_capability_id
    ):
        raise ValueError(f"CAPABILITY_BUNDLE_NOT_SELECTABLE: {profile_id}={expected_version}")


def _required_port(capability: dict[str, Any], direction: str, name: str) -> dict[str, Any]:
    ports = capability.get(direction)
    if not isinstance(ports, list):
        raise ValueError(f"WORKFLOW_FASTQ_QC_PORT_REQUIRED: {direction}.{name}")
    matches = [item for item in ports if isinstance(item, dict) and item.get("name") == name]
    if len(matches) != 1:
        raise ValueError(f"WORKFLOW_FASTQ_QC_PORT_REQUIRED: {direction}.{name}")
    return matches[0]


def _fastqc_node(
    capability: dict[str, Any],
    *,
    fastqc_html: dict[str, Any],
    fastqc_zip: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": "fastqc",
        "toolRevisionId": capability["toolRevisionId"],
        "inputs": {"reads": {"fromInput": "reads"}},
        "params": {},
        "runtime": {"threads": 2, "schedulerResources": {"mem_mb": 2048}},
        "resources": {},
        "outputs": {
            "html": {"expose": True, "metadata": _port_metadata(fastqc_html)},
            "zip": {"expose": True, "metadata": _port_metadata(fastqc_zip)},
        },
        "metadata": _capability_metadata(capability),
        "provenance": _capability_provenance(capability),
    }


def _multiqc_node(capability: dict[str, Any], *, report: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "multiqc",
        "toolRevisionId": capability["toolRevisionId"],
        "inputs": {},
        "params": {"use_input_files_only": True},
        "runtime": {"threads": 1, "schedulerResources": {"mem_mb": 1024}},
        "resources": {},
        "outputs": {
            "report": {"expose": True, "metadata": _port_metadata(report)},
        },
        "metadata": _capability_metadata(capability),
        "provenance": _capability_provenance(capability),
    }


def _capability_metadata(capability: dict[str, Any]) -> dict[str, Any]:
    return {
        "capabilityBundleVersion": CAPABILITY_BUNDLE_VERSION,
        "capabilityId": str(capability["capabilityId"]),
        "toolVersion": str(capability["version"]),
    }


def _capability_provenance(capability: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": CAPABILITY_BUNDLE_VERSION,
        "selection": "unique-agent-selectable-revision",
        "capabilityId": str(capability["capabilityId"]),
    }


def _port_metadata(port: dict[str, Any]) -> dict[str, Any]:
    return {
        key: str(port[key])
        for key in ("kind", "mimeType", "data", "format")
        if str(port.get(key) or "").strip()
    }


__all__ = [
    "FASTQ_QC_CAPABILITY_PACK_ID",
    "build_fastq_qc_plan_proposal_from_capabilities",
    "fastq_qc_capability_id",
]
