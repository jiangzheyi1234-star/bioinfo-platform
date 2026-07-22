from __future__ import annotations

import json
import tarfile
from pathlib import Path, PurePosixPath
from typing import Literal, TypedDict, cast

from core.contracts.runner_activation_release_bootstrap_manifest import (
    RUNNER_ACTIVATION_RELEASE_BOOTSTRAP_MANIFEST_MAX_BYTES,
    RUNNER_ACTIVATION_RELEASE_BOOTSTRAP_MANIFEST_PATH,
    require_runner_activation_release_bootstrap_manifest_bytes,
)
from core.contracts.remote_runner_sqlite_runtime import (
    REMOTE_RUNNER_SQLITE_MINIMUM_VERSION,
    REMOTE_RUNNER_SQLITE_MINIMUM_VERSION_TEXT,
    require_remote_runner_sqlite_version,
)
from core.remote_runner.artifact_models import RemoteRunnerArtifactError


_PACKAGED_SQLITE_METADATA_PREFIX = "runtime/conda-meta/libsqlite-"
_PACKAGED_SQLITE_METADATA_SUFFIX = ".json"
_PACKAGED_SQLITE_METADATA_MAX_BYTES = 64 * 1024
_PACKAGED_SQLITE_BUILD_MAX_LENGTH = 255

REQUIRED_WRAPPER_ASSET_MEMBERS = frozenset(
    {
        "remote_runner/snakemake_wrappers/v9.8.0/bio/fastp/wrapper.py",
        "remote_runner/snakemake_wrappers/v9.8.0/bio/fastp/environment.yaml",
        "remote_runner/snakemake_wrappers/v9.8.0/bio/fastqc/wrapper.py",
        "remote_runner/snakemake_wrappers/v9.8.0/bio/fastqc/environment.yaml",
        "remote_runner/snakemake_wrappers/v9.8.0/bio/multiqc/wrapper.py",
        "remote_runner/snakemake_wrappers/v9.8.0/bio/multiqc/environment.yaml",
        "remote_runner/snakemake_wrappers/v9.8.0/bio/seqkit/wrapper.py",
        "remote_runner/snakemake_wrappers/v9.8.0/bio/seqkit/environment.yaml",
    }
)


class RemoteRunnerPackagedSqliteEvidence(TypedDict):
    """Canonical static evidence from the archive, never loaded-runtime proof."""

    evidenceKind: Literal["packaged-conda-metadata"]
    minimumVersion: str
    packageName: Literal["libsqlite"]
    packagedVersion: str
    build: str
    metadataMember: str


class _DuplicateJsonKeyError(ValueError):
    pass


class _InvalidJsonConstantError(ValueError):
    pass


def read_remote_runner_bootstrap_manifest(
    archive_path: Path,
) -> dict[str, object]:
    """Read one bounded regular manifest and validate its exact raw JSON bytes."""

    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            members = _validated_posix_archive_members(archive, archive_path)
            member = members.get(RUNNER_ACTIVATION_RELEASE_BOOTSTRAP_MANIFEST_PATH)
            if member is None:
                raise RemoteRunnerArtifactError(
                    f"remote runner artifact manifest not found: {archive_path}"
                )
            payload = _read_bootstrap_manifest_bytes(archive, member, archive_path)
    except RemoteRunnerArtifactError:
        raise
    except (OSError, EOFError, tarfile.TarError) as exc:
        raise RemoteRunnerArtifactError(
            f"remote runner artifact manifest is unreadable: {archive_path}"
        ) from exc

    return require_runner_activation_release_bootstrap_manifest_bytes(
        payload,
        make_error=lambda message: _bootstrap_manifest_contract_error(
            message,
            payload=payload,
            archive_path=archive_path,
        ),
    )


def _bootstrap_manifest_contract_error(
    message: str,
    *,
    payload: bytes,
    archive_path: Path,
) -> RemoteRunnerArtifactError:
    if message == "runner activation release artifactVersion is invalid":
        try:
            decoded = json.loads(payload.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError, RecursionError):
            decoded = None
        raw_version = decoded.get("version") if isinstance(decoded, dict) else None
        message = (
            "remote runner artifact manifest missing version"
            if not isinstance(raw_version, str) or not raw_version
            else "remote runner artifact manifest has unsafe version"
        )
    return RemoteRunnerArtifactError(f"{message}: {archive_path}")


def _read_bootstrap_manifest_bytes(
    archive: tarfile.TarFile,
    member: tarfile.TarInfo,
    archive_path: Path,
) -> bytes:
    if not member.isreg():
        raise RemoteRunnerArtifactError(
            f"remote runner artifact manifest must be a regular file: {archive_path}"
        )
    if member.size > RUNNER_ACTIVATION_RELEASE_BOOTSTRAP_MANIFEST_MAX_BYTES:
        raise RemoteRunnerArtifactError(
            f"remote runner artifact manifest exceeds the size limit: {archive_path}"
        )
    handle = archive.extractfile(member)
    if handle is None:
        raise RemoteRunnerArtifactError(
            f"remote runner artifact manifest is unreadable: {archive_path}"
        )
    with handle:
        payload = handle.read(
            RUNNER_ACTIVATION_RELEASE_BOOTSTRAP_MANIFEST_MAX_BYTES + 1
        )
    if len(payload) != member.size:
        raise RemoteRunnerArtifactError(
            f"remote runner artifact manifest is unreadable: {archive_path}"
        )
    return payload


