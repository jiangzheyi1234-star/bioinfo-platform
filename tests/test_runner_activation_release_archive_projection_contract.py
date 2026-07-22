from __future__ import annotations

import hashlib
import json

import pytest

from core.contracts.runner_activation_release_archive import (
    RUNNER_ACTIVATION_RELEASE_ARTIFACT_MANIFEST_PATH,
    build_runner_activation_release_archive_manifest,
    project_runner_activation_release_archive_materialization_entries,
    runner_activation_release_archive_projected_tree_content_fingerprint,
)
from core.contracts.runner_activation_release_tree import (
    build_runner_activation_release_tree_manifest,
    runner_activation_release_tree_content_fingerprint,
)
from core.contracts.runner_activation_target import RUNNER_ACTIVATION_SERVICE
from core.contracts.runner_protocol import (
    build_runner_protocol_descriptor,
    runner_protocol_descriptor_fingerprint,
)


ARCHIVE_SHA256 = "sha256:" + "a" * 64
EXECUTABLE_SHA256 = "sha256:" + "b" * 64
DATA_SHA256 = "sha256:" + "c" * 64
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
PROJECTED_ENTRY_FIELDS = {
    "contentSha256",
    "linkTarget",
    "mode",
    "path",
    "payloadSourcePath",
    "sizeBytes",
    "type",
}


class ArchiveProjectionError(RuntimeError):
    pass


def _members() -> list[dict[str, object]]:
    return [
        _member(path="bin", member_type="directory", mode="0755"),
        _member(
            path="bin/python",
            member_type="file",
            mode="0755",
            size_bytes=12,
            content_sha256=EXECUTABLE_SHA256,
        ),
        _member(
            path=RUNNER_ACTIVATION_RELEASE_ARTIFACT_MANIFEST_PATH,
            member_type="file",
            mode="0644",
            size_bytes=len(BOOTSTRAP_MANIFEST_BYTES),
            content_sha256=BOOTSTRAP_MANIFEST_SHA256,
        ),
        _member(path="lib", member_type="directory", mode="0755"),
        _member(
            path="lib/data",
            member_type="file",
            mode="0644",
            size_bytes=8,
            content_sha256=DATA_SHA256,
        ),
        _member(
            path="lib/data-copy",
            member_type="hardlink",
            mode="0644",
            link_target="lib/data",
        ),
        _member(
            path="python-link",
            member_type="symlink",
            mode="0777",
            link_target="bin/python",
        ),
    ]


def _member(
    *,
    path: str,
    member_type: str,
    mode: str,
    size_bytes: int = 0,
    content_sha256: str = "",
    link_target: str = "",
) -> dict[str, object]:
    return {
        "contentSha256": content_sha256,
        "linkTarget": link_target,
        "mode": mode,
        "path": path,
        "sizeBytes": size_bytes,
        "type": member_type,
    }


def _manifest(
    members: object | None = None,
) -> dict[str, object]:
    return build_runner_activation_release_archive_manifest(
        artifact_archive_sha256=ARCHIVE_SHA256,
        artifact_archive_size_bytes=4_096,
        bootstrap_manifest_bytes=BOOTSTRAP_MANIFEST_BYTES,
        uncompressed_archive_size_bytes=10_240,
        members=_members() if members is None else members,
    )


def _projection_rows(
    projected: list[dict[str, object]],
) -> list[tuple[object, ...]]:
    return [
        (
            entry["path"],
            entry["type"],
            entry["mode"],
            entry["sizeBytes"],
            entry["contentSha256"],
            entry["linkTarget"],
            entry["payloadSourcePath"],
        )
        for entry in projected
    ]


def test_archive_materialization_projection_is_exact_and_deeply_detached() -> None:
    manifest = _manifest()

    projected = project_runner_activation_release_archive_materialization_entries(
        manifest
    )

    assert _projection_rows(projected) == [
        ("bin", "directory", "0555", 0, "", "", ""),
        (
            "bin/python",
            "file",
            "0555",
            12,
            EXECUTABLE_SHA256,
            "",
            "bin/python",
        ),
        (
            RUNNER_ACTIVATION_RELEASE_ARTIFACT_MANIFEST_PATH,
            "file",
            "0444",
            len(BOOTSTRAP_MANIFEST_BYTES),
            BOOTSTRAP_MANIFEST_SHA256,
            "",
            RUNNER_ACTIVATION_RELEASE_ARTIFACT_MANIFEST_PATH,
        ),
        ("lib", "directory", "0555", 0, "", "", ""),
        ("lib/data", "file", "0444", 8, DATA_SHA256, "", "lib/data"),
        (
            "lib/data-copy",
            "hardlink",
            "0444",
            8,
            DATA_SHA256,
            "lib/data",
            "",
        ),
        ("python-link", "symlink", "0777", 10, "", "bin/python", ""),
    ]
    assert all(set(entry) == PROJECTED_ENTRY_FIELDS for entry in projected)
    projected[0]["path"] = "changed"
    assert manifest["members"][0]["path"] == "bin"
    assert (
        project_runner_activation_release_archive_materialization_entries(manifest)[0][
            "path"
        ]
        == "bin"
    )


def test_archive_projection_routes_every_raw_file_payload_once() -> None:
    manifest = _manifest()

    projected = project_runner_activation_release_archive_materialization_entries(
        manifest
    )

    raw_files = {
        member["path"] for member in manifest["members"] if member["type"] == "file"
    }
    routed = [
        entry["payloadSourcePath"] for entry in projected if entry["payloadSourcePath"]
    ]
    assert set(routed) == raw_files
    assert len(routed) == len(set(routed))
    assert all(
        bool(entry["payloadSourcePath"]) == (entry["type"] == "file")
        for entry in projected
    )


def test_archive_projection_promotes_hardlink_before_raw_payload_member() -> None:
    members = _members()
    members[5]["linkTarget"] = "z-file"
    members.append(
        _member(
            path="z-file",
            member_type="file",
            mode="0644",
            size_bytes=8,
            content_sha256=DATA_SHA256,
        )
    )

    projected = project_runner_activation_release_archive_materialization_entries(
        _manifest(members)
    )
    by_path = {entry["path"]: entry for entry in projected}

    assert by_path["lib/data-copy"] == {
        "contentSha256": DATA_SHA256,
        "linkTarget": "",
        "mode": "0444",
        "path": "lib/data-copy",
        "payloadSourcePath": "z-file",
        "sizeBytes": 8,
        "type": "file",
    }
    assert by_path["z-file"] == {
        "contentSha256": DATA_SHA256,
        "linkTarget": "lib/data-copy",
        "mode": "0444",
        "path": "z-file",
        "payloadSourcePath": "",
        "sizeBytes": 8,
        "type": "hardlink",
    }


def test_archive_projected_tree_fingerprint_reuses_tree_identity_domain() -> None:
    manifest = _manifest()
    projected = project_runner_activation_release_archive_materialization_entries(
        manifest
    )
    tree_entries = [
        {key: value for key, value in entry.items() if key != "payloadSourcePath"}
        for entry in projected
    ]
    tree_manifest = build_runner_activation_release_tree_manifest(tree_entries)

    assert runner_activation_release_archive_projected_tree_content_fingerprint(
        manifest
    ) == runner_activation_release_tree_content_fingerprint(tree_manifest)


def test_archive_materialization_projection_uses_the_caller_error_type() -> None:
    manifest = _manifest()
    manifest["archiveFormat"] = "zip"

    with pytest.raises(ArchiveProjectionError, match="archiveFormat"):
        project_runner_activation_release_archive_materialization_entries(
            manifest,
            make_error=ArchiveProjectionError,
        )
