"""Private validation primitives for remote-runner activation contracts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Any


_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_FINGERPRINT_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_MAX_PATH_LENGTH = 4096


def require_mapping(
    payload: object,
    *,
    expected: frozenset[str],
    context: str,
    make_error: Callable[[str], Exception],
) -> Mapping[object, Any]:
    if not isinstance(payload, Mapping):
        raise make_error(f"{context} must be an object")
    if frozenset(payload.keys()) != expected:
        raise make_error(f"{context} fields must match exactly")
    return payload


def require_exact_string(
    value: object,
    *,
    expected: str,
    field: str,
    make_error: Callable[[str], Exception],
) -> None:
    if not isinstance(value, str) or value != expected:
        raise make_error(f"runner activation {field} is invalid")


def require_id(
    value: object,
    field: str,
    make_error: Callable[[str], Exception],
) -> str:
    if not isinstance(value, str) or _ID_PATTERN.fullmatch(value) is None:
        raise make_error(f"runner activation {field} is invalid")
    return value


def require_optional_id(
    value: object,
    field: str,
    make_error: Callable[[str], Exception],
) -> str:
    if value == "":
        return ""
    return require_id(value, field, make_error)


def require_fingerprint(
    value: object,
    field: str,
    make_error: Callable[[str], Exception],
) -> str:
    if not isinstance(value, str) or _FINGERPRINT_PATTERN.fullmatch(value) is None:
        raise make_error(f"runner activation {field} is invalid")
    return value


def require_optional_fingerprint(
    value: object,
    field: str,
    make_error: Callable[[str], Exception],
) -> str:
    if value == "":
        return ""
    return require_fingerprint(value, field, make_error)


def require_absolute_posix_path(
    value: object,
    field: str,
    make_error: Callable[[str], Exception],
) -> PurePosixPath:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_PATH_LENGTH
        or value != value.strip()
        or value.startswith("//")
        or "\\" in value
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
    ):
        raise make_error(f"runner activation {field} is invalid")
    try:
        encoded = value.encode("utf-8")
        path = PurePosixPath(value)
    except (UnicodeEncodeError, ValueError) as exc:
        raise make_error(f"runner activation {field} is invalid") from exc
    if (
        len(encoded) > _MAX_PATH_LENGTH
        or not path.is_absolute()
        or path == PurePosixPath("/")
        or str(path) != value
        or any(part in {".", ".."} for part in path.parts)
    ):
        raise make_error(f"runner activation {field} is invalid")
    return path


def require_positive_integer(
    value: object,
    field: str,
    make_error: Callable[[str], Exception],
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise make_error(f"runner activation {field} is invalid")
    return value


def require_token_rotation_preserves_runtime(
    target: dict[str, object],
    previous: dict[str, object],
    *,
    make_error: Callable[[str], Exception],
) -> None:
    generation = target["generation"]
    previous_generation = previous["generation"]
    if not isinstance(generation, dict) or not isinstance(
        previous_generation,
        dict,
    ):
        raise make_error("runner activation target generation is invalid")
    preserved_generation_fields = (
        "profileFingerprint",
        "protocolFingerprint",
        "protocolVersion",
        "releaseArtifactSha256",
        "releasePath",
        "runtimeConfigFingerprint",
        "service",
        "systemdUnitTemplateFingerprint",
    )
    runtime_changed = any(
        generation[field] != previous_generation[field]
        for field in preserved_generation_fields
    )
    if runtime_changed:
        raise make_error("runner activation token_rotation changed runtime identity")
    credential_unchanged = (
        generation["generationId"] == previous_generation["generationId"]
        or generation["tokenGenerationId"] == previous_generation["tokenGenerationId"]
        or generation["configFingerprint"] == previous_generation["configFingerprint"]
    )
    if credential_unchanged:
        raise make_error(
            "runner activation token_rotation did not create a new credential generation"
        )


def canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def fingerprint(domain: bytes, canonical: str) -> str:
    digest = hashlib.sha256(domain + b"\x00" + canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


__all__ = [
    "canonical_json",
    "fingerprint",
    "require_absolute_posix_path",
    "require_exact_string",
    "require_fingerprint",
    "require_id",
    "require_mapping",
    "require_optional_fingerprint",
    "require_optional_id",
    "require_positive_integer",
    "require_token_rotation_preserves_runtime",
]
