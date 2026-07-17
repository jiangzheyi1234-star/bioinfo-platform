from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

from core.contracts.runner_activation_release_publication import (
    RUNNER_ACTIVATION_RELEASE_EXTRACTION_POLICY,
    RUNNER_ACTIVATION_RELEASE_OBJECTS_DIRECTORY,
    RUNNER_ACTIVATION_RELEASE_PLATFORMS,
    RUNNER_ACTIVATION_RELEASE_PUBLICATION_INTENT_SCHEMA,
    RUNNER_ACTIVATION_RELEASE_PUBLICATION_RECEIPT_SCHEMA,
    RUNNER_ACTIVATION_RELEASE_PUBLICATION_SERVICE,
    RUNNER_ACTIVATION_RELEASE_RELOCATION_POLICY,
    build_runner_activation_release_publication_intent,
    build_runner_activation_release_publication_receipt,
    require_runner_activation_release_publication_intent,
    require_runner_activation_release_publication_manifest_binding,
    require_runner_activation_release_publication_receipt,
    runner_activation_release_publication_intent_canonical_json,
    runner_activation_release_publication_intent_fingerprint,
    runner_activation_release_publication_receipt_canonical_json,
    runner_activation_release_publication_receipt_fingerprint,
    runner_activation_release_publication_relative_path,
)
from core.contracts.runner_activation_release_tree import (
    RUNNER_ACTIVATION_RELEASE_TREE_MATERIALIZATION_POLICY,
    build_runner_activation_release_tree_manifest,
    runner_activation_release_tree_content_fingerprint,
    runner_activation_release_tree_manifest_fingerprint,
)


PUBLICATION_ID = "1" * 32
INSTALLATION_FINGERPRINT = "sha256:" + "a" * 64
ARCHIVE_SHA256 = "sha256:" + "b" * 64
BOOTSTRAP_MANIFEST_FINGERPRINT = "sha256:" + "c" * 64
PROVENANCE_FINGERPRINT = "sha256:" + "d" * 64
ARCHIVE_INSPECTION_MANIFEST_FINGERPRINT = "sha256:" + "e" * 64

INTENT_FIELDS = {
    "artifactArchiveSha256",
    "artifactArchiveSizeBytes",
    "artifactPlatform",
    "artifactProvenanceFingerprint",
    "artifactVersion",
    "archiveInspectionManifestFingerprint",
    "bootstrapManifestFingerprint",
    "extractionPolicyVersion",
    "installationFingerprint",
    "materializationPolicyVersion",
    "publicationId",
    "releaseTreeRelativePath",
    "relocationPolicyVersion",
    "schemaVersion",
    "service",
}
RECEIPT_FIELDS = {
    "intent",
    "intentFingerprint",
    "releaseTreeContentFingerprint",
    "releaseTreeDevice",
    "releaseTreeInode",
    "releaseTreeManifestFingerprint",
    "schemaVersion",
    "service",
}


def _intent(**overrides: object) -> dict[str, object]:
    values = {
        "publication_id": PUBLICATION_ID,
        "installation_fingerprint": INSTALLATION_FINGERPRINT,
        "artifact_version": "0.2.0-control-plane",
        "artifact_platform": "linux-64",
        "artifact_archive_sha256": ARCHIVE_SHA256,
        "artifact_archive_size_bytes": 987_654,
        "bootstrap_manifest_fingerprint": BOOTSTRAP_MANIFEST_FINGERPRINT,
        "archive_inspection_manifest_fingerprint": (
            ARCHIVE_INSPECTION_MANIFEST_FINGERPRINT
        ),
        "artifact_provenance_fingerprint": PROVENANCE_FINGERPRINT,
    }
    values.update(overrides)
    return build_runner_activation_release_publication_intent(**values)


def _tree_manifest(*, content: str = "e") -> dict[str, object]:
    return build_runner_activation_release_tree_manifest(
        [
            {
                "contentSha256": "sha256:" + content * 64,
                "linkTarget": "",
                "mode": "0555",
                "path": "runner",
                "sizeBytes": 321,
                "type": "file",
            }
        ]
    )


