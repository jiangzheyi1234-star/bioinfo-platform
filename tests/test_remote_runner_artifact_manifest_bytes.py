from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import tarfile

import pytest

from core.contracts.runner_activation_release_bootstrap_manifest import (
    RUNNER_ACTIVATION_RELEASE_BOOTSTRAP_MANIFEST_MAX_BYTES,
)
from core.remote_runner.artifact import RemoteRunnerArtifactProvider
from core.remote_runner.artifact_models import RemoteRunnerArtifactError
from core.remote_runner.protocol_manifest import build_runner_protocol_manifest_fields
from core.remote_runner.remote_runner_artifact_validation import (
    read_remote_runner_bootstrap_manifest,
)
from scripts import check_remote_runner_release_artifacts as release_checker


def _manifest_payload(*, version: str = "dev") -> bytes:
    return json.dumps(
        {
            "service": "h2ometa-remote",
            "version": version,
            "platform": "linux-64",
            "runtime": {
                "provider": "bundled",
                "python": "runtime/bin/python",
                "sqlite": {"minimumVersion": "3.51.3"},
            },
            **build_runner_protocol_manifest_fields(),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _regular_member(name: str, payload: bytes) -> tuple[tarfile.TarInfo, bytes]:
    member = tarfile.TarInfo(name)
    member.size = len(payload)
    return member, payload


def _write_archive(
    path: Path,
    members: list[tuple[tarfile.TarInfo, bytes | None]],
    *,
    checksum: bool = False,
) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for member, payload in members:
            archive.addfile(
                member,
                io.BytesIO(payload) if payload is not None else None,
            )
    if checksum:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        Path(str(path) + ".sha256").write_text(
            f"{digest}  {path.name}\n",
            encoding="utf-8",
        )


@pytest.mark.parametrize(
    "member_name",
    ["bootstrap_manifest.json", "./bootstrap_manifest.json"],
)
def test_strict_manifest_reader_accepts_one_bounded_regular_member(
    tmp_path: Path,
    member_name: str,
) -> None:
    archive = tmp_path / "runner.tar.gz"
    manifest = _manifest_payload()
    _write_archive(archive, [_regular_member(member_name, manifest)])

    parsed = read_remote_runner_bootstrap_manifest(archive)

    assert parsed["version"] == "dev"
    assert parsed["runtime"] == {
        "provider": "bundled",
        "python": "runtime/bin/python",
        "sqlite": {"minimumVersion": "3.51.3"},
    }


def test_strict_manifest_reader_accepts_the_exact_size_limit(tmp_path: Path) -> None:
    archive = tmp_path / "runner.tar.gz"
    manifest = _manifest_payload()
    padded = manifest + b" " * (
        RUNNER_ACTIVATION_RELEASE_BOOTSTRAP_MANIFEST_MAX_BYTES - len(manifest)
    )
    _write_archive(
        archive,
        [_regular_member("bootstrap_manifest.json", padded)],
    )

    parsed = read_remote_runner_bootstrap_manifest(archive)

    assert parsed["version"] == "dev"


def test_strict_manifest_reader_rejects_an_oversized_member(tmp_path: Path) -> None:
    archive = tmp_path / "runner.tar.gz"
    payload = b"x" * (RUNNER_ACTIVATION_RELEASE_BOOTSTRAP_MANIFEST_MAX_BYTES + 1)
    _write_archive(
        archive,
        [_regular_member("bootstrap_manifest.json", payload)],
    )

    with pytest.raises(RemoteRunnerArtifactError, match="size limit"):
        read_remote_runner_bootstrap_manifest(archive)


@pytest.mark.parametrize(
    "member_type", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.DIRTYPE]
)
def test_strict_manifest_reader_requires_a_regular_member(
    tmp_path: Path,
    member_type: bytes,
) -> None:
    archive = tmp_path / "runner.tar.gz"
    target, target_payload = _regular_member(
        "manifest-target.json", _manifest_payload()
    )
    manifest = tarfile.TarInfo("bootstrap_manifest.json")
    manifest.type = member_type
    manifest.linkname = "manifest-target.json" if member_type != tarfile.DIRTYPE else ""
    _write_archive(archive, [(target, target_payload), (manifest, None)])

    with pytest.raises(RemoteRunnerArtifactError, match="regular file"):
        read_remote_runner_bootstrap_manifest(archive)


@pytest.mark.parametrize(
    "duplicate_name",
    ["bootstrap_manifest.json", "./bootstrap_manifest.json"],
)
def test_strict_manifest_reader_rejects_duplicate_or_normalized_collision(
    tmp_path: Path,
    duplicate_name: str,
) -> None:
    archive = tmp_path / "runner.tar.gz"
    manifest = _manifest_payload()
    _write_archive(
        archive,
        [
            _regular_member("bootstrap_manifest.json", manifest),
            _regular_member(duplicate_name, manifest),
        ],
    )

    with pytest.raises(RemoteRunnerArtifactError, match="duplicate or ambiguous"):
        read_remote_runner_bootstrap_manifest(archive)


@pytest.mark.parametrize(
    "member_name",
    [
        "bootstrap_manifest.json.",
        "bootstrap\\manifest.json",
        "././bootstrap_manifest.json",
    ],
)
def test_strict_manifest_reader_rejects_non_posix_or_noncanonical_names(
    tmp_path: Path,
    member_name: str,
) -> None:
    archive = tmp_path / "runner.tar.gz"
    _write_archive(archive, [_regular_member(member_name, _manifest_payload())])

    with pytest.raises(RemoteRunnerArtifactError, match="non-POSIX"):
        read_remote_runner_bootstrap_manifest(archive)


def _duplicate_version_payload() -> bytes:
    payload = _manifest_payload()
    return payload[:-1] + b',"version":"duplicate"}'


def test_strict_manifest_reader_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    archive = tmp_path / "runner.tar.gz"
    _write_archive(
        archive,
        [_regular_member("bootstrap_manifest.json", _duplicate_version_payload())],
    )

    with pytest.raises(RemoteRunnerArtifactError, match="manifest bytes are invalid"):
        read_remote_runner_bootstrap_manifest(archive)


def test_artifact_provider_uses_the_strict_manifest_reader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = tmp_path / "runner.tar.gz"
    _write_archive(
        archive,
        [_regular_member("bootstrap_manifest.json", _duplicate_version_payload())],
        checksum=True,
    )
    monkeypatch.setenv("H2OMETA_REMOTE_RUNNER_BUNDLE", str(archive))

    with pytest.raises(RemoteRunnerArtifactError, match="manifest bytes are invalid"):
        RemoteRunnerArtifactProvider(search_roots=[]).resolve(
            "dev",
            platform="linux-64",
        )


def test_staging_release_checker_uses_the_strict_manifest_reader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = tmp_path / "runner.tar.gz"
    _write_archive(
        archive,
        [_regular_member("bootstrap_manifest.json", _duplicate_version_payload())],
        checksum=True,
    )
    monkeypatch.setenv("H2OMETA_REMOTE_RUNNER_BUNDLE", str(archive))

    with pytest.raises(RemoteRunnerArtifactError, match="manifest bytes are invalid"):
        release_checker._resolve_staging_runner_bundle()
