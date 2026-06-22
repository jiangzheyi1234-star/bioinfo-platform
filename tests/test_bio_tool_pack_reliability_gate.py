from __future__ import annotations

import pytest

from apps.api.bio_tool_pack_acceptance import reliability_acceptance_matrix
from apps.api.bio_tool_pack_capability_graph import (
    one_hop_converter_candidates,
    ports_can_connect,
    semantic_capability_graph,
)
from apps.api.bio_tool_pack_manifest import (
    BioToolPackManifestError,
    load_bio_tool_pack_manifest,
    load_bio_tool_pack_manifests,
)
from apps.api.tool_profile_registry import TOOL_PROFILES
from apps.api.tool_profile_model import ToolProfile


def test_builtin_bio_tool_pack_profiles_pass_reliability_matrix() -> None:
    matrix = reliability_acceptance_matrix()

    assert matrix["summary"] == {"total": len(TOOL_PROFILES), "passed": len(TOOL_PROFILES), "failed": 0}
    assert {row["packId"] for row in matrix["rows"]} == {"h2ometa-metagenomics-core"}
    assert all(row["checks"]["reportSchemaBound"] for row in matrix["rows"])


def test_external_bio_tool_pack_manifest_adds_new_tool_profile() -> None:
    profiles = load_bio_tool_pack_manifest(_custom_pack_manifest())

    assert [profile.profile_id for profile in profiles] == ["sourmash-sketch"]
    assert profiles[0].pack_id == "third-party-metagenomics"
    assert profiles[0].operation == "genome-sketching"

    matrix = reliability_acceptance_matrix(profiles)
    graph = semantic_capability_graph(profiles=profiles)

    assert matrix["summary"] == {"total": 1, "passed": 1, "failed": 0}
    assert any(node["id"] == "profile:third-party-metagenomics:sourmash-sketch" for node in graph["nodes"])
    assert any(
        node["kind"] == "InputPort" and node["kindLabel"] == "sequence_reads"
        for node in graph["nodes"]
    )


def test_multiple_bio_tool_pack_manifests_can_extend_candidate_registry() -> None:
    second_pack = _custom_pack_manifest()
    second_pack["packId"] = "third-party-assembly"
    second_pack["profiles"][0]["profileId"] = "flye-assembly"
    second_pack["profiles"][0]["toolNames"] = ["flye"]
    second_pack["profiles"][0]["packageName"] = "flye"

    profiles = load_bio_tool_pack_manifests([_custom_pack_manifest(), second_pack])

    assert [profile.profile_id for profile in profiles] == ["sourmash-sketch", "flye-assembly"]


def test_bio_tool_pack_manifest_fails_loudly_when_required_gate_fields_are_missing() -> None:
    manifest = _custom_pack_manifest()
    del manifest["license"]

    with pytest.raises(BioToolPackManifestError, match="BIO_TOOL_PACK_LICENSE_REQUIRED"):
        load_bio_tool_pack_manifest(manifest)


def test_bio_tool_pack_manifest_requires_smoke_fixture_and_report_schema() -> None:
    missing_smoke = _custom_pack_manifest()
    missing_smoke["profiles"][0]["ruleTemplate"].pop("smokeTest")

    with pytest.raises(BioToolPackManifestError, match="BIO_TOOL_PACK_SMOKE_FIXTURES_REQUIRED"):
        load_bio_tool_pack_manifest(missing_smoke)

    missing_report_schema = _custom_pack_manifest()
    missing_report_schema["profiles"][0]["reportSchemas"] = []

    with pytest.raises(BioToolPackManifestError, match="BIO_TOOL_PACK_REPORT_SCHEMAS_REQUIRED"):
        load_bio_tool_pack_manifest(missing_report_schema)


def test_capability_graph_agent_selectable_subgraph_only_contains_workflow_ready_tools() -> None:
    graph = semantic_capability_graph(
        registered_tools=[
            {
                "id": "bioconda::fastqc",
                "name": "fastqc",
                "toolRevisionId": "bioconda::fastqc#ready",
                "toolContract": {"state": "WorkflowReady", "workflowReady": True},
            },
            {
                "id": "bioconda::kraken2",
                "name": "kraken2",
                "toolRevisionId": "bioconda::kraken2#draft",
                "toolContract": {"state": "SnakemakeRenderable", "workflowReady": False},
            },
        ],
        agent_selectable_only=True,
    )

    assert graph["agentSelectableProfileIds"] == ["fastqc"]
    assert all(node.get("agentSelectable") for node in graph["nodes"] if node["kind"] == "ToolProfile")


def test_capability_graph_port_connection_is_a_hard_semantic_filter() -> None:
    assert ports_can_connect(
        {"name": "html", "type": "file", "kind": "report", "mimeType": "text/html"},
        {"name": "reads", "type": "file", "kind": "sequence_reads", "mimeType": "text/plain"},
    ) is False


def test_capability_graph_finds_one_hop_converter_with_strong_port_evidence() -> None:
    candidates = one_hop_converter_candidates(
        output_port={
            "name": "sam",
            "type": "file",
            "kind": "alignment_sam",
            "mimeType": "text/plain",
            "data": "http://edamontology.org/data_0863",
            "format": "EDAM:format_2573",
        },
        input_port={
            "name": "bam",
            "type": "file",
            "kind": "alignment_bam",
            "mimeType": "application/octet-stream",
            "data": "data_0863",
            "format": "format_2572",
        },
        profiles=(_sam_to_bam_converter_profile(),),
    )

    assert candidates[0]["profileId"] == "samtools-view"
    assert candidates[0]["inputPort"] == "alignment"
    assert candidates[0]["outputPort"] == "bam"
    assert candidates[0]["inputDecision"]["matchedFields"] == ["type", "kind", "mimeType", "data", "format"]
    assert candidates[0]["outputDecision"]["matchedFields"] == ["type", "kind", "mimeType", "data", "format"]


