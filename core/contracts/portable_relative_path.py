"""One strict cross-platform contract for portable relative filesystem paths."""

from __future__ import annotations

import re


MAX_PORTABLE_RELATIVE_PATH_BYTES = 4095
MAX_PORTABLE_PATH_COMPONENT_BYTES = 255

_WINDOWS_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")
_WINDOWS_RESERVED_DEVICE_NAMES = frozenset(
    {
        "aux",
        "con",
        "nul",
        "prn",
        *(f"com{index}" for index in range(1, 10)),
        *(f"lpt{index}" for index in range(1, 10)),
    }
)


def require_portable_relative_path(
    value: str,
    *,
    error_code: str = "PORTABLE_RELATIVE_PATH_INVALID",
) -> str:
    """Reject platform aliases, ADS, traversal, controls, and non-ASCII paths."""

    if type(value) is not str:
        raise ValueError(error_code)
    if (
        value != value.strip(" ")
        or value.startswith(("/", "//"))
        or "\\" in value
        or "\x00" in value
        or _WINDOWS_DRIVE_PREFIX.match(value) is not None
    ):
        raise ValueError(error_code)
    try:
        encoded = value.encode("ascii", errors="strict")
    except UnicodeEncodeError:
        raise ValueError(error_code) from None
    components = value.split("/")
    if (
        not encoded
        or len(encoded) > MAX_PORTABLE_RELATIVE_PATH_BYTES
        or any(
            not component
            or component in {".", ".."}
            or component != component.strip(" ")
            or component.endswith((".", " "))
            or ":" in component
            or _is_windows_reserved_device_component(component)
            or len(component.encode("ascii")) > MAX_PORTABLE_PATH_COMPONENT_BYTES
            or any(
                ord(character) < 0x20 or ord(character) > 0x7E
                for character in component
            )
            for component in components
        )
    ):
        raise ValueError(error_code)
    return value


def portable_relative_path_alias_key(value: str) -> tuple[str, ...]:
    """Return the case-insensitive component identity used by Windows."""

    normalized = require_portable_relative_path(value)
    return tuple(component.casefold() for component in normalized.split("/"))


def _is_windows_reserved_device_component(component: str) -> bool:
    return component.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_DEVICE_NAMES


__all__ = [
    "MAX_PORTABLE_PATH_COMPONENT_BYTES",
    "MAX_PORTABLE_RELATIVE_PATH_BYTES",
    "portable_relative_path_alias_key",
    "require_portable_relative_path",
]
