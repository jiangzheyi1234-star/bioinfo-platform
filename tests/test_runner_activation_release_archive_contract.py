from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

import core.contracts.runner_activation_release_archive as archive_contract
import core.contracts.runner_activation_release_archive_graph as archive_graph_contract
from core.contracts.runner_activation_release_archive import (
    RUNNER_ACTIVATION_RELEASE_ARCHIVE_EXTRACTION_POLICY,
    RUNNER_ACTIVATION_RELEASE_ARCHIVE_FORMAT,
    RUNNER_ACTIVATION_RELEASE_ARCHIVE_MANIFEST_SCHEMA,
    RUNNER_ACTIVATION_RELEASE_ARTIFACT_MANIFEST_PATH,
    build_runner_activation_release_archive_manifest,
    require_runner_activation_release_archive_manifest,
    runner_activation_release_archive_manifest_canonical_json,
    runner_activation_release_archive_manifest_fingerprint,
)
from core.contracts.runner_activation_release_bootstrap_manifest import (
    runner_activation_release_bootstrap_manifest_fingerprint,
)
from core.contracts.runner_activation_target import RUNNER_ACTIVATION_SERVICE
from core.contracts.runner_protocol import (
    build_runner_protocol_descriptor,
    runner_protocol_descriptor_fingerprint,
)


ARCHIVE_SHA256 = "sha256:" + "a" * 64
EXECUTABLE_SHA256 = "sha256:" + "b" * 64
DATA_SHA256 = "sha256:" + "c" * 64
ARCHIVE_SIZE_BYTES = 4_096
UNCOMPRESSED_ARCHIVE_SIZE_BYTES = 10_240
PROTOCOL_DESCRIPTOR = build_runner_protocol_descriptor()
BOOTSTRAP_MANIFEST = {
    "platform": "linux-64",
    "runnerProtocol": PROTOCOL_DESCRIPTOR,
    "runnerProtocolFingerprint": runner_protocol_descriptor_fingerprint(
        PROTOCOL_DESCRIPTOR
    ),
    "runtime": {"provider": "bundled", "python": "runtime/bin/python"},
    "service": RUNNER_ACTIVATION_SERVICE,
    "version": "0.2.0",
}
BOOTSTRAP_MANIFEST_BYTES = json.dumps(
    BOOTSTRAP_MANIFEST,
    allow_nan=False,
    ensure_ascii=False,
    separators=(",", ":"),
    sort_keys=True,
).encode("utf-8")
BOOTSTRAP_MANIFEST_SHA256 = (
    "sha256:" + hashlib.sha256(BOOTSTRAP_MANIFEST_BYTES).hexdigest()
)
BOOTSTRAP_MANIFEST_FINGERPRINT = (
    runner_activation_release_bootstrap_manifest_fingerprint(BOOTSTRAP_MANIFEST)
)