def verify_packaged_sqlite_metadata(
    archive_path: Path,
) -> RemoteRunnerPackagedSqliteEvidence:
    """Require one safe libsqlite conda record and return static package evidence.

    This proves only what the archive declares.  Startup must independently
    inspect the SQLite library loaded by the bundled Python process.
    """

    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            members = _validated_posix_archive_members(archive, archive_path)
            candidates = [
                (member_name, member)
                for member_name, member in members.items()
                if _is_packaged_sqlite_metadata_member(member_name)
            ]
            if len(candidates) != 1:
                raise RemoteRunnerArtifactError(
                    "remote runner artifact must contain exactly one packaged "
                    "SQLite metadata member"
                )
            member_name, member = candidates[0]
            payload = _read_packaged_sqlite_metadata(
                archive,
                member,
            )
    except RemoteRunnerArtifactError:
        raise
    except (OSError, EOFError, tarfile.TarError) as exc:
        raise RemoteRunnerArtifactError(
            f"remote runner artifact packaged SQLite metadata is unreadable: {archive_path}"
        ) from exc

    metadata = _decode_unique_json_object(payload)
    if metadata.get("name") != "libsqlite":
        raise RemoteRunnerArtifactError(
            "remote runner artifact packaged SQLite package name must be exactly libsqlite"
        )
    raw_version = metadata.get("version")
    packaged_version = require_remote_runner_sqlite_version(
        raw_version,
        field="packaged version",
        make_error=RemoteRunnerArtifactError,
    )
    if packaged_version < REMOTE_RUNNER_SQLITE_MINIMUM_VERSION:
        raise RemoteRunnerArtifactError(
            "remote runner artifact packaged SQLite version is below minimum "
            f"{REMOTE_RUNNER_SQLITE_MINIMUM_VERSION_TEXT}"
        )
    build = _require_packaged_sqlite_build(metadata.get("build"))
    version_text = cast(str, raw_version)
    expected_member = (
        f"{_PACKAGED_SQLITE_METADATA_PREFIX}{version_text}-{build}"
        f"{_PACKAGED_SQLITE_METADATA_SUFFIX}"
    )
    if member_name != expected_member:
        raise RemoteRunnerArtifactError(
            "remote runner artifact packaged SQLite filename does not match metadata"
        )
    return {
        "evidenceKind": "packaged-conda-metadata",
        "minimumVersion": REMOTE_RUNNER_SQLITE_MINIMUM_VERSION_TEXT,
        "packageName": "libsqlite",
        "packagedVersion": version_text,
        "build": build,
        "metadataMember": member_name,
    }


def _validated_posix_archive_members(
    archive: tarfile.TarFile,
    archive_path: Path,
) -> dict[str, tarfile.TarInfo]:
    members: dict[str, tarfile.TarInfo] = {}
    for member in archive.getmembers():
        member_name = _canonical_posix_member_name(member, archive_path)
        if member_name in members:
            raise RemoteRunnerArtifactError(
                f"remote runner artifact has a duplicate or ambiguous tar member: {archive_path}"
            )
        members[member_name] = member
    return members


def _canonical_posix_member_name(
    member: tarfile.TarInfo,
    archive_path: Path,
) -> str:
    raw_name = member.name
    if raw_name in {".", "./"}:
        if member.isdir():
            return ""
        raise RemoteRunnerArtifactError(
            f"remote runner artifact has a non-POSIX tar member: {archive_path}"
        )
    if "\\" in raw_name or any(
        ord(character) < 0x20 or ord(character) == 0x7F for character in raw_name
    ):
        raise RemoteRunnerArtifactError(
            f"remote runner artifact has a non-POSIX tar member: {archive_path}"
        )

    member_name = raw_name[2:] if raw_name.startswith("./") else raw_name
    if member.isdir() and member_name.endswith("/"):
        member_name = member_name[:-1]
    elif member_name.endswith("/"):
        raise RemoteRunnerArtifactError(
            f"remote runner artifact has a non-POSIX tar member: {archive_path}"
        )

    posix_name = PurePosixPath(member_name)
    if (
        not member_name
        or member_name.startswith("./")
        or member_name.startswith("/")
        or "//" in member_name
        or posix_name.is_absolute()
        or ".." in posix_name.parts
        or any(part.endswith(".") for part in posix_name.parts)
        or str(posix_name) != member_name
    ):
        raise RemoteRunnerArtifactError(
            f"remote runner artifact has a non-POSIX tar member: {archive_path}"
        )
    return member_name


