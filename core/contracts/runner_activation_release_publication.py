"""Dormant identities for installed remote-runner release publication.

This module describes publication intent and an observation-shaped receipt. It
does not extract an archive, walk or mutate a filesystem, prove durability,
authorize a generation, or constitute ``prepared`` evidence.  In particular,
a self-consistent receipt is not storage proof; callers must also supply the
actual installed release-tree manifest to the explicit binding verifier.
"""

from __future__ import annotations

from collections.abc import Callable
import hmac
import re

from .runner_activation_release_tree import (
    RUNNER_ACTIVATION_RELEASE_TREE_MATERIALIZATION_POLICY,
    require_runner_activation_release_tree_manifest,
    runner_activation_release_tree_content_fingerprint,
    runner_activation_release_tree_manifest_fingerprint,
)
from .runner_activation_target import RUNNER_ACTIVATION_SERVICE
from .runner_activation_validation import (
    canonical_json as _canonical_json,
    fingerprint as _fingerprint,
    require_exact_string as _require_exact_string,
    require_fingerprint as _require_fingerprint,
    require_id as _require_id,
    require_mapping as _require_mapping,
    require_positive_integer as _require_positive_integer,
)


RUNNER_ACTIVATION_RELEASE_PUBLICATION_INTENT_SCHEMA = (
    "h2ometa.runner-installed-release-publication-intent.v1"
)
RUNNER_ACTIVATION_RELEASE_PUBLICATION_RECEIPT_SCHEMA = (
    "h2ometa.runner-installed-release-publication-receipt.v1"
)
RUNNER_ACTIVATION_RELEASE_EXTRACTION_POLICY = (
    "h2ometa.runner-installed-release-extraction.v1"
)
RUNNER_ACTIVATION_RELEASE_RELOCATION_POLICY = (
    "h2ometa.runner-installed-release-relocation.v1"
)
RUNNER_ACTIVATION_RELEASE_PUBLICATION_SERVICE = RUNNER_ACTIVATION_SERVICE
RUNNER_ACTIVATION_RELEASE_OBJECTS_DIRECTORY = "release-objects"
RUNNER_ACTIVATION_RELEASE_PLATFORMS = frozenset({"linux-64", "linux-aarch64"})

_INTENT_FIELDS = frozenset(
    {
        "artifactArchiveSha256",
        "artifactArchiveSizeBytes",
        "artifactManifestFingerprint",
        "artifactPlatform",
        "artifactProvenanceFingerprint",
        "artifactVersion",
        "extractionPolicyVersion",
        "installationFingerprint",
        "materializationPolicyVersion",
        "publicationId",
        "releaseTreeRelativePath",
        "relocationPolicyVersion",
        "schemaVersion",
        "service",
    }
)
_RECEIPT_FIELDS = frozenset(
    {
        "intent",
        "intentFingerprint",
        "releaseTreeContentFingerprint",
        "releaseTreeDevice",
        "releaseTreeInode",
        "releaseTreeManifestFingerprint",
        "schemaVersion",
        "service",
    }
)
_ARTIFACT_VERSION_PATTERN = re.compile(
    r"^[0-9A-Za-z](?:[0-9A-Za-z._+-]{0,126}[0-9A-Za-z])?$"
)
_INTENT_FINGERPRINT_DOMAIN = RUNNER_ACTIVATION_RELEASE_PUBLICATION_INTENT_SCHEMA.encode(
    "ascii"
)
_RECEIPT_FINGERPRINT_DOMAIN = (
    RUNNER_ACTIVATION_RELEASE_PUBLICATION_RECEIPT_SCHEMA.encode("ascii")
)


