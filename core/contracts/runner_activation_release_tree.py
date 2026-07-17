"""Dormant canonical identities for installed remote-runner release trees.

The contracts in this module describe a portable, read-only tree shape.  They
do not parse an archive, walk a filesystem, prove publication, bind a host or
installation, authorize a generation, or constitute ``prepared`` evidence.
Archive, provenance, installation, path, and publication identities remain
separate inputs to a future storage receipt.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .runner_activation_target import RUNNER_ACTIVATION_SERVICE
from .runner_activation_validation import (
    canonical_json as _canonical_json,
    fingerprint as _fingerprint,
    require_exact_string as _require_exact_string,
    require_fingerprint as _require_fingerprint,
    require_mapping as _require_mapping,
)


RUNNER_ACTIVATION_RELEASE_TREE_SCHEMA = (
    "h2ometa.runner-installed-release-tree.v1"
)
RUNNER_ACTIVATION_RELEASE_TREE_MANIFEST_SCHEMA = (
    "h2ometa.runner-installed-release-tree-manifest.v1"
)
RUNNER_ACTIVATION_RELEASE_TREE_MATERIALIZATION_POLICY = (
    "h2ometa.runner-installed-release-materialization.v1"
)
RUNNER_ACTIVATION_RELEASE_TREE_ROOT_MODE = "0555"

_MANIFEST_FIELDS = frozenset(
    {
        "entries",
        "materializationPolicyVersion",
        "rootMode",
        "schemaVersion",
        "service",
        "treeContentFingerprint",
    }
)
_ENTRY_FIELDS = frozenset(
    {
        "contentSha256",
        "linkTarget",
        "mode",
        "path",
        "sizeBytes",
        "type",
    }
)
_ENTRY_TYPES = frozenset({"directory", "file", "hardlink", "symlink"})
_FILE_MODES = frozenset({"0444", "0555"})
_DIRECTORY_MODE = "0555"
_SYMLINK_MODE = "0777"
_RESERVED_COMPONENT_PREFIX = ".h2ometa-"
_MAX_ENTRIES = 250_000
_MAX_PATH_BYTES = 4095
_MAX_COMPONENT_BYTES = 255
_MAX_TOTAL_FILE_BYTES = 1 << 40
_MAX_SYMLINK_DEPTH = 40
_TREE_CONTENT_FINGERPRINT_DOMAIN = RUNNER_ACTIVATION_RELEASE_TREE_SCHEMA.encode(
    "ascii"
)
_MANIFEST_FINGERPRINT_DOMAIN = (
    RUNNER_ACTIVATION_RELEASE_TREE_MANIFEST_SCHEMA.encode("ascii")
)


def build_runner_activation_release_tree_manifest(
    entries: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, object]:
    """Build one exact tree manifest from already observed entry records."""

    normalized_entries = _require_entries(entries, make_error=make_error)
    return _normalized_manifest(normalized_entries)


def require_runner_activation_release_tree_entries(
    entries: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> list[dict[str, object]]:
    """Validate portable tree entries without constructing or hashing a manifest."""

    return _require_entries(entries, make_error=make_error)


def require_runner_activation_release_tree_manifest(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, object]:
    """Validate a manifest and return a deeply detached normalized copy."""

    mapping = _require_mapping(
        payload,
        expected=_MANIFEST_FIELDS,
        context="runner activation installed release-tree manifest",
        make_error=make_error,
    )
    _require_exact_string(
        mapping.get("schemaVersion"),
        expected=RUNNER_ACTIVATION_RELEASE_TREE_MANIFEST_SCHEMA,
        field="releaseTreeManifest.schemaVersion",
        make_error=make_error,
    )
    _require_exact_string(
        mapping.get("service"),
        expected=RUNNER_ACTIVATION_SERVICE,
        field="releaseTreeManifest.service",
        make_error=make_error,
    )
    _require_exact_string(
        mapping.get("materializationPolicyVersion"),
        expected=RUNNER_ACTIVATION_RELEASE_TREE_MATERIALIZATION_POLICY,
        field="releaseTreeManifest.materializationPolicyVersion",
        make_error=make_error,
    )
    _require_exact_string(
        mapping.get("rootMode"),
        expected=RUNNER_ACTIVATION_RELEASE_TREE_ROOT_MODE,
        field="releaseTreeManifest.rootMode",
        make_error=make_error,
    )
    normalized_entries = _require_entries(
        mapping.get("entries"),
        make_error=make_error,
    )
    observed_fingerprint = _require_fingerprint(
        mapping.get("treeContentFingerprint"),
        "releaseTreeManifest.treeContentFingerprint",
        make_error,
    )
    expected_fingerprint = _tree_content_fingerprint(normalized_entries)
    if observed_fingerprint != expected_fingerprint:
        raise make_error(
            "runner activation installed release-tree content binding is invalid"
        )
    return _normalized_manifest(normalized_entries)


def runner_activation_release_tree_content_fingerprint(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> str:
    """Return the domain-separated portable tree-content identity."""

    normalized = require_runner_activation_release_tree_manifest(
        payload,
        make_error=make_error,
    )
    return str(normalized["treeContentFingerprint"])


def runner_activation_release_tree_manifest_canonical_json(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> str:
    """Return deterministic compact JSON for the complete manifest."""

    return _canonical_json(
        require_runner_activation_release_tree_manifest(
            payload,
            make_error=make_error,
        )
    )


def runner_activation_release_tree_manifest_fingerprint(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> str:
    """Return the identity of the schema/policy-bound manifest document."""

    return _fingerprint(
        _MANIFEST_FINGERPRINT_DOMAIN,
        runner_activation_release_tree_manifest_canonical_json(
            payload,
            make_error=make_error,
        ),
    )


def _normalized_manifest(
    entries: list[dict[str, object]],
) -> dict[str, object]:
    detached_entries = [dict(entry) for entry in entries]
    return {
        "entries": detached_entries,
        "materializationPolicyVersion": (
            RUNNER_ACTIVATION_RELEASE_TREE_MATERIALIZATION_POLICY
        ),
        "rootMode": RUNNER_ACTIVATION_RELEASE_TREE_ROOT_MODE,
        "schemaVersion": RUNNER_ACTIVATION_RELEASE_TREE_MANIFEST_SCHEMA,
        "service": RUNNER_ACTIVATION_SERVICE,
        "treeContentFingerprint": _tree_content_fingerprint(detached_entries),
    }


def _tree_content_fingerprint(entries: list[dict[str, object]]) -> str:
    return _fingerprint(
        _TREE_CONTENT_FINGERPRINT_DOMAIN,
        _canonical_json(
            {
                "entries": entries,
                "rootMode": RUNNER_ACTIVATION_RELEASE_TREE_ROOT_MODE,
            }
        ),
    )


def _require_entries(
    value: object,
    *,
    make_error: Callable[[str], Exception],
) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(
        value,
        (str, bytes, bytearray),
    ):
        raise make_error("runner activation installed release-tree entries are invalid")
    if not 1 <= len(value) <= _MAX_ENTRIES:
        raise make_error(
            "runner activation installed release-tree entry count is invalid"
        )

    normalized: list[dict[str, object]] = []
    by_path: dict[str, dict[str, object]] = {}
    previous_path = ""
    total_file_bytes = 0
    for raw_entry in value:
        entry = _require_mapping(
            raw_entry,
            expected=_ENTRY_FIELDS,
            context="runner activation installed release-tree entry",
            make_error=make_error,
        )
        path = _require_entry_path(
            entry.get("path"),
            field="entry.path",
            make_error=make_error,
        )
        if previous_path and path <= previous_path:
            raise make_error(
                "runner activation installed release-tree entries are not strictly ordered"
            )
        previous_path = path
        parent = path.rpartition("/")[0]
        if parent:
            parent_entry = by_path.get(parent)
            if parent_entry is None or parent_entry["type"] != "directory":
                raise make_error(
                    "runner activation installed release-tree parent is invalid"
                )

        entry_type = entry.get("type")
        if not isinstance(entry_type, str) or entry_type not in _ENTRY_TYPES:
            raise make_error(
                "runner activation installed release-tree entry type is invalid"
            )
        mode = entry.get("mode")
        size_bytes = _require_nonnegative_integer(
            entry.get("sizeBytes"),
            field="entry.sizeBytes",
            make_error=make_error,
        )
        content_sha256 = entry.get("contentSha256")
        link_target = entry.get("linkTarget")
        if not isinstance(content_sha256, str) or not isinstance(link_target, str):
            raise make_error(
                "runner activation installed release-tree entry content fields are invalid"
            )

        if entry_type == "directory":
            _require_directory_entry(
                mode=mode,
                size_bytes=size_bytes,
                content_sha256=content_sha256,
                link_target=link_target,
                make_error=make_error,
            )
        elif entry_type == "file":
            _require_file_entry(
                mode=mode,
                content_sha256=content_sha256,
                link_target=link_target,
                make_error=make_error,
            )
            total_file_bytes += size_bytes
        elif entry_type == "symlink":
            link_target = _require_symlink_target(
                link_target,
                make_error=make_error,
            )
            if (
                mode != _SYMLINK_MODE
                or size_bytes != len(link_target.encode("ascii"))
                or content_sha256
            ):
                raise make_error(
                    "runner activation installed release-tree symlink metadata is invalid"
                )
        else:
            primary_path = _require_entry_path(
                link_target,
                field="entry.linkTarget",
                make_error=make_error,
            )
            primary = by_path.get(primary_path)
            if (
                primary_path >= path
                or primary is None
                or primary["type"] != "file"
                or mode != primary["mode"]
                or size_bytes != primary["sizeBytes"]
                or content_sha256 != primary["contentSha256"]
            ):
                raise make_error(
                    "runner activation installed release-tree hardlink binding is invalid"
                )
            total_file_bytes += size_bytes
            link_target = primary_path

        if total_file_bytes > _MAX_TOTAL_FILE_BYTES:
            raise make_error(
                "runner activation installed release-tree total file size is invalid"
            )
        normalized_entry = {
            "contentSha256": content_sha256,
            "linkTarget": link_target,
            "mode": mode,
            "path": path,
            "sizeBytes": size_bytes,
            "type": entry_type,
        }
        normalized.append(normalized_entry)
        by_path[path] = normalized_entry

    symlink_targets = _require_symlink_bindings(
        normalized,
        by_path=by_path,
        make_error=make_error,
    )
    _require_acyclic_tree_graph(
        normalized,
        by_path=by_path,
        symlink_targets=symlink_targets,
        make_error=make_error,
    )
    return normalized


def _require_directory_entry(
    *,
    mode: object,
    size_bytes: int,
    content_sha256: str,
    link_target: str,
    make_error: Callable[[str], Exception],
) -> None:
    if (
        mode != _DIRECTORY_MODE
        or size_bytes != 0
        or content_sha256
        or link_target
    ):
        raise make_error(
            "runner activation installed release-tree directory metadata is invalid"
        )


def _require_file_entry(
    *,
    mode: object,
    content_sha256: str,
    link_target: str,
    make_error: Callable[[str], Exception],
) -> None:
    if mode not in _FILE_MODES or link_target:
        raise make_error(
            "runner activation installed release-tree file metadata is invalid"
        )
    _require_fingerprint(
        content_sha256,
        "releaseTreeManifest.entry.contentSha256",
        make_error,
    )


def _require_entry_path(
    value: object,
    *,
    field: str,
    make_error: Callable[[str], Exception],
) -> str:
    if not isinstance(value, str) or not value or value.startswith("/") or "\\" in value:
        raise make_error(f"runner activation releaseTreeManifest.{field} is invalid")
    try:
        encoded = value.encode("ascii", errors="strict")
    except UnicodeEncodeError:
        raise make_error(
            f"runner activation releaseTreeManifest.{field} is invalid"
        ) from None
    components = value.split("/")
    if (
        len(encoded) > _MAX_PATH_BYTES
        or any(byte < 0x20 or byte > 0x7E for byte in encoded)
        or any(
            not component
            or component in {".", ".."}
            or component != component.strip(" ")
            or len(component.encode("ascii")) > _MAX_COMPONENT_BYTES
            or component.startswith(_RESERVED_COMPONENT_PREFIX)
            for component in components
        )
    ):
        raise make_error(f"runner activation releaseTreeManifest.{field} is invalid")
    return value


def _require_symlink_target(
    value: object,
    *,
    make_error: Callable[[str], Exception],
) -> str:
    if not isinstance(value, str) or not value or value.startswith("/") or "\\" in value:
        raise make_error(
            "runner activation releaseTreeManifest.entry.linkTarget is invalid"
        )
    try:
        encoded = value.encode("ascii", errors="strict")
    except UnicodeEncodeError:
        raise make_error(
            "runner activation releaseTreeManifest.entry.linkTarget is invalid"
        ) from None
    components = value.split("/")
    if (
        len(encoded) > _MAX_PATH_BYTES
        or any(byte < 0x20 or byte > 0x7E for byte in encoded)
        or any(
            not component
            or component != component.strip(" ")
            or len(component.encode("ascii")) > _MAX_COMPONENT_BYTES
            for component in components
        )
    ):
        raise make_error(
            "runner activation releaseTreeManifest.entry.linkTarget is invalid"
        )
    return value


def _require_nonnegative_integer(
    value: object,
    *,
    field: str,
    make_error: Callable[[str], Exception],
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise make_error(f"runner activation releaseTreeManifest.{field} is invalid")
    return value


def _require_symlink_bindings(
    entries: list[dict[str, object]],
    *,
    by_path: Mapping[str, dict[str, object]],
    make_error: Callable[[str], Exception],
) -> dict[str, str]:
    cache: dict[str, str] = {}
    targets: dict[str, str] = {}
    for entry in entries:
        if entry["type"] != "symlink":
            continue
        path = str(entry["path"])
        targets[path] = _resolve_symlink_entry(
            path,
            by_path=by_path,
            cache=cache,
            active=set(),
            depth=0,
            make_error=make_error,
        )
    return targets


def _resolve_symlink_entry(
    path: str,
    *,
    by_path: Mapping[str, dict[str, object]],
    cache: dict[str, str],
    active: set[str],
    depth: int,
    make_error: Callable[[str], Exception],
) -> str:
    cached = cache.get(path)
    if cached is not None:
        return cached
    if path in active or depth >= _MAX_SYMLINK_DEPTH:
        raise make_error(
            "runner activation installed release-tree symlink cycle or depth is invalid"
        )
    entry = by_path.get(path)
    if entry is None or entry["type"] != "symlink":
        raise make_error(
            "runner activation installed release-tree symlink binding is invalid"
        )
    active.add(path)
    try:
        resolved = _resolve_symlink_components(
            path.split("/")[:-1],
            str(entry["linkTarget"]).split("/"),
            by_path=by_path,
            cache=cache,
            active=active,
            depth=depth,
            make_error=make_error,
        )
    finally:
        active.remove(path)
    cache[path] = resolved
    return resolved


def _resolve_symlink_components(
    base: list[str],
    pending: list[str],
    *,
    by_path: Mapping[str, dict[str, object]],
    cache: dict[str, str],
    active: set[str],
    depth: int,
    make_error: Callable[[str], Exception],
) -> str:
    resolved = list(base)
    for index, component in enumerate(pending):
        has_remaining = index + 1 < len(pending)
        if component == ".":
            continue
        if component == "..":
            if not resolved:
                raise make_error(
                    "runner activation installed release-tree symlink escapes root"
                )
            resolved.pop()
            continue
        candidate = "/".join([*resolved, component])
        candidate_entry = by_path.get(candidate)
        if candidate_entry is None:
            raise make_error(
                "runner activation installed release-tree symlink is dangling"
            )
        if candidate_entry["type"] == "symlink":
            terminal = _resolve_symlink_entry(
                candidate,
                by_path=by_path,
                cache=cache,
                active=active,
                depth=depth + 1,
                make_error=make_error,
            )
            terminal_entry = by_path[terminal]
            if has_remaining and terminal_entry["type"] != "directory":
                raise make_error(
                    "runner activation installed release-tree symlink traversal is invalid"
                )
            resolved = terminal.split("/")
            continue
        if has_remaining and candidate_entry["type"] != "directory":
            raise make_error(
                "runner activation installed release-tree symlink traversal is invalid"
            )
        resolved.append(component)
    if not resolved:
        raise make_error(
            "runner activation installed release-tree symlink target is invalid"
        )
    target_path = "/".join(resolved)
    if target_path not in by_path:
        raise make_error(
            "runner activation installed release-tree symlink is dangling"
        )
    return target_path


def _require_acyclic_tree_graph(
    entries: list[dict[str, object]],
    *,
    by_path: Mapping[str, dict[str, object]],
    symlink_targets: Mapping[str, str],
    make_error: Callable[[str], Exception],
) -> None:
    children: dict[str, list[str]] = {"": []}
    for entry in entries:
        path = str(entry["path"])
        parent = path.rpartition("/")[0]
        children.setdefault(parent, []).append(path)
        if entry["type"] == "directory":
            children.setdefault(path, [])

    def neighbors(path: str) -> Sequence[str]:
        if path == "":
            return children[""]
        entry = by_path[path]
        if entry["type"] == "directory":
            return children.get(path, ())
        if entry["type"] == "symlink":
            return (symlink_targets[path],)
        return ()

    colors: dict[str, int] = {"": 1}
    stack: list[tuple[str, Any]] = [("", iter(neighbors("")))]
    while stack:
        path, iterator = stack[-1]
        try:
            child = next(iterator)
        except StopIteration:
            colors[path] = 2
            stack.pop()
            continue
        state = colors.get(child, 0)
        if state == 1:
            raise make_error(
                "runner activation installed release-tree symlink cycle is invalid"
            )
        if state == 0:
            colors[child] = 1
            stack.append((child, iter(neighbors(child))))


__all__ = [
    "RUNNER_ACTIVATION_RELEASE_TREE_MANIFEST_SCHEMA",
    "RUNNER_ACTIVATION_RELEASE_TREE_MATERIALIZATION_POLICY",
    "RUNNER_ACTIVATION_RELEASE_TREE_ROOT_MODE",
    "RUNNER_ACTIVATION_RELEASE_TREE_SCHEMA",
    "build_runner_activation_release_tree_manifest",
    "require_runner_activation_release_tree_entries",
    "require_runner_activation_release_tree_manifest",
    "runner_activation_release_tree_content_fingerprint",
    "runner_activation_release_tree_manifest_canonical_json",
    "runner_activation_release_tree_manifest_fingerprint",
]
