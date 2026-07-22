from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest

from core.remote_runner.artifact_models import RemoteRunnerArtifactError
from core.remote_runner.remote_runner_artifact_validation import (
    verify_packaged_sqlite_metadata,
)


SQLITE_VERSION = "3.53.0"
SQLITE_BUILD = "hf4e2dac_0"
SQLITE_MEMBER = f"runtime/conda-meta/libsqlite-{SQLITE_VERSION}-{SQLITE_BUILD}.json"


def _metadata_payload(**overrides: object) -> bytes:
    metadata: dict[str, object] = {
        "name": "libsqlite",
        "version": SQLITE_VERSION,
        "build": SQLITE_BUILD,
        "build_number": 0,
        "subdir": "linux-64",
    }
    metadata.update(overrides)
    return json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _regular_member(name: str, payload: bytes) -> tuple[tarfile.TarInfo, bytes]:
    member = tarfile.TarInfo(name)
    member.size = len(payload)
    return member, payload


def _write_archive(
    path: Path,
    members: list[tuple[tarfile.TarInfo, bytes | None]],
) -> None:
    with tarfile.open(path, "w:gz") as archive:
        marker, marker_payload = _regular_member("payload.txt", b"artifact")
        archive.addfile(marker, io.BytesIO(marker_payload))
        for member, payload in members:
            archive.addfile(
                member,
                io.BytesIO(payload) if payload is not None else None,
            )


def _write_metadata_archive(
    path: Path,
    *,
    payload: bytes | None = None,
    member_name: str = SQLITE_MEMBER,
    member_type: bytes = tarfile.REGTYPE,
    copies: int = 1,
) -> None:
    content = _metadata_payload() if payload is None else payload
    members: list[tuple[tarfile.TarInfo, bytes | None]] = []
    for _ in range(copies):
        member = tarfile.TarInfo(member_name)
        member.type = member_type
        if member.isreg():
            member.size = len(content)
            members.append((member, content))
        else:
            member.linkname = "payload.txt"
            members.append((member, None))
    _write_archive(path, members)


