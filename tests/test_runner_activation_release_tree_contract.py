from __future__ import annotations

import hashlib
import json

import pytest

import core.contracts.runner_activation_release_tree as release_tree_contract
from core.contracts.runner_activation_release_tree import (
    RUNNER_ACTIVATION_RELEASE_TREE_MANIFEST_SCHEMA,
    RUNNER_ACTIVATION_RELEASE_TREE_MATERIALIZATION_POLICY,
    RUNNER_ACTIVATION_RELEASE_TREE_ROOT_MODE,
    RUNNER_ACTIVATION_RELEASE_TREE_SCHEMA,
    build_runner_activation_release_tree_manifest,
    require_runner_activation_release_tree_manifest,
    runner_activation_release_tree_content_fingerprint,
    runner_activation_release_tree_manifest_canonical_json,
    runner_activation_release_tree_manifest_fingerprint,
)


FILE_A_SHA256 = "sha256:" + "a" * 64
FILE_B_SHA256 = "sha256:" + "b" * 64
FILE_C_SHA256 = "sha256:" + "c" * 64
ARCHIVE_SHA256 = "sha256:" + "f" * 64
ENTRY_FIELDS = {
    "contentSha256",
    "linkTarget",
    "mode",
    "path",
    "sizeBytes",
    "type",
}
MANIFEST_FIELDS = {
    "entries",
    "materializationPolicyVersion",
    "rootMode",
    "schemaVersion",
    "service",
    "treeContentFingerprint",
}