MANIFEST_FIELDS = {
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
MEMBER_FIELDS = {
    "contentSha256",
    "linkTarget",
    "mode",
    "path",
    "sizeBytes",
    "type",
}


class ArchiveContractError(RuntimeError):
    pass


def _members() -> list[dict[str, object]]:
    return [
        {
            "contentSha256": "",
            "linkTarget": "",
            "mode": "0755",
            "path": "bin",
            "sizeBytes": 0,
            "type": "directory",
        },
        {
            "contentSha256": EXECUTABLE_SHA256,
            "linkTarget": "",
            "mode": "0755",
            "path": "bin/python",
            "sizeBytes": 12,
            "type": "file",
        },
        {
            "contentSha256": BOOTSTRAP_MANIFEST_SHA256,
            "linkTarget": "",
            "mode": "0644",
            "path": RUNNER_ACTIVATION_RELEASE_ARTIFACT_MANIFEST_PATH,
            "sizeBytes": len(BOOTSTRAP_MANIFEST_BYTES),
            "type": "file",
        },
        {
            "contentSha256": "",
            "linkTarget": "",
            "mode": "0755",
            "path": "lib",
            "sizeBytes": 0,
            "type": "directory",
        },
        {
            "contentSha256": DATA_SHA256,
            "linkTarget": "",
            "mode": "0644",
            "path": "lib/data",
            "sizeBytes": 8,
            "type": "file",
        },
        {
            "contentSha256": "",
            "linkTarget": "lib/data",
            "mode": "0644",
            "path": "lib/data-copy",
            "sizeBytes": 0,
            "type": "hardlink",
        },
        {
            "contentSha256": "",
            "linkTarget": "bin/python",
            "mode": "0777",
            "path": "python-link",
            "sizeBytes": 0,
            "type": "symlink",
        },
    ]


def _manifest(
    *,
    artifact_archive_sha256: object = ARCHIVE_SHA256,
    artifact_archive_size_bytes: object = ARCHIVE_SIZE_BYTES,
    bootstrap_manifest_bytes: object = BOOTSTRAP_MANIFEST_BYTES,
    uncompressed_archive_size_bytes: object = UNCOMPRESSED_ARCHIVE_SIZE_BYTES,
    members: object | None = None,
) -> dict[str, object]:
    return build_runner_activation_release_archive_manifest(
        artifact_archive_sha256=artifact_archive_sha256,
        artifact_archive_size_bytes=artifact_archive_size_bytes,
        bootstrap_manifest_bytes=bootstrap_manifest_bytes,
        uncompressed_archive_size_bytes=uncompressed_archive_size_bytes,
        members=_members() if members is None else members,
    )


def test_archive_manifest_builder_emits_exact_policy_bound_shape() -> None:
    manifest = _manifest()

    assert set(manifest) == MANIFEST_FIELDS
    assert manifest["schemaVersion"] == (
        RUNNER_ACTIVATION_RELEASE_ARCHIVE_MANIFEST_SCHEMA
    )
    assert manifest["service"] == RUNNER_ACTIVATION_SERVICE
    assert manifest["archiveFormat"] == RUNNER_ACTIVATION_RELEASE_ARCHIVE_FORMAT
    assert manifest["extractionPolicyVersion"] == (
        RUNNER_ACTIVATION_RELEASE_ARCHIVE_EXTRACTION_POLICY
    )
    assert manifest["artifactArchiveSha256"] == ARCHIVE_SHA256
    assert manifest["artifactArchiveSizeBytes"] == ARCHIVE_SIZE_BYTES
    assert manifest["uncompressedArchiveSizeBytes"] == (UNCOMPRESSED_ARCHIVE_SIZE_BYTES)
    assert manifest["bootstrapManifest"] == BOOTSTRAP_MANIFEST
    assert manifest["bootstrapManifestContentSha256"] == (BOOTSTRAP_MANIFEST_SHA256)
    assert manifest["bootstrapManifestPath"] == (
        RUNNER_ACTIVATION_RELEASE_ARTIFACT_MANIFEST_PATH
    )
    assert manifest["bootstrapManifestFingerprint"] == (BOOTSTRAP_MANIFEST_FINGERPRINT)
    assert manifest["memberCount"] == 7
    assert manifest["totalMemberMetadataBytes"] > 0
    assert manifest["totalPayloadBytes"] == 20 + len(BOOTSTRAP_MANIFEST_BYTES)
    assert manifest["totalTreeFileBytes"] == 28 + len(BOOTSTRAP_MANIFEST_BYTES)
    assert all(set(member) == MEMBER_FIELDS for member in manifest["members"])


def test_archive_manifest_validation_is_deeply_detached() -> None:
    manifest = _manifest()
    normalized = require_runner_activation_release_archive_manifest(manifest)

    assert normalized == manifest
    assert normalized is not manifest
    assert normalized["members"] is not manifest["members"]
    assert normalized["members"][0] is not manifest["members"][0]
    assert normalized["bootstrapManifest"] is not manifest["bootstrapManifest"]
    normalized["members"][0]["path"] = "changed"
    normalized["bootstrapManifest"]["runtime"]["python"] = "changed"
    assert manifest["members"][0]["path"] == "bin"
    assert manifest["bootstrapManifest"]["runtime"]["python"] == ("runtime/bin/python")


@pytest.mark.parametrize("extra", [True, False])
def test_archive_manifest_requires_exact_top_level_fields(extra: bool) -> None:
    manifest = _manifest()
    if extra:
        manifest["unexpected"] = True
    else:
        manifest.pop("archiveFormat")

    with pytest.raises(ValueError, match="fields must match exactly"):
        require_runner_activation_release_archive_manifest(manifest)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schemaVersion", "h2ometa.runner-installed-release-archive-manifest.v2"),
        ("service", "another-service"),
        ("archiveFormat", "zip"),
        ("extractionPolicyVersion", "unsafe"),
        ("artifactArchiveSha256", "a" * 64),
        ("artifactArchiveSizeBytes", True),
        ("artifactArchiveSizeBytes", 0),
        ("uncompressedArchiveSizeBytes", True),
        ("uncompressedArchiveSizeBytes", 1_025),
        ("bootstrapManifest", {}),
        ("bootstrapManifestContentSha256", "sha256:" + "0" * 64),
        ("bootstrapManifestFingerprint", "e" * 64),
        ("bootstrapManifestPath", "another.json"),
    ],
)
def test_archive_manifest_rejects_identity_or_policy_drift(
    field: str,
    value: object,
) -> None:
    manifest = _manifest()
    manifest[field] = value

    with pytest.raises(ValueError):
        require_runner_activation_release_archive_manifest(manifest)