def test_packaged_sqlite_validation_returns_canonical_static_evidence(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "runner.tar.gz"
    _write_metadata_archive(archive)

    evidence = verify_packaged_sqlite_metadata(archive)

    assert evidence == {
        "evidenceKind": "packaged-conda-metadata",
        "minimumVersion": "3.51.3",
        "packageName": "libsqlite",
        "packagedVersion": "3.53.0",
        "build": "hf4e2dac_0",
        "metadataMember": SQLITE_MEMBER,
    }
    assert "loadedVersion" not in evidence
    assert "sqlVersion" not in evidence
    assert "ok" not in evidence


def test_packaged_sqlite_validation_accepts_the_exact_minimum(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "runner.tar.gz"
    version = "3.51.3"
    member = f"runtime/conda-meta/libsqlite-{version}-{SQLITE_BUILD}.json"
    _write_metadata_archive(
        archive,
        payload=_metadata_payload(version=version),
        member_name=member,
    )

    evidence = verify_packaged_sqlite_metadata(archive)

    assert evidence["packagedVersion"] == version


def test_packaged_sqlite_validation_rejects_missing_metadata(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "runner.tar.gz"
    _write_archive(archive, [])

    with pytest.raises(RemoteRunnerArtifactError, match="exactly one"):
        verify_packaged_sqlite_metadata(archive)


def test_packaged_sqlite_validation_ignores_metadata_outside_exact_runtime_path(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "runner.tar.gz"
    misplaced = _regular_member(
        f"conda-meta/libsqlite-{SQLITE_VERSION}-{SQLITE_BUILD}.json",
        _metadata_payload(),
    )
    _write_archive(archive, [misplaced])

    with pytest.raises(RemoteRunnerArtifactError, match="exactly one"):
        verify_packaged_sqlite_metadata(archive)


def test_packaged_sqlite_validation_rejects_duplicate_metadata_members(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "runner.tar.gz"
    _write_metadata_archive(archive, copies=2)

    with pytest.raises(RemoteRunnerArtifactError, match="duplicate or ambiguous"):
        verify_packaged_sqlite_metadata(archive)


@pytest.mark.parametrize(
    "member_type",
    [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.DIRTYPE],
)
def test_packaged_sqlite_validation_rejects_non_regular_metadata(
    tmp_path: Path,
    member_type: bytes,
) -> None:
    archive = tmp_path / "runner.tar.gz"
    _write_metadata_archive(archive, member_type=member_type)

    with pytest.raises(RemoteRunnerArtifactError, match="regular file"):
        verify_packaged_sqlite_metadata(archive)


def test_packaged_sqlite_validation_rejects_empty_metadata(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "runner.tar.gz"
    _write_metadata_archive(archive, payload=b"")

    with pytest.raises(RemoteRunnerArtifactError, match="must not be empty"):
        verify_packaged_sqlite_metadata(archive)


def test_packaged_sqlite_validation_rejects_oversized_metadata(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "runner.tar.gz"
    _write_metadata_archive(archive, payload=b"x" * (64 * 1024 + 1))

    with pytest.raises(RemoteRunnerArtifactError, match="size limit"):
        verify_packaged_sqlite_metadata(archive)


@pytest.mark.parametrize(
    "payload",
    [
        b"{",
        b"\xff",
        b'{"name":"libsqlite","version":NaN,"build":"build_0"}',
    ],
)
def test_packaged_sqlite_validation_rejects_malformed_json(
    tmp_path: Path,
    payload: bytes,
) -> None:
    archive = tmp_path / "runner.tar.gz"
    _write_metadata_archive(archive, payload=payload)

    with pytest.raises(RemoteRunnerArtifactError, match="malformed JSON"):
        verify_packaged_sqlite_metadata(archive)


@pytest.mark.parametrize("payload", [b"[]", b"null", b'"libsqlite"'])
def test_packaged_sqlite_validation_requires_a_json_object(
    tmp_path: Path,
    payload: bytes,
) -> None:
    archive = tmp_path / "runner.tar.gz"
    _write_metadata_archive(archive, payload=payload)

    with pytest.raises(RemoteRunnerArtifactError, match="JSON object"):
        verify_packaged_sqlite_metadata(archive)


@pytest.mark.parametrize(
    "payload",
    [
        b'{"name":"libsqlite","name":"other","version":"3.53.0","build":"build_0"}',
        b'{"name":"libsqlite","version":"3.53.0","build":"build_0","extra":{"x":1,"x":2}}',
    ],
)
def test_packaged_sqlite_validation_rejects_duplicate_json_keys_recursively(
    tmp_path: Path,
    payload: bytes,
) -> None:
    archive = tmp_path / "runner.tar.gz"
    _write_metadata_archive(archive, payload=payload)

    with pytest.raises(RemoteRunnerArtifactError, match="duplicate JSON keys"):
        verify_packaged_sqlite_metadata(archive)


@pytest.mark.parametrize("package_name", [None, True, "sqlite", "LibSQLite"])
def test_packaged_sqlite_validation_requires_exact_package_name(
    tmp_path: Path,
    package_name: object,
) -> None:
    archive = tmp_path / "runner.tar.gz"
    _write_metadata_archive(
        archive,
        payload=_metadata_payload(name=package_name),
    )

    with pytest.raises(RemoteRunnerArtifactError, match="exactly libsqlite"):
        verify_packaged_sqlite_metadata(archive)


@pytest.mark.parametrize(
    "version",
    [
        None,
        True,
        3.53,
        "",
        "3.53",
        "3.53.0.0",
        "03.53.0",
        "3.053.0",
        "3.53.00",
        "3.53.0+build",
        "2147483648.0.0",
    ],
)
def test_packaged_sqlite_validation_rejects_noncanonical_versions(
    tmp_path: Path,
    version: object,
) -> None:
    archive = tmp_path / "runner.tar.gz"
    _write_metadata_archive(
        archive,
        payload=_metadata_payload(version=version),
    )

    with pytest.raises(RemoteRunnerArtifactError, match="canonical version"):
        verify_packaged_sqlite_metadata(archive)


@pytest.mark.parametrize("version", ["0.0.0", "3.45.3", "3.51.2"])
def test_packaged_sqlite_validation_rejects_versions_below_minimum(
    tmp_path: Path,
    version: str,
) -> None:
    archive = tmp_path / "runner.tar.gz"
    member = f"runtime/conda-meta/libsqlite-{version}-{SQLITE_BUILD}.json"
    _write_metadata_archive(
        archive,
        payload=_metadata_payload(version=version),
        member_name=member,
    )

    with pytest.raises(RemoteRunnerArtifactError, match="below minimum 3.51.3"):
        verify_packaged_sqlite_metadata(archive)


@pytest.mark.parametrize(
    "build",
    [
        None,
        True,
        "",
        " build_0",
        "build_0 ",
        "bad/build",
        "bad\\build",
        "bad\nvalue",
        "x" * 256,
    ],
)
def test_packaged_sqlite_validation_rejects_invalid_builds(
    tmp_path: Path,
    build: object,
) -> None:
    archive = tmp_path / "runner.tar.gz"
    _write_metadata_archive(
        archive,
        payload=_metadata_payload(build=build),
    )

    with pytest.raises(RemoteRunnerArtifactError, match="build is invalid"):
        verify_packaged_sqlite_metadata(archive)


@pytest.mark.parametrize(
    "member_name",
    [
        f"runtime/conda-meta/libsqlite-3.52.0-{SQLITE_BUILD}.json",
        f"runtime/conda-meta/libsqlite-{SQLITE_VERSION}-different_0.json",
    ],
)
def test_packaged_sqlite_validation_rejects_filename_metadata_drift(
    tmp_path: Path,
    member_name: str,
) -> None:
    archive = tmp_path / "runner.tar.gz"
    _write_metadata_archive(archive, member_name=member_name)

    with pytest.raises(RemoteRunnerArtifactError, match="filename does not match"):
        verify_packaged_sqlite_metadata(archive)


@pytest.mark.parametrize(
    "member_name",
    [SQLITE_MEMBER.replace("/", "\\"), f"{SQLITE_MEMBER}."],
)
def test_packaged_sqlite_validation_rejects_non_posix_member_names(
    tmp_path: Path,
    member_name: str,
) -> None:
    archive = tmp_path / "runner.tar.gz"
    _write_metadata_archive(archive, member_name=member_name)

    with pytest.raises(RemoteRunnerArtifactError, match="non-POSIX"):
        verify_packaged_sqlite_metadata(archive)


def test_packaged_sqlite_validation_rejects_normalized_path_collisions(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "runner.tar.gz"
    payload = _metadata_payload()
    _write_archive(
        archive,
        [
            _regular_member(SQLITE_MEMBER, payload),
            _regular_member(f"./{SQLITE_MEMBER}", payload),
        ],
    )

    with pytest.raises(RemoteRunnerArtifactError, match="duplicate or ambiguous"):
        verify_packaged_sqlite_metadata(archive)