def runner_activation_release_publication_relative_path(
    publication_id: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> str:
    """Derive the only release-tree path allowed for ``publication_id``."""

    normalized_id = _require_id(
        publication_id,
        "releasePublication.publicationId",
        make_error,
    )
    return f"{RUNNER_ACTIVATION_RELEASE_OBJECTS_DIRECTORY}/{normalized_id}"


def build_runner_activation_release_publication_intent(
    *,
    publication_id: object,
    installation_fingerprint: object,
    artifact_version: object,
    artifact_platform: object,
    artifact_archive_sha256: object,
    artifact_archive_size_bytes: object,
    artifact_manifest_fingerprint: object,
    artifact_provenance_fingerprint: object,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, object]:
    """Build an exact publication intent without accepting a caller path."""

    return require_runner_activation_release_publication_intent(
        {
            "artifactArchiveSha256": artifact_archive_sha256,
            "artifactArchiveSizeBytes": artifact_archive_size_bytes,
            "artifactManifestFingerprint": artifact_manifest_fingerprint,
            "artifactPlatform": artifact_platform,
            "artifactProvenanceFingerprint": artifact_provenance_fingerprint,
            "artifactVersion": artifact_version,
            "extractionPolicyVersion": (RUNNER_ACTIVATION_RELEASE_EXTRACTION_POLICY),
            "installationFingerprint": installation_fingerprint,
            "materializationPolicyVersion": (
                RUNNER_ACTIVATION_RELEASE_TREE_MATERIALIZATION_POLICY
            ),
            "publicationId": publication_id,
            "releaseTreeRelativePath": (
                runner_activation_release_publication_relative_path(
                    publication_id,
                    make_error=make_error,
                )
            ),
            "relocationPolicyVersion": (RUNNER_ACTIVATION_RELEASE_RELOCATION_POLICY),
            "schemaVersion": (RUNNER_ACTIVATION_RELEASE_PUBLICATION_INTENT_SCHEMA),
            "service": RUNNER_ACTIVATION_RELEASE_PUBLICATION_SERVICE,
        },
        make_error=make_error,
    )


def require_runner_activation_release_publication_intent(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, object]:
    """Validate a publication intent and return a detached normalized copy."""

    mapping = _require_mapping(
        payload,
        expected=_INTENT_FIELDS,
        context="runner activation release publication intent",
        make_error=make_error,
    )
    _require_exact_string(
        mapping.get("schemaVersion"),
        expected=RUNNER_ACTIVATION_RELEASE_PUBLICATION_INTENT_SCHEMA,
        field="releasePublicationIntent.schemaVersion",
        make_error=make_error,
    )
    _require_exact_string(
        mapping.get("service"),
        expected=RUNNER_ACTIVATION_RELEASE_PUBLICATION_SERVICE,
        field="releasePublicationIntent.service",
        make_error=make_error,
    )
    publication_id = _require_id(
        mapping.get("publicationId"),
        "releasePublicationIntent.publicationId",
        make_error,
    )
    expected_relative_path = runner_activation_release_publication_relative_path(
        publication_id,
        make_error=make_error,
    )
    _require_exact_string(
        mapping.get("releaseTreeRelativePath"),
        expected=expected_relative_path,
        field="releasePublicationIntent.releaseTreeRelativePath",
        make_error=make_error,
    )
    artifact_version = _require_artifact_version(
        mapping.get("artifactVersion"),
        make_error=make_error,
    )
    artifact_platform = mapping.get("artifactPlatform")
    if (
        not isinstance(artifact_platform, str)
        or artifact_platform not in RUNNER_ACTIVATION_RELEASE_PLATFORMS
    ):
        raise make_error(
            "runner activation releasePublicationIntent.artifactPlatform is invalid"
        )
    _require_exact_string(
        mapping.get("materializationPolicyVersion"),
        expected=RUNNER_ACTIVATION_RELEASE_TREE_MATERIALIZATION_POLICY,
        field="releasePublicationIntent.materializationPolicyVersion",
        make_error=make_error,
    )
    _require_exact_string(
        mapping.get("extractionPolicyVersion"),
        expected=RUNNER_ACTIVATION_RELEASE_EXTRACTION_POLICY,
        field="releasePublicationIntent.extractionPolicyVersion",
        make_error=make_error,
    )
    _require_exact_string(
        mapping.get("relocationPolicyVersion"),
        expected=RUNNER_ACTIVATION_RELEASE_RELOCATION_POLICY,
        field="releasePublicationIntent.relocationPolicyVersion",
        make_error=make_error,
    )
    installation_fingerprint = _require_fingerprint(
        mapping.get("installationFingerprint"),
        "releasePublicationIntent.installationFingerprint",
        make_error,
    )
    archive_sha256 = _require_fingerprint(
        mapping.get("artifactArchiveSha256"),
        "releasePublicationIntent.artifactArchiveSha256",
        make_error,
    )
    artifact_manifest_fingerprint = _require_fingerprint(
        mapping.get("artifactManifestFingerprint"),
        "releasePublicationIntent.artifactManifestFingerprint",
        make_error,
    )
    artifact_provenance_fingerprint = _require_fingerprint(
        mapping.get("artifactProvenanceFingerprint"),
        "releasePublicationIntent.artifactProvenanceFingerprint",
        make_error,
    )
    return {
        "artifactArchiveSha256": archive_sha256,
        "artifactArchiveSizeBytes": _require_positive_integer(
            mapping.get("artifactArchiveSizeBytes"),
            "releasePublicationIntent.artifactArchiveSizeBytes",
            make_error,
        ),
        "artifactManifestFingerprint": artifact_manifest_fingerprint,
        "artifactPlatform": artifact_platform,
        "artifactProvenanceFingerprint": artifact_provenance_fingerprint,
        "artifactVersion": artifact_version,
        "extractionPolicyVersion": RUNNER_ACTIVATION_RELEASE_EXTRACTION_POLICY,
        "installationFingerprint": installation_fingerprint,
        "materializationPolicyVersion": (
            RUNNER_ACTIVATION_RELEASE_TREE_MATERIALIZATION_POLICY
        ),
        "publicationId": publication_id,
        "releaseTreeRelativePath": expected_relative_path,
        "relocationPolicyVersion": RUNNER_ACTIVATION_RELEASE_RELOCATION_POLICY,
        "schemaVersion": RUNNER_ACTIVATION_RELEASE_PUBLICATION_INTENT_SCHEMA,
        "service": RUNNER_ACTIVATION_RELEASE_PUBLICATION_SERVICE,
    }


def runner_activation_release_publication_intent_canonical_json(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> str:
    return _canonical_json(
        require_runner_activation_release_publication_intent(
            payload,
            make_error=make_error,
        )
    )


def runner_activation_release_publication_intent_fingerprint(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> str:
    normalized = require_runner_activation_release_publication_intent(
        payload,
        make_error=make_error,
    )
    return _fingerprint(
        _INTENT_FINGERPRINT_DOMAIN,
        _canonical_json(normalized),
    )


def build_runner_activation_release_publication_receipt(
    *,
    intent: object,
    release_tree_manifest: object,
    release_tree_device: object,
    release_tree_inode: object,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, object]:
    """Derive a receipt from normalized intent and an actual tree manifest."""

    normalized_intent = require_runner_activation_release_publication_intent(
        intent,
        make_error=make_error,
    )
    manifest = require_runner_activation_release_tree_manifest(
        release_tree_manifest,
        make_error=make_error,
    )
    return require_runner_activation_release_publication_receipt(
        {
            "intent": normalized_intent,
            "intentFingerprint": (
                runner_activation_release_publication_intent_fingerprint(
                    normalized_intent,
                    make_error=make_error,
                )
            ),
            "releaseTreeContentFingerprint": (
                runner_activation_release_tree_content_fingerprint(
                    manifest,
                    make_error=make_error,
                )
            ),
            "releaseTreeDevice": release_tree_device,
            "releaseTreeInode": release_tree_inode,
            "releaseTreeManifestFingerprint": (
                runner_activation_release_tree_manifest_fingerprint(
                    manifest,
                    make_error=make_error,
                )
            ),
            "schemaVersion": (RUNNER_ACTIVATION_RELEASE_PUBLICATION_RECEIPT_SCHEMA),
            "service": RUNNER_ACTIVATION_RELEASE_PUBLICATION_SERVICE,
        },
        make_error=make_error,
    )


def require_runner_activation_release_publication_receipt(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, object]:
    """Validate receipt self-consistency, without claiming storage proof."""

    mapping = _require_mapping(
        payload,
        expected=_RECEIPT_FIELDS,
        context="runner activation release publication receipt",
        make_error=make_error,
    )
    _require_exact_string(
        mapping.get("schemaVersion"),
        expected=RUNNER_ACTIVATION_RELEASE_PUBLICATION_RECEIPT_SCHEMA,
        field="releasePublicationReceipt.schemaVersion",
        make_error=make_error,
    )
    _require_exact_string(
        mapping.get("service"),
        expected=RUNNER_ACTIVATION_RELEASE_PUBLICATION_SERVICE,
        field="releasePublicationReceipt.service",
        make_error=make_error,
    )
    intent = require_runner_activation_release_publication_intent(
        mapping.get("intent"),
        make_error=make_error,
    )
    intent_fingerprint = _require_fingerprint(
        mapping.get("intentFingerprint"),
        "releasePublicationReceipt.intentFingerprint",
        make_error,
    )
    expected_intent_fingerprint = (
        runner_activation_release_publication_intent_fingerprint(
            intent,
            make_error=make_error,
        )
    )
    if not hmac.compare_digest(
        intent_fingerprint,
        expected_intent_fingerprint,
    ):
        raise make_error(
            "runner activation release publication receipt intent binding is invalid"
        )
    tree_content_fingerprint = _require_fingerprint(
        mapping.get("releaseTreeContentFingerprint"),
        "releasePublicationReceipt.releaseTreeContentFingerprint",
        make_error,
    )
    tree_manifest_fingerprint = _require_fingerprint(
        mapping.get("releaseTreeManifestFingerprint"),
        "releasePublicationReceipt.releaseTreeManifestFingerprint",
        make_error,
    )
    return {
        "intent": intent,
        "intentFingerprint": intent_fingerprint,
        "releaseTreeContentFingerprint": tree_content_fingerprint,
        "releaseTreeDevice": _require_positive_integer(
            mapping.get("releaseTreeDevice"),
            "releasePublicationReceipt.releaseTreeDevice",
            make_error,
        ),
        "releaseTreeInode": _require_positive_integer(
            mapping.get("releaseTreeInode"),
            "releasePublicationReceipt.releaseTreeInode",
            make_error,
        ),
        "releaseTreeManifestFingerprint": tree_manifest_fingerprint,
        "schemaVersion": RUNNER_ACTIVATION_RELEASE_PUBLICATION_RECEIPT_SCHEMA,
        "service": RUNNER_ACTIVATION_RELEASE_PUBLICATION_SERVICE,
    }


def require_runner_activation_release_publication_manifest_binding(
    receipt_payload: object,
    *,
    release_tree_manifest: object,
    release_tree_device: object,
    release_tree_inode: object,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, object]:
    """Bind a receipt to the supplied manifest and opened root identity."""

    receipt = require_runner_activation_release_publication_receipt(
        receipt_payload,
        make_error=make_error,
    )
    manifest = require_runner_activation_release_tree_manifest(
        release_tree_manifest,
        make_error=make_error,
    )
    expected_content_fingerprint = runner_activation_release_tree_content_fingerprint(
        manifest,
        make_error=make_error,
    )
    expected_manifest_fingerprint = runner_activation_release_tree_manifest_fingerprint(
        manifest,
        make_error=make_error,
    )
    if not hmac.compare_digest(
        str(receipt["releaseTreeContentFingerprint"]),
        expected_content_fingerprint,
    ) or not hmac.compare_digest(
        str(receipt["releaseTreeManifestFingerprint"]),
        expected_manifest_fingerprint,
    ):
        raise make_error(
            "runner activation release publication receipt manifest binding is invalid"
        )
    intent = receipt["intent"]
    if not isinstance(intent, dict):  # pragma: no cover - validator invariant.
        raise make_error(
            "runner activation release publication receipt intent is invalid"
        )
    if (
        intent["materializationPolicyVersion"]
        != manifest["materializationPolicyVersion"]
    ):
        raise make_error(
            "runner activation release publication materialization binding is invalid"
        )
    observed_device = _require_positive_integer(
        release_tree_device,
        "releasePublicationBinding.releaseTreeDevice",
        make_error,
    )
    observed_inode = _require_positive_integer(
        release_tree_inode,
        "releasePublicationBinding.releaseTreeInode",
        make_error,
    )
    if (
        receipt["releaseTreeDevice"] != observed_device
        or receipt["releaseTreeInode"] != observed_inode
    ):
        raise make_error(
            "runner activation release publication root identity binding is invalid"
        )
    return receipt


def runner_activation_release_publication_receipt_canonical_json(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> str:
    return _canonical_json(
        require_runner_activation_release_publication_receipt(
            payload,
            make_error=make_error,
        )
    )


def runner_activation_release_publication_receipt_fingerprint(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> str:
    normalized = require_runner_activation_release_publication_receipt(
        payload,
        make_error=make_error,
    )
    return _fingerprint(
        _RECEIPT_FINGERPRINT_DOMAIN,
        _canonical_json(normalized),
    )


def _require_artifact_version(
    value: object,
    *,
    make_error: Callable[[str], Exception],
) -> str:
    if (
        not isinstance(value, str)
        or _ARTIFACT_VERSION_PATTERN.fullmatch(value) is None
        or ".." in value
    ):
        raise make_error(
            "runner activation releasePublicationIntent.artifactVersion is invalid"
        )
    return value


__all__ = [
    "RUNNER_ACTIVATION_RELEASE_EXTRACTION_POLICY",
    "RUNNER_ACTIVATION_RELEASE_OBJECTS_DIRECTORY",
    "RUNNER_ACTIVATION_RELEASE_PLATFORMS",
    "RUNNER_ACTIVATION_RELEASE_PUBLICATION_INTENT_SCHEMA",
    "RUNNER_ACTIVATION_RELEASE_PUBLICATION_RECEIPT_SCHEMA",
    "RUNNER_ACTIVATION_RELEASE_PUBLICATION_SERVICE",
    "RUNNER_ACTIVATION_RELEASE_RELOCATION_POLICY",
    "build_runner_activation_release_publication_intent",
    "build_runner_activation_release_publication_receipt",
    "require_runner_activation_release_publication_intent",
    "require_runner_activation_release_publication_manifest_binding",
    "require_runner_activation_release_publication_receipt",
    "runner_activation_release_publication_intent_canonical_json",
    "runner_activation_release_publication_intent_fingerprint",
    "runner_activation_release_publication_receipt_canonical_json",
    "runner_activation_release_publication_receipt_fingerprint",
    "runner_activation_release_publication_relative_path",
]