@pytest.mark.parametrize("extra", [True, False])
def test_archive_manifest_requires_exact_member_fields(extra: bool) -> None:
    manifest = _manifest()
    member = manifest["members"][1]
    if extra:
        member["unexpected"] = True
    else:
        member.pop("mode")

    with pytest.raises(ValueError, match="fields must match exactly"):
        require_runner_activation_release_archive_manifest(manifest)


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/absolute",
        "a\\b",
        ".",
        "..",
        "a/./b",
        "a/../b",
        "a//b",
        "a/",
        " leading",
        "trailing ",
        "é",
        "control\x1f",
        ".h2ometa-marker",
        "a/" + "b" * 256,
        "a/" + "/".join("b" * 255 for _ in range(17)),
    ],
)
def test_archive_manifest_rejects_noncanonical_member_paths(path: str) -> None:
    members = _members()
    members[0]["path"] = path

    with pytest.raises(ValueError):
        _manifest(members=members)


def test_archive_manifest_requires_strict_order_unique_names_and_parents() -> None:
    duplicate = _members()
    duplicate[1]["path"] = "bin"
    with pytest.raises(ValueError, match="strictly ordered"):
        _manifest(members=duplicate)

    reversed_members = list(reversed(_members()))
    with pytest.raises(ValueError, match="strictly ordered|parent is invalid"):
        _manifest(members=reversed_members)

    missing_parent = _members()
    missing_parent.pop(0)
    with pytest.raises(ValueError, match="parent is invalid"):
        _manifest(members=missing_parent)

    file_ancestor = _members()
    file_ancestor[0] = {
        "contentSha256": DATA_SHA256,
        "linkTarget": "",
        "mode": "0644",
        "path": "bin",
        "sizeBytes": 1,
        "type": "file",
    }
    with pytest.raises(ValueError, match="parent is invalid"):
        _manifest(members=file_ancestor)


@pytest.mark.parametrize(
    ("index", "field", "value", "message"),
    [
        (0, "mode", "0775", "directory metadata"),
        (0, "sizeBytes", 1, "directory metadata"),
        (1, "mode", "04755", "file metadata"),
        (1, "contentSha256", "", "contentSha256"),
        (1, "linkTarget", "bin/other", "file metadata"),
        (5, "sizeBytes", 8, "hardlink binding"),
        (5, "contentSha256", DATA_SHA256, "hardlink binding"),
        (6, "mode", "0755", "symlink metadata"),
        (6, "sizeBytes", 10, "symlink metadata"),
        (6, "contentSha256", DATA_SHA256, "symlink metadata"),
    ],
)
def test_archive_manifest_rejects_nonpolicy_member_metadata(
    index: int,
    field: str,
    value: object,
    message: str,
) -> None:
    members = _members()
    members[index][field] = value

    with pytest.raises(ValueError, match=message):
        _manifest(members=members)


@pytest.mark.parametrize("member_type", ["fifo", "block", "char", "socket", "sparse"])
def test_archive_manifest_rejects_special_or_unknown_member_types(
    member_type: str,
) -> None:
    members = _members()
    members[1]["type"] = member_type

    with pytest.raises(ValueError, match="member type"):
        _manifest(members=members)


def test_archive_manifest_requires_at_least_one_regular_payload() -> None:
    members = [
        {
            "contentSha256": "",
            "linkTarget": "",
            "mode": "0755",
            "path": "empty",
            "sizeBytes": 0,
            "type": "directory",
        }
    ]

    with pytest.raises(ValueError, match="no regular file payload"):
        _manifest(members=members)


@pytest.mark.parametrize("field", ["missing", "mode", "empty", "content", "size"])
def test_archive_manifest_binds_a_fixed_bootstrap_manifest_member(field: str) -> None:
    members = _members()
    bootstrap = members[2]
    if field == "missing":
        members.pop(2)
    elif field == "mode":
        bootstrap["mode"] = "0755"
    elif field == "empty":
        bootstrap["sizeBytes"] = 0
    elif field == "content":
        bootstrap["contentSha256"] = "sha256:" + "0" * 64
    else:
        bootstrap["sizeBytes"] += 1

    with pytest.raises(ValueError, match="bootstrap manifest member"):
        _manifest(members=members)


