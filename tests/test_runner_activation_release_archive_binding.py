from __future__ import annotations

import hashlib
import json

import pytest

from core.contracts.runner_activation_release_archive import (
    RUNNER_ACTIVATION_RELEASE_ARTIFACT_MANIFEST_PATH,
    build_runner_activation_release_archive_manifest,
    runner_activation_release_archive_manifest_fingerprint,
)
from core.contracts.runner_activation_release_publication import (
    build_runner_activation_release_publication_intent,
    require_runner_activation_release_publication_archive_binding,
)
from core.contracts.runner_activation_target import RUNNER_ACTIVATION_SERVICE
from core.contracts.runner_protocol import (
    build_runner_protocol_descriptor,
    runner_protocol_descriptor_fingerprint,
)


ARCHIVE_SHA256 = "sha256:" + "a" * 64
PAYLOAD_SHA256 = "sha256:" + "b" * 64
PROVENANCE_FINGERPRINT = "sha256:" + "c" * 64
PROTOCOL_DESCRIPTOR = build_runner_protocol_descriptor()
BOOTSTRAP_MANIFEST = {
    "platform": "linux-64",
    "runnerProtocol": PROTOCOL_DESCRIPTOR,
    "runnerProtocolFingerprint": runner_protocol_descriptor_fingerprint(
        PROTOCOL_DESCRIPTOR
    ),
    "runtime": {
        "provider": "bundled",
        "python": "runtime/bin/python",
        "sqlite": {"minimumVersion": "3.51.3"},
    },
    "service": RUNNER_ACTIVATION_SERVICE,
    "version": "0.2.0",
}
BOOTSTRAP_BYTES = json.dumps(
    BOOTSTRAP_MANIFEST,
    allow_nan=False,
    ensure_ascii=False,
    separators=(",", ":"),
    sort_keys=True,
).encode("utf-8")
BOOTSTRAP_SHA256 = "sha256:" + hashlib.sha256(BOOTSTRAP_BYTES).hexdigest()


class ArchiveBindingError(RuntimeError):
    pass


def _archive_manifest() -> dict[str, object]:
    return build_runner_activation_release_archive_manifest(
        artifact_archive_sha256=ARCHIVE_SHA256,
        artifact_archive_size_bytes=4_096,
        bootstrap_manifest_bytes=BOOTSTRAP_BYTES,
        uncompressed_archive_size_bytes=10_240,
        members=[
            {
                "contentSha256": BOOTSTRAP_SHA256,
                "linkTarget": "",
                "mode": "0644",
                "path": RUNNER_ACTIVATION_RELEASE_ARTIFACT_MANIFEST_PATH,
                "sizeBytes": len(BOOTSTRAP_BYTES),
                "type": "file",
            },
            {
                "contentSha256": PAYLOAD_SHA256,
                "linkTarget": "",
                "mode": "0755",
                "path": "runner",
                "sizeBytes": 12,
                "type": "file",
            },
        ],
    )


def _intent(
    manifest: dict[str, object],
    **overrides: object,
) -> dict[str, object]:
    bootstrap = manifest["bootstrapManifest"]
    assert isinstance(bootstrap, dict)
    arguments: dict[str, object] = {
        "publication_id": "1" * 32,
        "installation_fingerprint": "sha256:" + "2" * 64,
        "artifact_version": bootstrap["version"],
        "artifact_platform": bootstrap["platform"],
        "artifact_archive_sha256": manifest["artifactArchiveSha256"],
        "artifact_archive_size_bytes": manifest["artifactArchiveSizeBytes"],
        "bootstrap_manifest_fingerprint": manifest["bootstrapManifestFingerprint"],
        "archive_inspection_manifest_fingerprint": (
            runner_activation_release_archive_manifest_fingerprint(manifest)
        ),
        "artifact_provenance_fingerprint": PROVENANCE_FINGERPRINT,
    }
    arguments.update(overrides)
    return build_runner_activation_release_publication_intent(**arguments)


def test_publication_intent_binds_bounded_bootstrap_and_archive_identities() -> None:
    manifest = _archive_manifest()
    intent = _intent(manifest)

    assert (
        require_runner_activation_release_publication_archive_binding(
            intent,
            archive_manifest=manifest,
        )
        == intent
    )


@pytest.mark.parametrize(
    "override",
    [
        {"artifact_archive_sha256": "sha256:" + "1" * 64},
        {"artifact_archive_size_bytes": 4_097},
        {"bootstrap_manifest_fingerprint": "sha256:" + "3" * 64},
        {"archive_inspection_manifest_fingerprint": "sha256:" + "4" * 64},
        {"artifact_version": "0.2.1"},
        {"artifact_platform": "linux-aarch64"},
    ],
)
def test_publication_intent_rejects_archive_or_bootstrap_binding_drift(
    override: dict[str, object],
) -> None:
    manifest = _archive_manifest()
    intent = _intent(manifest, **override)

    with pytest.raises(ValueError, match="archive binding"):
        require_runner_activation_release_publication_archive_binding(
            intent,
            archive_manifest=manifest,
        )


def test_archive_publication_binding_uses_the_caller_error_type() -> None:
    manifest = _archive_manifest()
    intent = _intent(
        manifest,
        archive_inspection_manifest_fingerprint="sha256:" + "4" * 64,
    )

    with pytest.raises(ArchiveBindingError, match="archive binding"):
        require_runner_activation_release_publication_archive_binding(
            intent,
            archive_manifest=manifest,
            make_error=ArchiveBindingError,
        )
