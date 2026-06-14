from __future__ import annotations

import pytest


def test_bio_tool_pack_import_enable_surfaces_external_profiles() -> None:
    from apps.api.bio_tool_pack_store import (
        enable_bio_tool_pack,
        enabled_bio_tool_pack_profiles,
        import_bio_tool_pack_manifest,
        list_bio_tool_packs,
        review_bio_tool_pack_manifest,
    )
    from apps.api.tool_candidate_recommendations import recommend_tool_candidates
    from apps.api.tool_candidate_target_acceptance import validation_queue_tool_ids
    from apps.api.tool_profile_catalog import catalog_tool_profiles

    manifest = _custom_pack_manifest()

    review = review_bio_tool_pack_manifest(manifest)
    assert review["decision"] == {
        "status": "AcceptedForImport",
        "canImport": True,
        "canEnable": True,
        "reason": "",
    }
    assert review["pack"]["profileIds"] == ["sourmash-sketch"]
    assert review["acceptance"]["summary"] == {"total": 1, "passed": 1, "failed": 0}

    imported = import_bio_tool_pack_manifest(manifest, enable=False)
    assert imported["pack"]["status"] == "Imported"
    assert enabled_bio_tool_pack_profiles() == ()
    assert catalog_tool_profiles(query="sourmash", page=1, page_size=10)["total"] == 0

    enabled = enable_bio_tool_pack("h2ometa-sourmash-pack")
    assert enabled["pack"]["status"] == "Enabled"
    assert list_bio_tool_packs()["summary"] == {"total": 1, "enabled": 1, "imported": 0}
    assert [profile.profile_id for profile in enabled_bio_tool_pack_profiles()] == ["sourmash-sketch"]

    catalog = catalog_tool_profiles(query="sourmash", page=1, page_size=10)
    item = catalog["items"][0]
    assert item["profileId"] == "sourmash-sketch"
    assert item["packId"] == "h2ometa-sourmash-pack"
    assert item["preparePayload"]["id"] == "bioconda::sourmash"
    assert item["preparePayload"]["ruleSpecDraft"]["requiresUserCompletion"] is False

    recommendations = recommend_tool_candidates(
        output_port={"kind": "sequence_reads", "mimeType": "text/plain"},
        query="sourmash",
        page=1,
        page_size=10,
    )
    recommendation = recommendations["items"][0]
    assert recommendation["candidate"]["candidateId"] == "h2ometa-tool-profile::sourmash-sketch"
    assert recommendation["blockReason"] == "WORKFLOW_TOOL_NOT_READY"
    assert recommendation["preparePayload"]["id"] == "bioconda::sourmash"
    assert "bioconda::sourmash" in validation_queue_tool_ids()


def test_bio_tool_pack_import_rejects_profile_id_collisions() -> None:
    from apps.api.bio_tool_pack_manifest import BioToolPackManifestError
    from apps.api.bio_tool_pack_store import import_bio_tool_pack_manifest

    manifest = _custom_pack_manifest()
    manifest["profiles"][0]["profileId"] = "fastqc"

    with pytest.raises(BioToolPackManifestError, match="BIO_TOOL_PACK_PROFILE_ID_DUPLICATE"):
        import_bio_tool_pack_manifest(manifest)


def test_bio_tool_pack_enable_can_be_reversed() -> None:
    from apps.api.bio_tool_pack_store import disable_bio_tool_pack, enable_bio_tool_pack, import_bio_tool_pack_manifest
    from apps.api.tool_profile_catalog import catalog_tool_profiles

    import_bio_tool_pack_manifest(_custom_pack_manifest(), enable=True)
    assert catalog_tool_profiles(query="sourmash", page=1, page_size=10)["total"] == 1

    disabled = disable_bio_tool_pack("h2ometa-sourmash-pack")
    assert disabled["pack"]["enabled"] is False
    assert catalog_tool_profiles(query="sourmash", page=1, page_size=10)["total"] == 0

    enable_bio_tool_pack("h2ometa-sourmash-pack")
    assert catalog_tool_profiles(query="sourmash", page=1, page_size=10)["total"] == 1


def _custom_pack_manifest() -> dict:
    return {
        "contractVersion": "bio-tool-pack-v1",
        "packId": "h2ometa-sourmash-pack",
        "version": "1",
        "name": "H2OMeta Sourmash Tool Pack",
        "source": "https://example.test/h2ometa-sourmash-pack",
        "license": "BSD-3-Clause",
        "citations": ["Sourmash tool pack citation"],
        "profiles": [
            {
                "profileId": "sourmash-sketch",
                "version": 1,
                "toolNames": ["sourmash", "sourmash sketch"],
                "packageName": "sourmash",
                "workflowStage": "read-qc",
                "operation": "sequence-sketching",
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
                        "assertions": ["exists", "non-empty"],
                    }
                ],
            }
        ],
    }
