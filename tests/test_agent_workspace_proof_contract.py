from __future__ import annotations

import hashlib
import json

import pytest
from pydantic import ValidationError

from core.contracts.agent_workspace_proof import (
    AGENT_WORKSPACE_MANIFEST_HASH_DOMAIN,
    AGENT_WORKSPACE_PROOF_CONTRACT_VERSION,
    AGENT_WORKSPACE_TOOL_ASSETS_HASH_DOMAIN,
    AgentWorkspaceProofV1,
    agent_workspace_manifest_hash,
    agent_workspace_proof_hash,
    agent_workspace_proof_id,
    agent_workspace_tool_assets_hash,
    build_agent_workspace_proof_v1,
)


def _semantic_payload() -> dict[str, object]:
    return {
        "contractVersion": AGENT_WORKSPACE_PROOF_CONTRACT_VERSION,
        "runId": "run-agent-1",
        "authorizationId": "authorization-agent-1",
        "attemptId": "attempt-agent-1",
        "leaseGeneration": 3,
        "sourceAttemptId": None,
        "processBoundary": "pre_dry_run",
        "processOrdinal": 1,
        "workflowRevisionId": "workflow-revision-1",
        "workflowRevisionContentHash": "1" * 64,
        "workflowRevisionManifestHash": "2" * 64,
        "runSpecHash": "3" * 64,
        "inputSnapshotHash": "4" * 64,
        "runtimeLockHash": "6" * 64,
        "runtimeProofHash": "7" * 64,
        "immutableManifest": [
            {"relativePath": "run-config.json", "size": 19, "sha256": "8" * 64},
            {"relativePath": "workflow/Snakefile", "size": 41, "sha256": "9" * 64},
            {
                "relativePath": "workflow/rules/qc.smk",
                "size": 23,
                "sha256": "a" * 64,
            },
        ],
        "snakemakeManifest": [],
        "previousProofHash": None,
        "eventId": "event-agent-workspace-1",
        "createdAt": "2026-07-19T09:10:11Z",
    }


def _canonical_hash(domain: str, payload: object) -> str:
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(
        domain.encode("utf-8") + b"\x00" + canonical.encode("utf-8")
    ).hexdigest()


def test_build_proof_has_exact_canonical_hash_and_content_addressed_id() -> None:
    proof = build_agent_workspace_proof_v1(_semantic_payload())
    runtime = proof.runtime_payload()

    assert runtime["sourceAttemptId"] == ""
    assert "previousProofHash" in runtime
    assert runtime["previousProofHash"] is None

    expected_manifest_hash = _canonical_hash(
        AGENT_WORKSPACE_MANIFEST_HASH_DOMAIN,
        {"entries": runtime["immutableManifest"]},
    )
    expected_empty_manifest_hash = _canonical_hash(
        AGENT_WORKSPACE_MANIFEST_HASH_DOMAIN,
        {"entries": []},
    )
    assert proof.immutableManifestHash == expected_manifest_hash
    assert proof.snakemakeManifestHash == expected_empty_manifest_hash
    assert (
        agent_workspace_manifest_hash(proof.immutableManifest) == expected_manifest_hash
    )
    expected_tool_assets = runtime["immutableManifest"][1:]
    expected_tool_assets_hash = _canonical_hash(
        AGENT_WORKSPACE_TOOL_ASSETS_HASH_DOMAIN,
        {"entries": expected_tool_assets},
    )
    assert proof.toolAssetsHash == expected_tool_assets_hash
    assert (
        agent_workspace_tool_assets_hash(proof.immutableManifest)
        == expected_tool_assets_hash
    )
    assert expected_tool_assets_hash != _canonical_hash(
        AGENT_WORKSPACE_MANIFEST_HASH_DOMAIN,
        {"entries": expected_tool_assets},
    )

    semantics = dict(runtime)
    semantics.pop("workspaceProofId")
    semantics.pop("proofHash")
    expected_proof_hash = _canonical_hash(
        AGENT_WORKSPACE_PROOF_CONTRACT_VERSION,
        semantics,
    )
    assert proof.proofHash == expected_proof_hash
    assert agent_workspace_proof_hash(proof) == expected_proof_hash
    nullable_source_semantics = dict(semantics)
    nullable_source_semantics["sourceAttemptId"] = None
    assert agent_workspace_proof_hash(nullable_source_semantics) == expected_proof_hash
    assert proof.workspaceProofId == f"awsp_{expected_proof_hash[:24]}"
    assert agent_workspace_proof_id(expected_proof_hash) == proof.workspaceProofId


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("relativePath", "workflow/rules/qc-v2.smk"),
        ("size", 24),
        ("sha256", "b" * 64),
    ],
)
def test_any_workflow_asset_semantic_change_changes_tool_hash(
    field: str,
    replacement: object,
) -> None:
    original = build_agent_workspace_proof_v1(_semantic_payload())
    changed_payload = _semantic_payload()
    changed_payload["immutableManifest"][2][field] = replacement
    changed = build_agent_workspace_proof_v1(changed_payload)

    assert changed.toolAssetsHash != original.toolAssetsHash
    assert changed.proofHash != original.proofHash


def test_non_workflow_change_preserves_tool_hash_but_changes_proof_hash() -> None:
    original = build_agent_workspace_proof_v1(_semantic_payload())
    changed_payload = _semantic_payload()
    changed_payload["immutableManifest"][0].update(size=20, sha256="c" * 64)
    changed = build_agent_workspace_proof_v1(changed_payload)

    assert changed.toolAssetsHash == original.toolAssetsHash
    assert changed.immutableManifestHash != original.immutableManifestHash
    assert changed.proofHash != original.proofHash