def _receipt(
    *,
    intent: object | None = None,
    manifest: object | None = None,
) -> dict[str, object]:
    return build_runner_activation_release_publication_receipt(
        intent=_intent() if intent is None else intent,
        release_tree_manifest=(_tree_manifest() if manifest is None else manifest),
        release_tree_device=2049,
        release_tree_inode=73_501,
    )


def _domain_fingerprint(domain: str, canonical: str) -> str:
    digest = hashlib.sha256(
        domain.encode("ascii") + b"\x00" + canonical.encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"


def test_intent_builder_derives_exact_fields_and_policy_versions() -> None:
    intent = _intent()

    assert set(intent) == INTENT_FIELDS
    assert intent == require_runner_activation_release_publication_intent(intent)
    assert intent["schemaVersion"] == (
        RUNNER_ACTIVATION_RELEASE_PUBLICATION_INTENT_SCHEMA
    )
    assert intent["service"] == RUNNER_ACTIVATION_RELEASE_PUBLICATION_SERVICE
    assert intent["releaseTreeRelativePath"] == (
        f"{RUNNER_ACTIVATION_RELEASE_OBJECTS_DIRECTORY}/{PUBLICATION_ID}"
    )
    assert intent["materializationPolicyVersion"] == (
        RUNNER_ACTIVATION_RELEASE_TREE_MATERIALIZATION_POLICY
    )
    assert intent["extractionPolicyVersion"] == (
        RUNNER_ACTIVATION_RELEASE_EXTRACTION_POLICY
    )
    assert intent["relocationPolicyVersion"] == (
        RUNNER_ACTIVATION_RELEASE_RELOCATION_POLICY
    )


def test_intent_builder_does_not_accept_a_caller_selected_path() -> None:
    with pytest.raises(TypeError, match="release_tree_relative_path"):
        build_runner_activation_release_publication_intent(
            publication_id=PUBLICATION_ID,
            installation_fingerprint=INSTALLATION_FINGERPRINT,
            artifact_version="0.2.0-control-plane",
            artifact_platform="linux-64",
            artifact_archive_sha256=ARCHIVE_SHA256,
            artifact_archive_size_bytes=1,
            bootstrap_manifest_fingerprint=BOOTSTRAP_MANIFEST_FINGERPRINT,
            archive_inspection_manifest_fingerprint=(
                ARCHIVE_INSPECTION_MANIFEST_FINGERPRINT
            ),
            artifact_provenance_fingerprint=PROVENANCE_FINGERPRINT,
            release_tree_relative_path="release-objects/caller-choice",  # type: ignore[call-arg]
        )


def test_receipt_builder_derives_tree_bindings_from_manifest() -> None:
    intent = _intent()
    manifest = _tree_manifest()
    receipt = _receipt(intent=intent, manifest=manifest)

    assert set(receipt) == RECEIPT_FIELDS
    assert receipt == require_runner_activation_release_publication_receipt(receipt)
    assert receipt["schemaVersion"] == (
        RUNNER_ACTIVATION_RELEASE_PUBLICATION_RECEIPT_SCHEMA
    )
    assert receipt["intent"] == intent
    assert receipt["intentFingerprint"] == (
        runner_activation_release_publication_intent_fingerprint(intent)
    )
    assert receipt["releaseTreeContentFingerprint"] == (
        runner_activation_release_tree_content_fingerprint(manifest)
    )
    assert receipt["releaseTreeManifestFingerprint"] == (
        runner_activation_release_tree_manifest_fingerprint(manifest)
    )


def test_publication_canonical_json_and_fingerprints_are_domain_separated() -> None:
    intent = _intent()
    receipt = _receipt(intent=intent)
    intent_canonical = runner_activation_release_publication_intent_canonical_json(
        intent
    )
    receipt_canonical = runner_activation_release_publication_receipt_canonical_json(
        receipt
    )

    assert intent_canonical == json.dumps(
        intent,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    assert receipt_canonical == json.dumps(
        receipt,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    assert runner_activation_release_publication_intent_fingerprint(intent) == (
        _domain_fingerprint(
            RUNNER_ACTIVATION_RELEASE_PUBLICATION_INTENT_SCHEMA,
            intent_canonical,
        )
    )
    assert runner_activation_release_publication_receipt_fingerprint(receipt) == (
        _domain_fingerprint(
            RUNNER_ACTIVATION_RELEASE_PUBLICATION_RECEIPT_SCHEMA,
            receipt_canonical,
        )
    )


def test_receipt_and_validators_deeply_detach_nested_intent() -> None:
    intent = _intent()
    receipt = _receipt(intent=intent)
    normalized = require_runner_activation_release_publication_receipt(receipt)

    intent["artifactVersion"] = "9.9.9"
    assert receipt["intent"]["artifactVersion"] == "0.2.0-control-plane"  # type: ignore[index]
    receipt["intent"]["artifactVersion"] = "8.8.8"  # type: ignore[index]
    assert normalized["intent"]["artifactVersion"] == "0.2.0-control-plane"  # type: ignore[index]


class PublicationContractError(RuntimeError):
    pass


def test_contract_uses_caller_error_type_across_nested_validation() -> None:
    receipt = _receipt()
    receipt["intent"]["artifactPlatform"] = "win-64"  # type: ignore[index]

    with pytest.raises(PublicationContractError, match="artifactPlatform"):
        require_runner_activation_release_publication_receipt(
            receipt,
            make_error=PublicationContractError,
        )


@pytest.mark.parametrize(
    "publication_id",
    [
        "",
        "1" * 31,
        "1" * 33,
        "A" * 32,
        "g" * 32,
        "../" + "1" * 32,
        1,
        None,
    ],
)
def test_publication_id_and_derived_path_are_strict(
    publication_id: object,
) -> None:
    with pytest.raises(ValueError, match="publicationId"):
        runner_activation_release_publication_relative_path(publication_id)


def test_intent_rejects_release_path_not_derived_from_id() -> None:
    intent = _intent()
    intent["releaseTreeRelativePath"] = (
        f"{RUNNER_ACTIVATION_RELEASE_OBJECTS_DIRECTORY}/{'2' * 32}"
    )

    with pytest.raises(ValueError, match="releaseTreeRelativePath"):
        require_runner_activation_release_publication_intent(intent)


@pytest.mark.parametrize(
    "version",
    [
        "",
        "-0.2.0",
        ".0.2.0",
        "0.2.0-",
        "0.2.0.",
        "0..2",
        "0/2",
        "0\\2",
        " 0.2.0",
        "0.2.0 ",
        "版本1",
        "v" * 129,
        1,
        True,
        None,
    ],
)
def test_intent_rejects_unsafe_artifact_version(version: object) -> None:
    with pytest.raises(ValueError, match="artifactVersion"):
        _intent(artifact_version=version)


@pytest.mark.parametrize(
    "version",
    ["1", "v1", "0.2.0", "0.2.0-control-plane", "1.0.0+build.7"],
)
def test_intent_accepts_tight_ascii_artifact_version(version: str) -> None:
    assert _intent(artifact_version=version)["artifactVersion"] == version


@pytest.mark.parametrize("platform", ["", "linux", "win-64", "LINUX-64", 1])
def test_intent_rejects_unknown_artifact_platform(platform: object) -> None:
    with pytest.raises(ValueError, match="artifactPlatform"):
        _intent(artifact_platform=platform)


def test_platform_set_is_exact() -> None:
    assert RUNNER_ACTIVATION_RELEASE_PLATFORMS == {
        "linux-64",
        "linux-aarch64",
    }


@pytest.mark.parametrize(
    ("argument", "field"),
    [
        ("installation_fingerprint", "installationFingerprint"),
        ("artifact_archive_sha256", "artifactArchiveSha256"),
        ("bootstrap_manifest_fingerprint", "bootstrapManifestFingerprint"),
        (
            "archive_inspection_manifest_fingerprint",
            "archiveInspectionManifestFingerprint",
        ),
        (
            "artifact_provenance_fingerprint",
            "artifactProvenanceFingerprint",
        ),
    ],
)
@pytest.mark.parametrize(
    "invalid",
    ["", "sha256:", "sha256:" + "A" * 64, "sha256:" + "0" * 63, "md5:" + "0" * 64, 1],
)
def test_intent_rejects_invalid_fingerprints(
    argument: str,
    field: str,
    invalid: object,
) -> None:
    with pytest.raises(ValueError, match=field):
        _intent(**{argument: invalid})


@pytest.mark.parametrize("size", [0, -1, True, False, 1.5, "1", None])
def test_intent_rejects_invalid_archive_size(size: object) -> None:
    with pytest.raises(ValueError, match="artifactArchiveSizeBytes"):
        _intent(artifact_archive_size_bytes=size)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("releaseTreeDevice", 0),
        ("releaseTreeDevice", -1),
        ("releaseTreeDevice", True),
        ("releaseTreeDevice", "2049"),
        ("releaseTreeInode", 0),
        ("releaseTreeInode", -1),
        ("releaseTreeInode", False),
        ("releaseTreeInode", "73501"),
    ],
)
def test_receipt_rejects_invalid_device_or_inode(
    field: str,
    value: object,
) -> None:
    receipt = _receipt()
    receipt[field] = value

    with pytest.raises(ValueError, match=field):
        require_runner_activation_release_publication_receipt(receipt)


@pytest.mark.parametrize("field", sorted(INTENT_FIELDS))
def test_intent_rejects_missing_or_extra_fields(field: str) -> None:
    intent = _intent()
    intent.pop(field)
    with pytest.raises(ValueError, match="fields must match exactly"):
        require_runner_activation_release_publication_intent(intent)

    intent = _intent()
    intent["unexpected"] = field
    with pytest.raises(ValueError, match="fields must match exactly"):
        require_runner_activation_release_publication_intent(intent)


@pytest.mark.parametrize("field", sorted(RECEIPT_FIELDS))
def test_receipt_rejects_missing_or_extra_fields(field: str) -> None:
    receipt = _receipt()
    receipt.pop(field)
    with pytest.raises(ValueError, match="fields must match exactly"):
        require_runner_activation_release_publication_receipt(receipt)

    receipt = _receipt()
    receipt["unexpected"] = field
    with pytest.raises(ValueError, match="fields must match exactly"):
        require_runner_activation_release_publication_receipt(receipt)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schemaVersion", "h2ometa.runner-installed-release-publication-intent.v3"),
        ("service", "another-service"),
        ("materializationPolicyVersion", "materialization.v2"),
        ("extractionPolicyVersion", "extraction.v2"),
        ("relocationPolicyVersion", "relocation.v2"),
    ],
)
def test_intent_rejects_schema_service_or_policy_drift(
    field: str,
    value: str,
) -> None:
    intent = _intent()
    intent[field] = value

    with pytest.raises(ValueError, match=field):
        require_runner_activation_release_publication_intent(intent)