@pytest.mark.parametrize(
    ("target", "message"),
    [
        ("missing", "hardlink binding"),
        ("python-link", "hardlink binding"),
        ("lib/data-copy", "hardlink binding"),
        ("/lib/data", "member.linkTarget"),
        ("lib/../data", "member.linkTarget"),
    ],
)
def test_archive_manifest_rejects_invalid_hardlink_bindings(
    target: str,
    message: str,
) -> None:
    members = _members()
    members[5]["linkTarget"] = target

    with pytest.raises(ValueError, match=message):
        _manifest(members=members)


def test_archive_manifest_accepts_hardlinks_to_later_canonical_regular_files() -> None:
    members = _members()
    members[5]["linkTarget"] = "z-file"
    members.append(
        {
            "contentSha256": DATA_SHA256,
            "linkTarget": "",
            "mode": "0644",
            "path": "z-file",
            "sizeBytes": 8,
            "type": "file",
        }
    )

    manifest = _manifest(members=members)

    assert manifest["members"][5]["linkTarget"] == "z-file"


@pytest.mark.parametrize(
    "target",
    ["/outside", "..", "../outside", "missing", "bin/python/child", "é"],
)
def test_archive_manifest_rejects_escaping_or_dangling_symlinks(
    target: str,
) -> None:
    members = _members()
    members[6]["linkTarget"] = target

    with pytest.raises(ValueError, match="symlink|member graph|linkTarget"):
        _manifest(members=members)


def test_archive_manifest_accepts_a_relative_symlink_with_dotdot_inside_root() -> None:
    members = _members()
    members.insert(
        6,
        {
            "contentSha256": "",
            "linkTarget": "../bin/python",
            "mode": "0777",
            "path": "lib/python-link",
            "sizeBytes": 0,
            "type": "symlink",
        },
    )

    manifest = _manifest(members=members)

    assert manifest["members"][6]["linkTarget"] == "../bin/python"


def test_archive_manifest_rejects_symlink_cycles_and_excessive_depth() -> None:
    cycle = [
        {
            "contentSha256": BOOTSTRAP_MANIFEST_SHA256,
            "linkTarget": "",
            "mode": "0644",
            "path": RUNNER_ACTIVATION_RELEASE_ARTIFACT_MANIFEST_PATH,
            "sizeBytes": len(BOOTSTRAP_MANIFEST_BYTES),
            "type": "file",
        },
        {
            "contentSha256": "",
            "linkTarget": "link-b",
            "mode": "0777",
            "path": "link-a",
            "sizeBytes": 0,
            "type": "symlink",
        },
        {
            "contentSha256": "",
            "linkTarget": "link-a",
            "mode": "0777",
            "path": "link-b",
            "sizeBytes": 0,
            "type": "symlink",
        },
        {
            "contentSha256": DATA_SHA256,
            "linkTarget": "",
            "mode": "0644",
            "path": "payload",
            "sizeBytes": 1,
            "type": "file",
        },
    ]
    with pytest.raises(ValueError, match="member graph"):
        _manifest(members=cycle)

    deep: list[dict[str, object]] = [
        {
            "contentSha256": BOOTSTRAP_MANIFEST_SHA256,
            "linkTarget": "",
            "mode": "0644",
            "path": RUNNER_ACTIVATION_RELEASE_ARTIFACT_MANIFEST_PATH,
            "sizeBytes": len(BOOTSTRAP_MANIFEST_BYTES),
            "type": "file",
        },
        {
            "contentSha256": "",
            "linkTarget": "",
            "mode": "0755",
            "path": "links",
            "sizeBytes": 0,
            "type": "directory",
        },
    ]
    for index in range(41):
        deep.append(
            {
                "contentSha256": "",
                "linkTarget": f"{index + 1:02d}" if index < 40 else "../target",
                "mode": "0777",
                "path": f"links/{index:02d}",
                "sizeBytes": 0,
                "type": "symlink",
            }
        )
    deep.append(
        {
            "contentSha256": DATA_SHA256,
            "linkTarget": "",
            "mode": "0644",
            "path": "target",
            "sizeBytes": 1,
            "type": "file",
        }
    )
    with pytest.raises(ValueError, match="member graph"):
        _manifest(members=deep)


def test_archive_manifest_enforces_all_fixed_resource_budgets(monkeypatch) -> None:
    with pytest.raises(ValueError, match="archive size exceeds policy"):
        _manifest(
            artifact_archive_size_bytes=(
                archive_contract.RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_SIZE_BYTES + 1
            )
        )

    with pytest.raises(ValueError, match="uncompressed size exceeds policy"):
        _manifest(
            uncompressed_archive_size_bytes=(
                archive_contract.RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_UNCOMPRESSED_SIZE_BYTES
                + 512
            )
        )

    members = _members()
    members[1]["sizeBytes"] = (
        archive_contract.RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_MEMBER_BYTES + 1
    )
    with pytest.raises(ValueError, match="member size exceeds policy"):
        _manifest(members=members)

    monkeypatch.setattr(
        archive_graph_contract,
        "RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_MEMBERS",
        5,
    )
    with pytest.raises(ValueError, match="member count exceeds policy"):
        _manifest()