def test_missing_required_snakefile_fails_builder_and_model_validation() -> None:
    payload = _semantic_payload()
    payload["immutableManifest"] = [
        entry
        for entry in payload["immutableManifest"]
        if entry["relativePath"] != "workflow/Snakefile"
    ]
    with pytest.raises(ValueError, match="TOOL_ASSETS_SNAKEFILE_MISSING"):
        build_agent_workspace_proof_v1(payload)

    direct = build_agent_workspace_proof_v1(_semantic_payload()).runtime_payload()
    direct["immutableManifest"] = [
        entry
        for entry in direct["immutableManifest"]
        if entry["relativePath"] != "workflow/Snakefile"
    ]
    direct["immutableManifestHash"] = agent_workspace_manifest_hash(
        direct["immutableManifest"]
    )
    with pytest.raises(ValidationError, match="TOOL_ASSETS_SNAKEFILE_MISSING"):
        AgentWorkspaceProofV1.model_validate(direct)


def test_forged_tool_assets_hash_fails_builder_and_model_validation() -> None:
    payload = _semantic_payload()
    payload["toolAssetsHash"] = "f" * 64
    with pytest.raises(ValueError, match="TOOL_ASSETS_HASH_MISMATCH"):
        build_agent_workspace_proof_v1(payload)

    direct = build_agent_workspace_proof_v1(_semantic_payload()).runtime_payload()
    direct["toolAssetsHash"] = "f" * 64
    direct["proofHash"] = agent_workspace_proof_hash(direct)
    direct["workspaceProofId"] = agent_workspace_proof_id(direct["proofHash"])
    with pytest.raises(ValidationError, match="TOOL_ASSETS_HASH_MISMATCH"):
        AgentWorkspaceProofV1.model_validate(direct)


def test_contract_rejects_extra_fields_at_every_level() -> None:
    proof = build_agent_workspace_proof_v1(_semantic_payload()).runtime_payload()

    with pytest.raises(ValidationError, match="extra_forbidden"):
        AgentWorkspaceProofV1.model_validate({**proof, "signature": "not-supported"})

    nested = dict(proof)
    entries = [dict(entry) for entry in proof["immutableManifest"]]
    entries[0]["absolutePath"] = "C:/private/workspace/run-config.json"
    nested["immutableManifest"] = entries
    with pytest.raises(ValidationError, match="extra_forbidden"):
        AgentWorkspaceProofV1.model_validate(nested)


@pytest.mark.parametrize(
    "relative_path",
    [
        "/etc/passwd",
        "../escape",
        "workflow/../escape",
        "./Snakefile",
        "workflow//Snakefile",
        "workflow/",
        r"C:\workspace\Snakefile",
        "C:/workspace/Snakefile",
        "workflow/Snakefile:secret",
        "workflow/Snakefile::$DATA",
        "workflow/Snakefile.",
        "CON",
        "workflow/con.txt",
    ],
)
def test_contract_rejects_absolute_or_noncanonical_relative_paths(
    relative_path: str,
) -> None:
    payload = _semantic_payload()
    entries = list(payload["immutableManifest"])
    entries[0] = {"relativePath": relative_path, "size": 1, "sha256": "a" * 64}
    payload["immutableManifest"] = entries

    with pytest.raises((ValidationError, ValueError), match="RELATIVE_PATH_INVALID"):
        build_agent_workspace_proof_v1(payload)


def test_contract_rejects_case_insensitive_windows_path_aliases() -> None:
    payload = _semantic_payload()
    payload["immutableManifest"] = [
        {"relativePath": "workflow/Snakefile", "size": 1, "sha256": "a" * 64},
        {"relativePath": "workflow/snakefile", "size": 1, "sha256": "b" * 64},
    ]

    with pytest.raises((ValidationError, ValueError), match="WINDOWS_ALIAS_PATH"):
        build_agent_workspace_proof_v1(payload)


@pytest.mark.parametrize("mode", ["duplicate", "unsorted"])
def test_contract_rejects_duplicate_or_unsorted_manifest_entries(mode: str) -> None:
    payload = _semantic_payload()
    entries = list(payload["immutableManifest"])
    if mode == "duplicate":
        entries[1] = dict(entries[0])
    else:
        entries.reverse()
    payload["immutableManifest"] = entries

    with pytest.raises(
        (ValidationError, ValueError), match="(DUPLICATE_PATH|ORDER_INVALID)"
    ):
        build_agent_workspace_proof_v1(payload)


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (
            lambda payload: payload.update(runId="run-agent-tampered"),
            "PROOF_HASH_MISMATCH",
        ),
        (
            lambda payload: payload["immutableManifest"][0].update(sha256="a" * 64),
            "IMMUTABLE_MANIFEST_HASH_MISMATCH",
        ),
        (
            lambda payload: payload.update(workspaceProofId="awsp_" + "f" * 24),
            "PROOF_ID_MISMATCH",
        ),
    ],
)
def test_contract_rejects_tampered_semantics_manifest_or_id(
    mutation, error: str
) -> None:
    payload = build_agent_workspace_proof_v1(_semantic_payload()).runtime_payload()
    mutation(payload)

    with pytest.raises(ValidationError, match=error):
        AgentWorkspaceProofV1.model_validate(payload)


def test_contract_rejects_noncanonical_sha256() -> None:
    payload = _semantic_payload()
    payload["runtimeProofHash"] = "A" * 64

    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        build_agent_workspace_proof_v1(payload)