def test_receipt_rejects_intent_fingerprint_drift() -> None:
    receipt = _receipt()
    receipt["intentFingerprint"] = "sha256:" + "9" * 64

    with pytest.raises(ValueError, match="intent binding"):
        require_runner_activation_release_publication_receipt(receipt)


@pytest.mark.parametrize(
    "field",
    [
        "intentFingerprint",
        "releaseTreeContentFingerprint",
        "releaseTreeManifestFingerprint",
    ],
)
@pytest.mark.parametrize(
    "invalid",
    ["", "sha256:" + "A" * 64, "sha256:" + "0" * 63, "raw:" + "0" * 64, 1],
)
def test_receipt_rejects_invalid_fingerprints(
    field: str,
    invalid: object,
) -> None:
    receipt = _receipt()
    receipt[field] = invalid

    with pytest.raises(ValueError, match=field):
        require_runner_activation_release_publication_receipt(receipt)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (
            "schemaVersion",
            "h2ometa.runner-installed-release-publication-receipt.v3",
        ),
        ("service", "another-service"),
    ],
)
def test_receipt_rejects_schema_or_service_drift(
    field: str,
    value: str,
) -> None:
    receipt = _receipt()
    receipt[field] = value

    with pytest.raises(ValueError, match=field):
        require_runner_activation_release_publication_receipt(receipt)


