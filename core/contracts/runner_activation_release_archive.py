"""Dormant identities for an inspected remote-runner release archive.

This contract describes normalized metadata produced by a future bounded
archive inspector. It does not open an archive, extract a member, write a
filesystem tree, verify provenance, authorize publication, or constitute
``prepared`` evidence. A self-consistent manifest is not proof that any archive
bytes were actually inspected.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import hmac

from .runner_activation_release_archive_graph import (
    RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_MEMBER_BYTES,
    RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_MEMBER_METADATA_BYTES,
    RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_MEMBERS,
    RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_TOTAL_BYTES,
    _project_runner_activation_release_archive_materialization_entries,
    require_runner_activation_release_archive_members,
)
from .runner_activation_release_bootstrap_manifest import (
    RUNNER_ACTIVATION_RELEASE_ARTIFACT_PLATFORMS,
    RUNNER_ACTIVATION_RELEASE_BOOTSTRAP_MANIFEST_MAX_BYTES,
    RUNNER_ACTIVATION_RELEASE_BOOTSTRAP_MANIFEST_PATH,
    require_runner_activation_release_artifact_platform,
    require_runner_activation_release_artifact_version,
    require_runner_activation_release_bootstrap_manifest,
    require_runner_activation_release_bootstrap_manifest_bytes,
    runner_activation_release_bootstrap_manifest_content_sha256,
    runner_activation_release_bootstrap_manifest_fingerprint,
)
from .runner_activation_release_tree import (
    build_runner_activation_release_tree_manifest,
    runner_activation_release_tree_content_fingerprint,
)
from .runner_activation_target import RUNNER_ACTIVATION_SERVICE
from .runner_activation_validation import (
    canonical_json as _canonical_json,
    fingerprint as _fingerprint,
    require_exact_string as _require_exact_string,
    require_fingerprint as _require_fingerprint,
    require_mapping as _require_mapping,
    require_positive_integer as _require_positive_integer,
)


RUNNER_ACTIVATION_RELEASE_ARCHIVE_MANIFEST_SCHEMA = (
    "h2ometa.runner-installed-release-archive-manifest.v1"
)
RUNNER_ACTIVATION_RELEASE_ARCHIVE_FORMAT = "tar+gzip"
RUNNER_ACTIVATION_RELEASE_ARCHIVE_EXTRACTION_POLICY = (
    "h2ometa.runner-installed-release-extraction.v1"
)
RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_SIZE_BYTES = 2 * 1024**3
RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_UNCOMPRESSED_SIZE_BYTES = 32 * 1024**3
RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_MANIFEST_BYTES = 40 * 1024**2
RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_COMPRESSION_RATIO = 200
RUNNER_ACTIVATION_RELEASE_ARCHIVE_COMPRESSION_RATIO_FLOOR_BYTES = 64 * 1024**2
RUNNER_ACTIVATION_RELEASE_ARTIFACT_MANIFEST_PATH = (
    RUNNER_ACTIVATION_RELEASE_BOOTSTRAP_MANIFEST_PATH
)

_MANIFEST_FIELDS = frozenset(
    {
        "archiveFormat",
        "artifactArchiveSha256",
        "artifactArchiveSizeBytes",
        "bootstrapManifest",
        "bootstrapManifestContentSha256",
        "bootstrapManifestFingerprint",
        "bootstrapManifestPath",
        "extractionPolicyVersion",
        "memberCount",
        "members",
        "schemaVersion",
        "service",
        "totalMemberMetadataBytes",
        "totalPayloadBytes",
        "totalTreeFileBytes",
        "uncompressedArchiveSizeBytes",
    }
)
_MIN_TAR_STREAM_BYTES = 2 * 512
_TAR_BLOCK_BYTES = 512
_MANIFEST_FINGERPRINT_DOMAIN = RUNNER_ACTIVATION_RELEASE_ARCHIVE_MANIFEST_SCHEMA.encode(
    "ascii"
)


def build_runner_activation_release_archive_manifest(
    *,
    artifact_archive_sha256: object,
    artifact_archive_size_bytes: object,
    bootstrap_manifest_bytes: object,
    uncompressed_archive_size_bytes: object,
    members: object,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, object]:
    """Build an exact manifest from already inspected archive metadata and bytes."""

    normalized_members, total_member_metadata_bytes = (
        require_runner_activation_release_archive_members(
            members,
            make_error=make_error,
        )
    )
    bootstrap_manifest = require_runner_activation_release_bootstrap_manifest_bytes(
        bootstrap_manifest_bytes,
        make_error=make_error,
    )
    bootstrap_content_sha256 = (
        runner_activation_release_bootstrap_manifest_content_sha256(
            bootstrap_manifest_bytes,
            make_error=make_error,
        )
    )
    _require_bootstrap_manifest_member(
        normalized_members,
        expected_content_sha256=bootstrap_content_sha256,
        expected_size_bytes=len(bootstrap_manifest_bytes),
        make_error=make_error,
    )
    return require_runner_activation_release_archive_manifest(
        _normalized_manifest(
            artifact_archive_sha256=artifact_archive_sha256,
            artifact_archive_size_bytes=artifact_archive_size_bytes,
            bootstrap_manifest=bootstrap_manifest,
            bootstrap_manifest_content_sha256=bootstrap_content_sha256,
            uncompressed_archive_size_bytes=uncompressed_archive_size_bytes,
            members=normalized_members,
            total_member_metadata_bytes=total_member_metadata_bytes,
        ),
        make_error=make_error,
    )


def require_runner_activation_release_archive_manifest(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, object]:
    """Validate and deeply detach one normalized archive inspection record."""

    mapping = _require_mapping(
        payload,
        expected=_MANIFEST_FIELDS,
        context="runner activation installed release archive manifest",
        make_error=make_error,
    )
    _require_exact_string(
        mapping.get("schemaVersion"),
        expected=RUNNER_ACTIVATION_RELEASE_ARCHIVE_MANIFEST_SCHEMA,
        field="releaseArchiveManifest.schemaVersion",
        make_error=make_error,
    )
    _require_exact_string(
        mapping.get("service"),
        expected=RUNNER_ACTIVATION_SERVICE,
        field="releaseArchiveManifest.service",
        make_error=make_error,
    )
    _require_exact_string(
        mapping.get("archiveFormat"),
        expected=RUNNER_ACTIVATION_RELEASE_ARCHIVE_FORMAT,
        field="releaseArchiveManifest.archiveFormat",
        make_error=make_error,
    )
    _require_exact_string(
        mapping.get("extractionPolicyVersion"),
        expected=RUNNER_ACTIVATION_RELEASE_ARCHIVE_EXTRACTION_POLICY,
        field="releaseArchiveManifest.extractionPolicyVersion",
        make_error=make_error,
    )
    archive_sha256 = _require_fingerprint(
        mapping.get("artifactArchiveSha256"),
        "releaseArchiveManifest.artifactArchiveSha256",
        make_error,
    )
    archive_size = _require_positive_integer(
        mapping.get("artifactArchiveSizeBytes"),
        "releaseArchiveManifest.artifactArchiveSizeBytes",
        make_error,
    )
    if archive_size > RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_SIZE_BYTES:
        raise make_error(
            "runner activation installed release archive size exceeds policy"
        )
    uncompressed_archive_size = _require_uncompressed_archive_size(
        mapping.get("uncompressedArchiveSizeBytes"),
        archive_size=archive_size,
        make_error=make_error,
    )
    bootstrap_manifest = require_runner_activation_release_bootstrap_manifest(
        mapping.get("bootstrapManifest"),
        make_error=make_error,
    )
    bootstrap_fingerprint = _require_fingerprint(
        mapping.get("bootstrapManifestFingerprint"),
        "releaseArchiveManifest.bootstrapManifestFingerprint",
        make_error,
    )
    expected_bootstrap_fingerprint = (
        runner_activation_release_bootstrap_manifest_fingerprint(
            bootstrap_manifest,
            make_error=make_error,
        )
    )
    if not hmac.compare_digest(
        bootstrap_fingerprint,
        expected_bootstrap_fingerprint,
    ):
        raise make_error(
            "runner activation installed release archive bootstrap manifest "
            "binding is invalid"
        )
    bootstrap_content_sha256 = _require_fingerprint(
        mapping.get("bootstrapManifestContentSha256"),
        "releaseArchiveManifest.bootstrapManifestContentSha256",
        make_error,
    )
    _require_exact_string(
        mapping.get("bootstrapManifestPath"),
        expected=RUNNER_ACTIVATION_RELEASE_BOOTSTRAP_MANIFEST_PATH,
        field="releaseArchiveManifest.bootstrapManifestPath",
        make_error=make_error,
    )

    members, total_member_metadata_bytes = (
        require_runner_activation_release_archive_members(
            mapping.get("members"),
            make_error=make_error,
        )
    )
    _require_bootstrap_manifest_member(
        members,
        expected_content_sha256=bootstrap_content_sha256,
        expected_size_bytes=None,
        make_error=make_error,
    )
    expected = _normalized_manifest(
        artifact_archive_sha256=archive_sha256,
        artifact_archive_size_bytes=archive_size,
        bootstrap_manifest=bootstrap_manifest,
        bootstrap_manifest_content_sha256=bootstrap_content_sha256,
        uncompressed_archive_size_bytes=uncompressed_archive_size,
        members=members,
        total_member_metadata_bytes=total_member_metadata_bytes,
    )
    _require_summary_binding(mapping, expected=expected, make_error=make_error)
    if uncompressed_archive_size < _minimum_tar_stream_size_bytes(members):
        raise make_error(
            "runner activation installed release archive stream binding is invalid"
        )
    if (
        _canonical_manifest_size_bytes(expected)
        > RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_MANIFEST_BYTES
    ):
        raise make_error(
            "runner activation installed release archive manifest size exceeds policy"
        )
    return expected


def runner_activation_release_archive_manifest_canonical_json(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> str:
    canonical = _canonical_json(
        require_runner_activation_release_archive_manifest(
            payload,
            make_error=make_error,
        )
    )
    if (
        len(canonical.encode("utf-8"))
        > RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_MANIFEST_BYTES
    ):
        raise make_error(
            "runner activation installed release archive manifest size exceeds policy"
        )
    return canonical


def runner_activation_release_archive_manifest_fingerprint(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> str:
    return _fingerprint(
        _MANIFEST_FINGERPRINT_DOMAIN,
        runner_activation_release_archive_manifest_canonical_json(
            payload,
            make_error=make_error,
        ),
    )


def project_runner_activation_release_archive_materialization_entries(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> list[dict[str, object]]:
    """Derive the only runtime materialization projection for an archive.

    The returned entries describe source topology before relocation.  They are
    not a filesystem observation, publication receipt, or portable plan.  The
    extra ``payloadSourcePath`` routes each canonical file to the one raw USTAR
    regular member whose bytes it consumes; it is excluded from tree identity.
    """

    manifest = require_runner_activation_release_archive_manifest(
        payload,
        make_error=make_error,
    )
    return _project_runner_activation_release_archive_materialization_entries(
        manifest["members"],
        make_error=make_error,
    )


def runner_activation_release_archive_projected_tree_content_fingerprint(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> str:
    """Fingerprint the logical source tree without claiming it was installed."""

    projected = project_runner_activation_release_archive_materialization_entries(
        payload,
        make_error=make_error,
    )
    tree_entries = [
        {
            "contentSha256": entry["contentSha256"],
            "linkTarget": entry["linkTarget"],
            "mode": entry["mode"],
            "path": entry["path"],
            "sizeBytes": entry["sizeBytes"],
            "type": entry["type"],
        }
        for entry in projected
    ]
    manifest = build_runner_activation_release_tree_manifest(
        tree_entries,
        make_error=make_error,
    )
    return runner_activation_release_tree_content_fingerprint(
        manifest,
        make_error=make_error,
    )


def _normalized_manifest(
    *,
    artifact_archive_sha256: object,
    artifact_archive_size_bytes: object,
    bootstrap_manifest: Mapping[str, object],
    bootstrap_manifest_content_sha256: object,
    uncompressed_archive_size_bytes: object,
    members: list[dict[str, object]],
    total_member_metadata_bytes: int,
) -> dict[str, object]:
    detached_members = [dict(member) for member in members]
    by_path = {str(member["path"]): member for member in detached_members}
    total_payload_bytes = sum(
        int(member["sizeBytes"])
        for member in detached_members
        if member["type"] == "file"
    )
    total_tree_file_bytes = sum(
        int(member["sizeBytes"])
        if member["type"] == "file"
        else int(by_path[str(member["linkTarget"])]["sizeBytes"])
        for member in detached_members
        if member["type"] in {"file", "hardlink"}
    )
    return {
        "archiveFormat": RUNNER_ACTIVATION_RELEASE_ARCHIVE_FORMAT,
        "artifactArchiveSha256": artifact_archive_sha256,
        "artifactArchiveSizeBytes": artifact_archive_size_bytes,
        "bootstrapManifest": dict(bootstrap_manifest),
        "bootstrapManifestContentSha256": bootstrap_manifest_content_sha256,
        "bootstrapManifestFingerprint": (
            runner_activation_release_bootstrap_manifest_fingerprint(bootstrap_manifest)
        ),
        "bootstrapManifestPath": RUNNER_ACTIVATION_RELEASE_BOOTSTRAP_MANIFEST_PATH,
        "extractionPolicyVersion": RUNNER_ACTIVATION_RELEASE_ARCHIVE_EXTRACTION_POLICY,
        "memberCount": len(detached_members),
        "members": detached_members,
        "schemaVersion": RUNNER_ACTIVATION_RELEASE_ARCHIVE_MANIFEST_SCHEMA,
        "service": RUNNER_ACTIVATION_SERVICE,
        "totalMemberMetadataBytes": total_member_metadata_bytes,
        "totalPayloadBytes": total_payload_bytes,
        "totalTreeFileBytes": total_tree_file_bytes,
        "uncompressedArchiveSizeBytes": uncompressed_archive_size_bytes,
    }


def _require_uncompressed_archive_size(
    value: object,
    *,
    archive_size: int,
    make_error: Callable[[str], Exception],
) -> int:
    observed = _require_positive_integer(
        value,
        "releaseArchiveManifest.uncompressedArchiveSizeBytes",
        make_error,
    )
    if observed < _MIN_TAR_STREAM_BYTES or observed % _TAR_BLOCK_BYTES != 0:
        raise make_error(
            "runner activation releaseArchiveManifest.uncompressedArchiveSizeBytes "
            "is invalid"
        )
    if observed > RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_UNCOMPRESSED_SIZE_BYTES:
        raise make_error(
            "runner activation installed release archive uncompressed size exceeds policy"
        )
    if observed > max(
        RUNNER_ACTIVATION_RELEASE_ARCHIVE_COMPRESSION_RATIO_FLOOR_BYTES,
        archive_size * RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_COMPRESSION_RATIO,
    ):
        raise make_error(
            "runner activation installed release archive expansion ratio exceeds policy"
        )
    return observed


def _require_summary_binding(
    mapping: Mapping[str, object],
    *,
    expected: Mapping[str, object],
    make_error: Callable[[str], Exception],
) -> None:
    for field in (
        "memberCount",
        "totalMemberMetadataBytes",
        "totalPayloadBytes",
        "totalTreeFileBytes",
    ):
        observed = mapping.get(field)
        if isinstance(observed, bool) or not isinstance(observed, int) or observed < 0:
            raise make_error(
                f"runner activation releaseArchiveManifest.{field} is invalid"
            )
        if observed != expected[field]:
            raise make_error(
                "runner activation installed release archive summary binding is invalid"
            )


def _require_bootstrap_manifest_member(
    members: Sequence[dict[str, object]],
    *,
    expected_content_sha256: str,
    expected_size_bytes: int | None,
    make_error: Callable[[str], Exception],
) -> None:
    member = next(
        (
            candidate
            for candidate in members
            if candidate["path"] == RUNNER_ACTIVATION_RELEASE_BOOTSTRAP_MANIFEST_PATH
        ),
        None,
    )
    if (
        member is None
        or member["type"] != "file"
        or member["mode"] != "0644"
        or not 0
        < int(member["sizeBytes"])
        <= RUNNER_ACTIVATION_RELEASE_BOOTSTRAP_MANIFEST_MAX_BYTES
        or member["contentSha256"] != expected_content_sha256
        or (
            expected_size_bytes is not None
            and member["sizeBytes"] != expected_size_bytes
        )
    ):
        raise make_error(
            "runner activation installed release archive bootstrap manifest member "
            "is invalid"
        )


def _canonical_manifest_size_bytes(manifest: Mapping[str, object]) -> int:
    without_members = dict(manifest)
    without_members["members"] = []
    top_level_bytes = len(_canonical_json(without_members).encode("utf-8"))
    return (
        top_level_bytes
        + int(manifest["totalMemberMetadataBytes"])
        + max(0, int(manifest["memberCount"]) - 1)
    )


def _minimum_tar_stream_size_bytes(members: Sequence[dict[str, object]]) -> int:
    payload_blocks = sum(
        ((int(member["sizeBytes"]) + _TAR_BLOCK_BYTES - 1) // _TAR_BLOCK_BYTES)
        * _TAR_BLOCK_BYTES
        for member in members
        if member["type"] == "file"
    )
    return len(members) * _TAR_BLOCK_BYTES + payload_blocks + _MIN_TAR_STREAM_BYTES


__all__ = [
    "RUNNER_ACTIVATION_RELEASE_ARCHIVE_COMPRESSION_RATIO_FLOOR_BYTES",
    "RUNNER_ACTIVATION_RELEASE_ARCHIVE_EXTRACTION_POLICY",
    "RUNNER_ACTIVATION_RELEASE_ARCHIVE_FORMAT",
    "RUNNER_ACTIVATION_RELEASE_ARCHIVE_MANIFEST_SCHEMA",
    "RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_COMPRESSION_RATIO",
    "RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_MANIFEST_BYTES",
    "RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_MEMBER_BYTES",
    "RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_MEMBER_METADATA_BYTES",
    "RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_MEMBERS",
    "RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_SIZE_BYTES",
    "RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_TOTAL_BYTES",
    "RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_UNCOMPRESSED_SIZE_BYTES",
    "RUNNER_ACTIVATION_RELEASE_ARTIFACT_MANIFEST_PATH",
    "RUNNER_ACTIVATION_RELEASE_ARTIFACT_PLATFORMS",
    "build_runner_activation_release_archive_manifest",
    "project_runner_activation_release_archive_materialization_entries",
    "require_runner_activation_release_archive_manifest",
    "require_runner_activation_release_artifact_platform",
    "require_runner_activation_release_artifact_version",
    "runner_activation_release_archive_manifest_canonical_json",
    "runner_activation_release_archive_manifest_fingerprint",
    "runner_activation_release_archive_projected_tree_content_fingerprint",
]