def test_capability_graph_converter_discovery_rejects_zero_evidence_paths() -> None:
    profile = _sam_to_bam_converter_profile()

    assert one_hop_converter_candidates(output_port={"name": "unknown"}, input_port={"name": "target"}, profiles=(profile,)) == []


def test_semantic_capability_graph_exposes_declared_database_resource_requirements() -> None:
    profile = _sam_to_bam_converter_profile()
    template = dict(profile.rule_template)
    template["resources"] = {
        "reference": {
            "type": "database",
            "required": True,
            "configKey": "reference_fasta",
            "acceptedTemplates": ["reference-fasta"],
            "acceptedCapabilities": ["reference_sequence"],
        }
    }
    graph = semantic_capability_graph(
        profiles=(
            ToolProfile(
                **{
                    **profile.__dict__,
                    "profile_id": "samtools-view-with-db",
                    "rule_template": template,
                }
            ),
        )
    )
    node = next(item for item in graph["nodes"] if item["kind"] == "ToolProfile")

    assert node["resourceRequirements"] == [
        {
            "resourceKey": "reference",
            "type": "database",
            "required": True,
            "configKey": "reference_fasta",
            "acceptedTemplates": ["reference-fasta"],
            "acceptedCapabilities": ["reference_sequence"],
        }
    ]


def _sam_to_bam_converter_profile() -> ToolProfile:
    return ToolProfile(
        profile_id="samtools-view",
        version=1,
        tool_names=("samtools-view",),
        package_name="samtools",
        package_source="bioconda",
        package_version="1.23.1",
        pack_id="test-pack",
        workflow_stage="format-conversion",
        operation="alignment-format-conversion",
        rule_template={
            "commandTemplate": "samtools view -bS {input.alignment:q} > {output.bam:q}",
            "inputs": [
                {
                    "name": "alignment",
                    "type": "file",
                    "kind": "alignment_sam",
                    "mimeType": "text/plain",
                    "data": "data_0863",
                    "format": "format_2573",
                    "required": True,
                }
            ],
            "outputs": [
                {
                    "name": "bam",
                    "path": "results/alignment.bam",
                    "type": "file",
                    "kind": "alignment_bam",
                    "mimeType": "application/octet-stream",
                    "data": "data_0863",
                    "format": "format_2572",
                }
            ],
            "params": {},
            "resources": {"threads": {"default": 1}},
            "environment": {"conda": {"channels": ["conda-forge", "bioconda"], "dependencies": ["bioconda::samtools=1.23.1"]}},
            "log": "logs/samtools-view.log",
            "smokeTest": {
                "inputs": {
                    "alignment": {
                        "filename": "alignment.sam",
                        "content": "@HD\tVN:1.0\n",
                        "mimeType": "text/plain",
                    }
                },
                "timeoutSeconds": 300,
            },
        },
        report_schemas=(
            {
                "key": "bam",
                "sourcePort": "bam",
                "kind": "alignment_bam",
                "mimeType": "application/octet-stream",
                "name": "alignment.bam",
                "assertions": ["exists"],
            },
        ),
    )


def _custom_pack_manifest() -> dict[str, object]:
    return {
        "contractVersion": "bio-tool-pack-v1",
        "packId": "third-party-metagenomics",
        "version": 1,
        "name": "Third-party Metagenomics Pack",
        "source": "https://example.org/h2ometa/tool-packs/metagenomics",
        "license": "Apache-2.0",
        "citations": ["Example sourmash tool pack citation"],
        "profiles": [
            {
                "profileId": "sourmash-sketch",
                "version": 1,
                "toolNames": ["sourmash", "sourmash sketch"],
                "packageName": "sourmash",
                "packageSource": "bioconda",
                "packageVersion": "4.9.4",
                "workflowStage": "sketching",
                "operation": "genome-sketching",
                "ruleTemplate": {
                    "commandTemplate": "sourmash sketch dna -o {output.sketch:q} {input.reads:q}",
                    "inputs": [
                        {
                            "name": "reads",
                            "type": "file",
                            "kind": "sequence_reads",
                            "mimeType": "text/plain",
                            "required": True,
                        }
                    ],
                    "outputs": [
                        {
                            "name": "sketch",
                            "path": "results/sourmash.sig",
                            "kind": "sequence_sketch",
                            "mimeType": "application/json",
                        }
                    ],
                    "params": {},
                    "resources": {"threads": {"default": 1}, "mem_mb": {"default": 1024}},
                    "environment": {
                        "conda": {
                            "channels": ["conda-forge", "bioconda"],
                            "dependencies": ["{packageSpec}"],
                        }
                    },
                    "log": "logs/sourmash-sketch.log",
                    "smokeTest": {
                        "inputs": {
                            "reads": {
                                "filename": "reads.fastq",
                                "content": "@smoke\nACGTACGT\n+\nFFFFFFFF\n",
                                "mimeType": "text/plain",
                            }
                        },
                        "timeoutSeconds": 300,
                    },
                },
                "reportSchemas": [
                    {
                        "key": "sketch",
                        "sourcePort": "sketch",
                        "kind": "sequence_sketch",
                        "mimeType": "application/json",
                        "name": "sourmash.sig",
                        "assertions": ["exists", "non-empty"],
                    }
                ],
            }
        ],
    }