class ReleaseTreeContractError(RuntimeError):
    pass


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _domain_fingerprint(domain: str, payload: object) -> str:
    digest = hashlib.sha256(
        domain.encode("ascii")
        + b"\x00"
        + _canonical_json(payload).encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"


def _directory(path: str) -> dict[str, object]:
    return {
        "contentSha256": "",
        "linkTarget": "",
        "mode": "0555",
        "path": path,
        "sizeBytes": 0,
        "type": "directory",
    }


def _file(
    path: str,
    *,
    mode: str = "0444",
    size_bytes: int = 5,
    content_sha256: str = FILE_A_SHA256,
) -> dict[str, object]:
    return {
        "contentSha256": content_sha256,
        "linkTarget": "",
        "mode": mode,
        "path": path,
        "sizeBytes": size_bytes,
        "type": "file",
    }


def _symlink(path: str, target: str) -> dict[str, object]:
    return {
        "contentSha256": "",
        "linkTarget": target,
        "mode": "0777",
        "path": path,
        "sizeBytes": len(target.encode("ascii")),
        "type": "symlink",
    }


def _hardlink(
    path: str,
    *,
    target: str,
    primary: dict[str, object],
) -> dict[str, object]:
    return {
        "contentSha256": primary["contentSha256"],
        "linkTarget": target,
        "mode": primary["mode"],
        "path": path,
        "sizeBytes": primary["sizeBytes"],
        "type": "hardlink",
    }


def _golden_entries() -> list[dict[str, object]]:
    data_file = _file(
        "share/a-data.txt",
        size_bytes=4,
        content_sha256=FILE_B_SHA256,
    )
    return [
        _directory("bin"),
        _file(
            "bin/h2ometa-runner",
            mode="0555",
            size_bytes=7,
            content_sha256=FILE_A_SHA256,
        ),
        _symlink("current", "bin/h2ometa-runner"),
        _directory("share"),
        data_file,
        _hardlink(
            "share/z-data.txt",
            target="share/a-data.txt",
            primary=data_file,
        ),
    ]


def test_release_tree_manifest_is_exact_canonical_and_domain_separated() -> None:
    entries = _golden_entries()
    manifest = build_runner_activation_release_tree_manifest(entries)
    content_payload = {
        "entries": entries,
        "rootMode": "0555",
    }
    expected_content_fingerprint = _domain_fingerprint(
        RUNNER_ACTIVATION_RELEASE_TREE_SCHEMA,
        content_payload,
    )

    assert RUNNER_ACTIVATION_RELEASE_TREE_SCHEMA == (
        "h2ometa.runner-installed-release-tree.v1"
    )
    assert RUNNER_ACTIVATION_RELEASE_TREE_MANIFEST_SCHEMA == (
        "h2ometa.runner-installed-release-tree-manifest.v1"
    )
    assert RUNNER_ACTIVATION_RELEASE_TREE_MATERIALIZATION_POLICY == (
        "h2ometa.runner-installed-release-materialization.v1"
    )
    assert RUNNER_ACTIVATION_RELEASE_TREE_ROOT_MODE == "0555"
    assert manifest == {
        "entries": entries,
        "materializationPolicyVersion": (
            RUNNER_ACTIVATION_RELEASE_TREE_MATERIALIZATION_POLICY
        ),
        "rootMode": "0555",
        "schemaVersion": RUNNER_ACTIVATION_RELEASE_TREE_MANIFEST_SCHEMA,
        "service": "h2ometa-remote",
        "treeContentFingerprint": expected_content_fingerprint,
    }
    assert set(manifest) == MANIFEST_FIELDS
    assert all(set(entry) == ENTRY_FIELDS for entry in manifest["entries"])

    canonical = runner_activation_release_tree_manifest_canonical_json(manifest)
    assert canonical == _canonical_json(manifest)
    assert runner_activation_release_tree_manifest_canonical_json(
        dict(reversed(list(manifest.items())))
    ) == canonical
    assert runner_activation_release_tree_content_fingerprint(manifest) == (
        expected_content_fingerprint
    )
    expected_manifest_fingerprint = _domain_fingerprint(
        RUNNER_ACTIVATION_RELEASE_TREE_MANIFEST_SCHEMA,
        manifest,
    )
    assert runner_activation_release_tree_manifest_fingerprint(manifest) == (
        expected_manifest_fingerprint
    )
    assert expected_content_fingerprint != expected_manifest_fingerprint


def test_manifest_builder_and_validator_return_deeply_detached_copies() -> None:
    entries = _golden_entries()
    manifest = build_runner_activation_release_tree_manifest(entries)

    assert manifest["entries"] is not entries
    assert manifest["entries"][0] is not entries[0]
    entries[0]["mode"] = "0000"
    assert manifest["entries"][0]["mode"] == "0555"

    normalized = require_runner_activation_release_tree_manifest(manifest)
    assert normalized == manifest
    assert normalized is not manifest
    assert normalized["entries"] is not manifest["entries"]
    assert normalized["entries"][0] is not manifest["entries"][0]
    normalized["entries"][0]["path"] = "changed"
    assert manifest["entries"][0]["path"] == "bin"


def test_manifest_validation_uses_caller_supplied_error_type() -> None:
    manifest = build_runner_activation_release_tree_manifest(_golden_entries())
    invalid = {**manifest, "archiveSha256": ARCHIVE_SHA256}

    with pytest.raises(ReleaseTreeContractError, match="fields must match exactly"):
        require_runner_activation_release_tree_manifest(
            invalid,
            make_error=ReleaseTreeContractError,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("schemaVersion", "h2ometa.runner-installed-release-tree.v1", "schemaVersion"),
        ("service", "another-service", "service"),
        ("materializationPolicyVersion", "legacy-policy.v1", "materializationPolicyVersion"),
        ("rootMode", "0755", "rootMode"),
        ("treeContentFingerprint", FILE_C_SHA256, "content binding"),
        ("treeContentFingerprint", "sha256:bad", "treeContentFingerprint"),
    ],
)
def test_manifest_rejects_top_level_identity_drift(
    field: str,
    value: object,
    message: str,
) -> None:
    manifest = build_runner_activation_release_tree_manifest(_golden_entries())
    manifest[field] = value

    with pytest.raises(ValueError, match=message):
        require_runner_activation_release_tree_manifest(manifest)


def test_manifest_rejects_entries_changed_after_content_identity_was_bound() -> None:
    manifest = build_runner_activation_release_tree_manifest([_file("runner")])
    manifest["entries"][0]["sizeBytes"] = 6

    with pytest.raises(ValueError, match="content binding"):
        require_runner_activation_release_tree_manifest(manifest)


@pytest.mark.parametrize(
    "extra_field",
    [
        "archiveSha256",
        "releasePath",
        "installationFingerprint",
        "provenance",
    ],
)
def test_manifest_rejects_archive_path_installation_and_provenance_fields(
    extra_field: str,
) -> None:
    manifest = build_runner_activation_release_tree_manifest(_golden_entries())
    manifest[extra_field] = "caller-controlled"

    with pytest.raises(ValueError, match="fields must match exactly"):
        require_runner_activation_release_tree_manifest(manifest)