def test_binding_verifier_requires_the_actual_matching_manifest() -> None:
    first_manifest = _tree_manifest(content="e")
    second_manifest = _tree_manifest(content="f")
    receipt = _receipt(manifest=first_manifest)

    assert (
        require_runner_activation_release_publication_manifest_binding(
            receipt,
            release_tree_manifest=first_manifest,
            release_tree_device=2049,
            release_tree_inode=73_501,
        )
        == receipt
    )
    with pytest.raises(ValueError, match="manifest binding"):
        require_runner_activation_release_publication_manifest_binding(
            receipt,
            release_tree_manifest=second_manifest,
            release_tree_device=2049,
            release_tree_inode=73_501,
        )


def test_self_consistent_receipt_is_not_manifest_storage_proof() -> None:
    receipt = _receipt()
    receipt["releaseTreeContentFingerprint"] = "sha256:" + "6" * 64
    receipt["releaseTreeManifestFingerprint"] = "sha256:" + "7" * 64

    assert require_runner_activation_release_publication_receipt(receipt) == (receipt)
    with pytest.raises(ValueError, match="manifest binding"):
        require_runner_activation_release_publication_manifest_binding(
            receipt,
            release_tree_manifest=_tree_manifest(),
            release_tree_device=2049,
            release_tree_inode=73_501,
        )


