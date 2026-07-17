"""Bounded normalized member graph for a remote-runner release archive."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from .runner_activation_release_tree import (
    require_runner_activation_release_tree_entries,
)
from .runner_activation_validation import (
    canonical_json as _canonical_json,
    require_fingerprint as _require_fingerprint,
    require_mapping as _require_mapping,
)


RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_MEMBERS = 100_000
RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_MEMBER_BYTES = 4 * 1024**3
RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_TOTAL_BYTES = 16 * 1024**3
RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_MEMBER_METADATA_BYTES = 32 * 1024**2

_MEMBER_FIELDS = frozenset(
    {"contentSha256", "linkTarget", "mode", "path", "sizeBytes", "type"}
)
_MEMBER_TYPES = frozenset({"directory", "file", "hardlink", "symlink"})
_FILE_MODES = frozenset({"0644", "0755"})
_DIRECTORY_MODE = "0755"
_SYMLINK_MODE = "0777"
_RESERVED_COMPONENT_PREFIX = ".h2ometa-"
_MAX_PATH_BYTES = 4095
_MAX_COMPONENT_BYTES = 255


class _ArchiveGraphError(Exception):
    pass


def require_runner_activation_release_archive_members(
    value: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> tuple[list[dict[str, object]], int]:
    """Validate ordered archive members and return their metadata byte total."""

    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise make_error(
            "runner activation installed release archive members are invalid"
        )
    if not 1 <= len(value) <= RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_MEMBERS:
        raise make_error(
            "runner activation installed release archive member count exceeds policy"
        )

    normalized: list[dict[str, object]] = []
    by_path: dict[str, dict[str, object]] = {}
    previous_path = ""
    total_payload_bytes = 0
    total_tree_file_bytes = 0
    total_member_metadata_bytes = 0
    regular_files = 0
    for raw_member in value:
        member = _require_mapping(
            raw_member,
            expected=_MEMBER_FIELDS,
            context="runner activation installed release archive member",
            make_error=make_error,
        )
        path = _require_member_path(
            member.get("path"), field="member.path", make_error=make_error
        )
        if previous_path and path <= previous_path:
            raise make_error(
                "runner activation installed release archive members are not strictly ordered"
            )
        previous_path = path
        parent = path.rpartition("/")[0]
        if parent:
            parent_member = by_path.get(parent)
            if parent_member is None or parent_member["type"] != "directory":
                raise make_error(
                    "runner activation installed release archive parent is invalid"
                )

        member_type = member.get("type")
        if not isinstance(member_type, str) or member_type not in _MEMBER_TYPES:
            raise make_error(
                "runner activation installed release archive member type is invalid"
            )
        mode = member.get("mode")
        size_bytes = _require_nonnegative_integer(
            member.get("sizeBytes"), field="member.sizeBytes", make_error=make_error
        )
        content_sha256 = member.get("contentSha256")
        link_target = member.get("linkTarget")
        if not isinstance(content_sha256, str) or not isinstance(link_target, str):
            raise make_error(
                "runner activation installed release archive member content is invalid"
            )

        if member_type == "directory":
            if (
                mode != _DIRECTORY_MODE
                or size_bytes != 0
                or content_sha256
                or link_target
            ):
                raise make_error(
                    "runner activation installed release archive directory metadata is invalid"
                )
        elif member_type == "file":
            if mode not in _FILE_MODES or link_target:
                raise make_error(
                    "runner activation installed release archive file metadata is invalid"
                )
            _require_fingerprint(
                content_sha256,
                "releaseArchiveManifest.member.contentSha256",
                make_error,
            )
            if size_bytes > RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_MEMBER_BYTES:
                raise make_error(
                    "runner activation installed release archive member size exceeds policy"
                )
            regular_files += 1
            total_payload_bytes += size_bytes
            total_tree_file_bytes += size_bytes
        elif member_type == "symlink":
            if (
                mode != _SYMLINK_MODE
                or size_bytes != 0
                or content_sha256
                or not link_target
            ):
                raise make_error(
                    "runner activation installed release archive symlink metadata is invalid"
                )
            link_target = _require_symlink_target(link_target, make_error=make_error)
        else:
            link_target = _require_member_path(
                link_target,
                field="member.linkTarget",
                make_error=make_error,
            )
            if size_bytes != 0 or content_sha256:
                raise make_error(
                    "runner activation installed release archive hardlink binding is invalid"
                )

        if (
            total_payload_bytes > RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_TOTAL_BYTES
            or total_tree_file_bytes > RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_TOTAL_BYTES
        ):
            raise make_error(
                "runner activation installed release archive total file size exceeds policy"
            )
        normalized_member = {
            "contentSha256": content_sha256,
            "linkTarget": link_target,
            "mode": mode,
            "path": path,
            "sizeBytes": size_bytes,
            "type": member_type,
        }
        total_member_metadata_bytes += len(
            _canonical_json(normalized_member).encode("utf-8")
        )
        if (
            total_member_metadata_bytes
            > RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_MEMBER_METADATA_BYTES
        ):
            raise make_error(
                "runner activation installed release archive member metadata size "
                "exceeds policy"
            )
        normalized.append(normalized_member)
        by_path[path] = normalized_member

    _require_hardlink_bindings(
        normalized,
        by_path=by_path,
        total_tree_file_bytes=total_tree_file_bytes,
        make_error=make_error,
    )
    if regular_files == 0:
        raise make_error(
            "runner activation installed release archive has no regular file payload"
        )
    _require_release_tree_graph(normalized, by_path=by_path, make_error=make_error)
    return normalized, total_member_metadata_bytes


def _require_hardlink_bindings(
    members: Sequence[dict[str, object]],
    *,
    by_path: Mapping[str, dict[str, object]],
    total_tree_file_bytes: int,
    make_error: Callable[[str], Exception],
) -> None:
    for member in members:
        if member["type"] != "hardlink":
            continue
        primary = by_path.get(str(member["linkTarget"]))
        if (
            primary is None
            or primary["type"] != "file"
            or member["mode"] != primary["mode"]
        ):
            raise make_error(
                "runner activation installed release archive hardlink binding is invalid"
            )
        total_tree_file_bytes += int(primary["sizeBytes"])
        if total_tree_file_bytes > RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_TOTAL_BYTES:
            raise make_error(
                "runner activation installed release archive total file size exceeds policy"
            )


def _require_release_tree_graph(
    members: list[dict[str, object]],
    *,
    by_path: Mapping[str, dict[str, object]],
    make_error: Callable[[str], Exception],
) -> None:
    canonical_primary_by_raw_primary: dict[str, str] = {}
    for member in members:
        if member["type"] != "hardlink":
            continue
        raw_primary = str(member["linkTarget"])
        canonical_primary_by_raw_primary[raw_primary] = min(
            raw_primary,
            canonical_primary_by_raw_primary.get(raw_primary, raw_primary),
            str(member["path"]),
        )

    entries: list[dict[str, object]] = []
    for member in members:
        member_type = str(member["type"])
        if member_type == "directory":
            entry_type, mode, size_bytes, content_sha256, link_target = (
                "directory",
                "0555",
                0,
                "",
                "",
            )
        elif member_type == "symlink":
            link_target = str(member["linkTarget"])
            entry_type, mode, size_bytes, content_sha256 = (
                "symlink",
                "0777",
                len(link_target.encode("ascii", errors="strict")),
                "",
            )
        else:
            primary = (
                member if member_type == "file" else by_path[str(member["linkTarget"])]
            )
            raw_primary = str(primary["path"])
            canonical_primary = canonical_primary_by_raw_primary.get(
                raw_primary,
                raw_primary,
            )
            entry_type = "file" if member["path"] == canonical_primary else "hardlink"
            mode = "0555" if primary["mode"] == "0755" else "0444"
            size_bytes = int(primary["sizeBytes"])
            content_sha256 = str(primary["contentSha256"])
            link_target = "" if entry_type == "file" else canonical_primary
        entries.append(
            {
                "contentSha256": content_sha256,
                "linkTarget": link_target,
                "mode": mode,
                "path": member["path"],
                "sizeBytes": size_bytes,
                "type": entry_type,
            }
        )
    try:
        require_runner_activation_release_tree_entries(
            entries,
            make_error=lambda message: _ArchiveGraphError(message),
        )
    except (_ArchiveGraphError, UnicodeEncodeError):
        raise make_error(
            "runner activation installed release archive member graph is invalid"
        ) from None


def _require_member_path(
    value: object,
    *,
    field: str,
    make_error: Callable[[str], Exception],
) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_PATH_BYTES
        or value.startswith("/")
        or "\\" in value
    ):
        raise make_error(f"runner activation releaseArchiveManifest.{field} is invalid")
    try:
        encoded = value.encode("ascii", errors="strict")
    except UnicodeEncodeError:
        raise make_error(
            f"runner activation releaseArchiveManifest.{field} is invalid"
        ) from None
    components = value.split("/")
    if any(byte < 0x20 or byte > 0x7E for byte in encoded) or any(
        not component
        or component in {".", ".."}
        or component != component.strip(" ")
        or len(component) > _MAX_COMPONENT_BYTES
        or component.startswith(_RESERVED_COMPONENT_PREFIX)
        for component in components
    ):
        raise make_error(f"runner activation releaseArchiveManifest.{field} is invalid")
    return value


def _require_symlink_target(
    value: object,
    *,
    make_error: Callable[[str], Exception],
) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_PATH_BYTES
        or value.startswith("/")
        or "\\" in value
    ):
        raise make_error(
            "runner activation releaseArchiveManifest.member.linkTarget is invalid"
        )
    try:
        encoded = value.encode("ascii", errors="strict")
    except UnicodeEncodeError:
        raise make_error(
            "runner activation releaseArchiveManifest.member.linkTarget is invalid"
        ) from None
    components = value.split("/")
    if any(byte < 0x20 or byte > 0x7E for byte in encoded) or any(
        not component
        or component != component.strip(" ")
        or len(component) > _MAX_COMPONENT_BYTES
        for component in components
    ):
        raise make_error(
            "runner activation releaseArchiveManifest.member.linkTarget is invalid"
        )
    return value


def _require_nonnegative_integer(
    value: object,
    *,
    field: str,
    make_error: Callable[[str], Exception],
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise make_error(f"runner activation releaseArchiveManifest.{field} is invalid")
    return value


__all__ = [
    "RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_MEMBER_BYTES",
    "RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_MEMBER_METADATA_BYTES",
    "RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_MEMBERS",
    "RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_TOTAL_BYTES",
    "require_runner_activation_release_archive_members",
]