@pytest.mark.parametrize("removed_field", sorted(ENTRY_FIELDS))
def test_entry_fields_are_exact_and_required(removed_field: str) -> None:
    entry = _file("runner")
    del entry[removed_field]

    with pytest.raises(ValueError, match="fields must match exactly"):
        build_runner_activation_release_tree_manifest([entry])


@pytest.mark.parametrize(
    "extra_field",
    ["archivePath", "sourcePath", "installationFingerprint", "provenance"],
)
def test_entry_rejects_caller_supplied_source_identity_fields(
    extra_field: str,
) -> None:
    entry = _file("runner")
    entry[extra_field] = "caller-controlled"

    with pytest.raises(ValueError, match="fields must match exactly"):
        build_runner_activation_release_tree_manifest([entry])


def test_entries_must_be_nonempty_strictly_sorted_unique_and_parented() -> None:
    with pytest.raises(ValueError, match="entry count"):
        build_runner_activation_release_tree_manifest([])
    with pytest.raises(ValueError, match="entries are invalid"):
        build_runner_activation_release_tree_manifest({"path": "runner"})
    with pytest.raises(ValueError, match="strictly ordered"):
        build_runner_activation_release_tree_manifest(
            [_file("z-runner"), _file("a-runner")]
        )
    with pytest.raises(ValueError, match="strictly ordered"):
        build_runner_activation_release_tree_manifest(
            [_file("runner"), _file("runner")]
        )
    with pytest.raises(ValueError, match="parent"):
        build_runner_activation_release_tree_manifest([_file("bin/runner")])
    with pytest.raises(ValueError, match="parent"):
        build_runner_activation_release_tree_manifest(
            [_file("bin"), _file("bin/runner")]
        )


TOO_LONG_PATH = "/".join(["a" * 255] * 17)


@pytest.mark.parametrize(
    "path",
    [
        None,
        "",
        "/runner",
        "bin\\runner",
        ".",
        "..",
        "./runner",
        "bin/./runner",
        "bin/../runner",
        "bin//runner",
        "bin/runner/",
        "bin/\x1frunner",
        "bin/\x7frunner",
        "bin/runnér",
        " runner",
        "runner ",
        "bin/ runner",
        "bin/runner ",
        ".h2ometa-metadata",
        "bin/.h2ometa-private",
        "a" * 256,
        TOO_LONG_PATH,
    ],
)
def test_entry_paths_follow_closed_portable_ascii_policy(path: object) -> None:
    entry = _file("runner")
    entry["path"] = path

    with pytest.raises(ValueError, match="entry.path"):
        build_runner_activation_release_tree_manifest([entry])


def test_entry_path_accepts_an_exact_255_byte_ascii_component() -> None:
    path = "a" * 255

    manifest = build_runner_activation_release_tree_manifest([_file(path)])

    assert manifest["entries"][0]["path"] == path


def test_entry_count_limit_is_enforced_without_a_large_fixture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(release_tree_contract, "_MAX_ENTRIES", 2)

    assert len(
        build_runner_activation_release_tree_manifest(
            [_file("a"), _file("b")]
        )["entries"]
    ) == 2
    with pytest.raises(ValueError, match="entry count"):
        build_runner_activation_release_tree_manifest(
            [_file("a"), _file("b"), _file("c")]
        )