def test_archive_manifest_enforces_total_and_expansion_budgets(monkeypatch) -> None:
    monkeypatch.setattr(
        archive_graph_contract,
        "RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_TOTAL_BYTES",
        147,
    )
    with pytest.raises(ValueError, match="total file size exceeds policy"):
        _manifest()

    monkeypatch.setattr(
        archive_graph_contract,
        "RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_TOTAL_BYTES",
        10 * 1024**2,
    )
    monkeypatch.setattr(
        archive_contract,
        "RUNNER_ACTIVATION_RELEASE_ARCHIVE_COMPRESSION_RATIO_FLOOR_BYTES",
        0,
    )
    monkeypatch.setattr(
        archive_contract,
        "RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_COMPRESSION_RATIO",
        1,
    )
    with pytest.raises(ValueError, match="expansion ratio exceeds policy"):
        _manifest(
            artifact_archive_size_bytes=512,
            uncompressed_archive_size_bytes=1_024,
        )


def test_archive_manifest_caps_metadata_and_full_canonical_record(monkeypatch) -> None:
    monkeypatch.setattr(
        archive_graph_contract,
        "RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_MEMBER_METADATA_BYTES",
        1,
    )
    with pytest.raises(ValueError, match="member metadata size exceeds policy"):
        _manifest()

    monkeypatch.setattr(
        archive_graph_contract,
        "RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_MEMBER_METADATA_BYTES",
        32 * 1024**2,
    )
    manifest = _manifest()
    monkeypatch.setattr(
        archive_contract,
        "RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_MANIFEST_BYTES",
        1,
    )
    with pytest.raises(ValueError, match="manifest size exceeds policy"):
        runner_activation_release_archive_manifest_canonical_json(manifest)


def test_archive_manifest_ratio_counts_header_and_pax_heavy_tar_stream(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        archive_contract,
        "RUNNER_ACTIVATION_RELEASE_ARCHIVE_COMPRESSION_RATIO_FLOOR_BYTES",
        0,
    )
    monkeypatch.setattr(
        archive_contract,
        "RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_COMPRESSION_RATIO",
        2,
    )

    with pytest.raises(ValueError, match="expansion ratio exceeds policy"):
        _manifest(
            artifact_archive_size_bytes=512,
            uncompressed_archive_size_bytes=50 * 512,
        )


def test_archive_manifest_rejects_stream_smaller_than_member_headers_and_padding() -> (
    None
):
    with pytest.raises(ValueError, match="stream binding"):
        _manifest(uncompressed_archive_size_bytes=5 * 512)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("memberCount", 8),
        ("memberCount", True),
        ("totalPayloadBytes", 149),
        ("totalTreeFileBytes", 157),
    ],
)
def test_archive_manifest_rejects_summary_drift(
    field: str,
    value: object,
) -> None:
    manifest = _manifest()
    manifest[field] = value

    with pytest.raises(ValueError, match="summary binding|is invalid"):
        require_runner_activation_release_archive_manifest(manifest)


def test_archive_manifest_rejects_member_metadata_summary_drift() -> None:
    manifest = _manifest()
    manifest["totalMemberMetadataBytes"] += 1

    with pytest.raises(ValueError, match="summary binding"):
        require_runner_activation_release_archive_manifest(manifest)


def test_archive_manifest_canonicalization_and_fingerprint_are_stable() -> None:
    manifest = _manifest()
    copied = deepcopy(manifest)

    assert runner_activation_release_archive_manifest_canonical_json(copied) == (
        runner_activation_release_archive_manifest_canonical_json(manifest)
    )
    fingerprint = runner_activation_release_archive_manifest_fingerprint(manifest)
    assert fingerprint == runner_activation_release_archive_manifest_fingerprint(copied)
    assert fingerprint.startswith("sha256:")
    assert fingerprint != ARCHIVE_SHA256


def test_archive_manifest_validation_uses_the_caller_error_type() -> None:
    manifest = _manifest()
    manifest["archiveFormat"] = "zip"

    with pytest.raises(ArchiveContractError, match="archiveFormat"):
        require_runner_activation_release_archive_manifest(
            manifest,
            make_error=ArchiveContractError,
        )