def test_binding_verifier_uses_caller_error_type() -> None:
    with pytest.raises(PublicationContractError, match="manifest binding"):
        require_runner_activation_release_publication_manifest_binding(
            _receipt(manifest=_tree_manifest(content="e")),
            release_tree_manifest=_tree_manifest(content="f"),
            release_tree_device=2049,
            release_tree_inode=73_501,
            make_error=PublicationContractError,
        )


@pytest.mark.parametrize(
    ("release_tree_device", "release_tree_inode"),
    [(2050, 73_501), (2049, 73_502)],
)
def test_binding_verifier_requires_the_opened_root_identity(
    release_tree_device: int,
    release_tree_inode: int,
) -> None:
    with pytest.raises(ValueError, match="root identity binding"):
        require_runner_activation_release_publication_manifest_binding(
            _receipt(),
            release_tree_manifest=_tree_manifest(),
            release_tree_device=release_tree_device,
            release_tree_inode=release_tree_inode,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("release_tree_device", True),
        ("release_tree_device", 0),
        ("release_tree_inode", False),
        ("release_tree_inode", -1),
    ],
)
def test_binding_verifier_rejects_invalid_opened_root_identity(
    field: str,
    value: object,
) -> None:
    arguments: dict[str, object] = {
        "release_tree_device": 2049,
        "release_tree_inode": 73_501,
    }
    arguments[field] = value

    with pytest.raises(ValueError, match="releasePublicationBinding"):
        require_runner_activation_release_publication_manifest_binding(
            _receipt(),
            release_tree_manifest=_tree_manifest(),
            **arguments,
        )


def test_archive_tree_manifest_intent_and_receipt_identities_are_distinct() -> None:
    intent = _intent()
    manifest = _tree_manifest()
    receipt = _receipt(intent=intent, manifest=manifest)
    identities = {
        str(intent["artifactArchiveSha256"]),
        str(intent["bootstrapManifestFingerprint"]),
        str(intent["archiveInspectionManifestFingerprint"]),
        runner_activation_release_tree_content_fingerprint(manifest),
        runner_activation_release_tree_manifest_fingerprint(manifest),
        runner_activation_release_publication_intent_fingerprint(intent),
        runner_activation_release_publication_receipt_fingerprint(receipt),
    }

    assert len(identities) == 7


def test_intent_allows_independently_derived_evidence_values_to_coincide() -> None:
    intent = _intent(bootstrap_manifest_fingerprint=ARCHIVE_SHA256)

    assert require_runner_activation_release_publication_intent(intent) == intent
    assert isinstance(
        runner_activation_release_publication_intent_fingerprint(intent),
        str,
    )


def test_receipt_allows_independently_derived_evidence_values_to_coincide() -> None:
    receipt = _receipt()
    receipt["releaseTreeManifestFingerprint"] = receipt["releaseTreeContentFingerprint"]

    assert require_runner_activation_release_publication_receipt(receipt) == receipt
    assert isinstance(
        runner_activation_release_publication_receipt_fingerprint(receipt),
        str,
    )


def test_receipt_canonicalization_is_stable_after_input_copy() -> None:
    receipt = _receipt()
    copied = deepcopy(receipt)

    assert runner_activation_release_publication_receipt_canonical_json(
        copied
    ) == runner_activation_release_publication_receipt_canonical_json(receipt)
    assert runner_activation_release_publication_receipt_fingerprint(copied) == (
        runner_activation_release_publication_receipt_fingerprint(receipt)
    )