def test_total_file_size_limit_counts_files_and_hardlink_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(release_tree_contract, "_MAX_TOTAL_FILE_BYTES", 5)
    first = _file("a", size_bytes=3)

    assert build_runner_activation_release_tree_manifest(
        [first, _file("b", size_bytes=2, content_sha256=FILE_B_SHA256)]
    )
    with pytest.raises(ValueError, match="total file size"):
        build_runner_activation_release_tree_manifest(
            [first, _file("b", size_bytes=3, content_sha256=FILE_B_SHA256)]
        )
    with pytest.raises(ValueError, match="total file size"):
        build_runner_activation_release_tree_manifest(
            [first, _hardlink("z", target="a", primary=first)]
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("mode", "0755"),
        ("mode", 0o555),
        ("sizeBytes", 1),
        ("contentSha256", FILE_A_SHA256),
        ("linkTarget", "other"),
    ],
)
def test_directory_metadata_matrix_is_closed(field: str, value: object) -> None:
    entry = _directory("bin")
    entry[field] = value

    with pytest.raises(ValueError, match="directory metadata"):
        build_runner_activation_release_tree_manifest([entry])


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("mode", "0644", "file metadata"),
        ("mode", "0777", "file metadata"),
        ("sizeBytes", -1, "sizeBytes"),
        ("sizeBytes", True, "sizeBytes"),
        ("sizeBytes", 1.5, "sizeBytes"),
        ("contentSha256", "", "contentSha256"),
        ("contentSha256", "sha256:" + "A" * 64, "contentSha256"),
        ("linkTarget", "other", "file metadata"),
    ],
)
def test_file_metadata_matrix_is_closed(
    field: str,
    value: object,
    message: str,
) -> None:
    entry = _file("runner")
    entry[field] = value

    with pytest.raises(ValueError, match=message):
        build_runner_activation_release_tree_manifest([entry])


def test_read_only_and_executable_file_modes_are_both_canonical() -> None:
    manifest = build_runner_activation_release_tree_manifest(
        [
            _file("a", mode="0444"),
            _file("b", mode="0555", content_sha256=FILE_B_SHA256),
        ]
    )

    assert [entry["mode"] for entry in manifest["entries"]] == ["0444", "0555"]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("mode", "0555", "symlink metadata"),
        ("sizeBytes", 0, "symlink metadata"),
        ("contentSha256", FILE_A_SHA256, "symlink metadata"),
    ],
)
def test_symlink_metadata_matrix_is_closed(
    field: str,
    value: object,
    message: str,
) -> None:
    entry = _symlink("z", "target")
    entry[field] = value

    with pytest.raises(ValueError, match=message):
        build_runner_activation_release_tree_manifest([_file("target"), entry])


def test_symlink_target_is_exact_relative_ascii_and_size_is_its_byte_length() -> None:
    target = "../bin/runner"
    entries = [
        _directory("bin"),
        _file("bin/runner"),
        _directory("links"),
        _symlink("links/runner", target),
    ]

    manifest = build_runner_activation_release_tree_manifest(entries)

    observed = manifest["entries"][-1]
    assert observed["linkTarget"] == target
    assert observed["sizeBytes"] == len(target.encode("ascii"))


@pytest.mark.parametrize(
    "target",
    [
        "",
        "/target",
        "dir\\target",
        "targét",
        " target",
        "target ",
        "dir//target",
        "target\x1f",
        "a" * 256,
    ],
)
def test_symlink_target_text_policy_is_closed(target: str) -> None:
    entry = _symlink("z", "target")
    entry["linkTarget"] = target
    entry["sizeBytes"] = len(target.encode("utf-8"))

    with pytest.raises(ValueError, match="linkTarget"):
        build_runner_activation_release_tree_manifest([_file("target"), entry])


def test_symlink_rejects_root_escape_and_dangling_targets() -> None:
    with pytest.raises(ValueError, match="escapes root"):
        build_runner_activation_release_tree_manifest(
            [_symlink("z", "../outside")]
        )
    with pytest.raises(ValueError, match="dangling"):
        build_runner_activation_release_tree_manifest([_symlink("z", "missing")])


def test_intermediate_symlink_to_directory_resolves_to_the_final_entry() -> None:
    entries = [
        _symlink("alias", "real"),
        _directory("real"),
        _file("real/runner"),
        _symlink("z", "alias/runner"),
        _symlink("zz", "z"),
    ]

    manifest = build_runner_activation_release_tree_manifest(entries)

    assert manifest["entries"][-2]["linkTarget"] == "alias/runner"
    assert manifest["entries"][-1]["linkTarget"] == "z"
    assert runner_activation_release_tree_content_fingerprint(manifest) == (
        manifest["treeContentFingerprint"]
    )