def _is_packaged_sqlite_metadata_member(member_name: str) -> bool:
    return member_name.startswith(
        _PACKAGED_SQLITE_METADATA_PREFIX
    ) and member_name.endswith(_PACKAGED_SQLITE_METADATA_SUFFIX)


def _read_packaged_sqlite_metadata(
    archive: tarfile.TarFile,
    member: tarfile.TarInfo,
) -> bytes:
    if not member.isreg():
        raise RemoteRunnerArtifactError(
            "remote runner artifact packaged SQLite metadata must be a regular file"
        )
    if member.size <= 0:
        raise RemoteRunnerArtifactError(
            "remote runner artifact packaged SQLite metadata must not be empty"
        )
    if member.size > _PACKAGED_SQLITE_METADATA_MAX_BYTES:
        raise RemoteRunnerArtifactError(
            "remote runner artifact packaged SQLite metadata exceeds the size limit"
        )
    handle = archive.extractfile(member)
    if handle is None:
        raise RemoteRunnerArtifactError(
            "remote runner artifact packaged SQLite metadata is unreadable"
        )
    with handle:
        payload = handle.read(_PACKAGED_SQLITE_METADATA_MAX_BYTES + 1)
    if len(payload) != member.size:
        raise RemoteRunnerArtifactError(
            "remote runner artifact packaged SQLite metadata is unreadable"
        )
    return payload


def _decode_unique_json_object(payload: bytes) -> dict[str, object]:
    try:
        decoded = payload.decode("utf-8")
        value = json.loads(
            decoded,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except _DuplicateJsonKeyError:
        raise RemoteRunnerArtifactError(
            "remote runner artifact packaged SQLite metadata has duplicate JSON keys"
        ) from None
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        _InvalidJsonConstantError,
        RecursionError,
        ValueError,
    ):
        raise RemoteRunnerArtifactError(
            "remote runner artifact packaged SQLite metadata is malformed JSON"
        ) from None
    if not isinstance(value, dict):
        raise RemoteRunnerArtifactError(
            "remote runner artifact packaged SQLite metadata must be a JSON object"
        )
    return cast(dict[str, object], value)


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateJsonKeyError(key)
        value[key] = item
    return value


def _reject_json_constant(value: str) -> None:
    raise _InvalidJsonConstantError(value)


def _require_packaged_sqlite_build(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _PACKAGED_SQLITE_BUILD_MAX_LENGTH
        or value != value.strip()
        or any(
            character in {"/", "\\"} or ord(character) < 0x20 or ord(character) == 0x7F
            for character in value
        )
    ):
        raise RemoteRunnerArtifactError(
            "remote runner artifact packaged SQLite build is invalid"
        )
    return value


def verify_bundled_runtime_entrypoints(archive_path: Path) -> None:
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            members = _validated_posix_archive_members(archive, archive_path)
    except RemoteRunnerArtifactError:
        raise
    except (OSError, EOFError, tarfile.TarError) as exc:
        raise RemoteRunnerArtifactError(
            f"remote runner artifact runtime entrypoints are unreadable: {archive_path}"
        ) from exc

    for entrypoint in ("runtime/bin/python", "runtime/bin/conda-unpack"):
        target = _resolve_runtime_member(members, entrypoint, archive_path)
        if target.mode & 0o111 == 0:
            raise RemoteRunnerArtifactError(
                f"remote runner artifact runtime executable is not executable: {entrypoint}"
            )


def _resolve_runtime_member(
    members: dict[str, tarfile.TarInfo],
    entrypoint: str,
    archive_path: Path,
) -> tarfile.TarInfo:
    member = members.get(entrypoint)
    if member is None:
        raise RemoteRunnerArtifactError(
            f"remote runner artifact missing runtime executable: {entrypoint}"
        )
    if not member.issym():
        return member
    link = PurePosixPath(member.linkname)
    if (
        not member.linkname
        or "\\" in member.linkname
        or member.linkname.startswith("/")
        or link.is_absolute()
        or ".." in link.parts
    ):
        raise RemoteRunnerArtifactError(
            f"remote runner artifact has unsafe runtime symlink: {archive_path}"
        )
    target_name = str(PurePosixPath(entrypoint).parent.joinpath(link))
    target = members.get(target_name)
    if target is None:
        raise RemoteRunnerArtifactError(
            f"remote runner artifact missing runtime executable: {target_name}"
        )
    return target


def verify_required_wrapper_assets(archive_path: Path) -> None:
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            names = set(_validated_posix_archive_members(archive, archive_path))
    except RemoteRunnerArtifactError:
        raise
    except (OSError, EOFError, tarfile.TarError) as exc:
        raise RemoteRunnerArtifactError(
            f"remote runner artifact wrapper assets are unreadable: {archive_path}"
        ) from exc
    missing = sorted(REQUIRED_WRAPPER_ASSET_MEMBERS - names)
    if missing:
        raise RemoteRunnerArtifactError(
            f"remote runner artifact missing bundled Snakemake wrapper assets: {', '.join(missing)}"
        )