def test_intermediate_symlink_must_resolve_to_a_directory() -> None:
    file_entries = [
        _symlink("alias", "real"),
        _file("real"),
        _symlink("z", "alias/runner"),
    ]
    with pytest.raises(ValueError, match="traversal"):
        build_runner_activation_release_tree_manifest(file_entries)

    primary = _file("a")
    hardlink = _hardlink("hard", target="a", primary=primary)
    hardlink_entries = [
        primary,
        _symlink("alias", "hard"),
        hardlink,
        _symlink("z", "alias/runner"),
    ]
    with pytest.raises(ValueError, match="traversal"):
        build_runner_activation_release_tree_manifest(hardlink_entries)


def test_multilevel_final_symlink_chain_resolves_normally() -> None:
    entries = [
        _symlink("a", "b"),
        _symlink("b", "c"),
        _symlink("c", "d"),
        _file("d"),
    ]

    manifest = build_runner_activation_release_tree_manifest(entries)

    assert [entry["linkTarget"] for entry in manifest["entries"][:3]] == [
        "b",
        "c",
        "d",
    ]


def test_symlink_chain_depth_limit_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(release_tree_contract, "_MAX_SYMLINK_DEPTH", 2)

    with pytest.raises(ValueError, match="cycle or depth"):
        build_runner_activation_release_tree_manifest(
            [
                _symlink("a", "b"),
                _symlink("b", "c"),
                _symlink("c", "d"),
                _file("d"),
            ]
        )


def test_symlink_graph_rejects_cycles() -> None:
    with pytest.raises(ValueError, match="cycle"):
        build_runner_activation_release_tree_manifest(
            [_symlink("a", "b"), _symlink("b", "a")]
        )

    with pytest.raises(ValueError, match="cycle"):
        build_runner_activation_release_tree_manifest(
            [
                _directory("tree"),
                _directory("tree/child"),
                _symlink("tree/child/back", ".."),
            ]
        )


def test_hardlink_binds_only_an_earlier_primary_file() -> None:
    primary = _file("a", mode="0555", size_bytes=9)
    link = _hardlink("z", target="a", primary=primary)

    manifest = build_runner_activation_release_tree_manifest([primary, link])

    assert manifest["entries"][-1] == link


def test_hardlink_rejects_forward_targets_chains_and_non_file_targets() -> None:
    forward_primary = _file("z")
    with pytest.raises(ValueError, match="hardlink binding"):
        build_runner_activation_release_tree_manifest(
            [
                _hardlink("a", target="z", primary=forward_primary),
                forward_primary,
            ]
        )

    primary = _file("a")
    first_link = _hardlink("b", target="a", primary=primary)
    chained_link = _hardlink("c", target="b", primary=primary)
    with pytest.raises(ValueError, match="hardlink binding"):
        build_runner_activation_release_tree_manifest(
            [primary, first_link, chained_link]
        )

    directory = _directory("a")
    with pytest.raises(ValueError, match="hardlink binding"):
        build_runner_activation_release_tree_manifest(
            [_directory("a"), _hardlink("z", target="a", primary=directory)]
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("mode", "0555"),
        ("sizeBytes", 6),
        ("contentSha256", FILE_B_SHA256),
    ],
)
def test_hardlink_rejects_primary_metadata_drift(field: str, value: object) -> None:
    primary = _file("a")
    link = _hardlink("z", target="a", primary=primary)
    link[field] = value

    with pytest.raises(ValueError, match="hardlink binding"):
        build_runner_activation_release_tree_manifest([primary, link])


def test_unknown_entry_type_is_rejected() -> None:
    entry = _file("runner")
    entry["type"] = "fifo"

    with pytest.raises(ValueError, match="entry type"):
        build_runner_activation_release_tree_manifest([entry])


def test_archive_digest_is_not_either_installed_tree_identity() -> None:
    manifest = build_runner_activation_release_tree_manifest(_golden_entries())
    content_fingerprint = runner_activation_release_tree_content_fingerprint(manifest)
    manifest_fingerprint = runner_activation_release_tree_manifest_fingerprint(manifest)
    canonical = runner_activation_release_tree_manifest_canonical_json(manifest)

    assert ARCHIVE_SHA256 != content_fingerprint
    assert ARCHIVE_SHA256 != manifest_fingerprint
    assert content_fingerprint != manifest_fingerprint
    assert "archive" not in canonical.lower()
    assert "installation" not in canonical.lower()
    assert "provenance" not in canonical.lower()
    assert "prepared" not in canonical.lower()
