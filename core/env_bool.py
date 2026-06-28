from __future__ import annotations


TRUE_ENV_BOOL_VALUES = frozenset(("1", "true", "yes", "on"))
FALSE_ENV_BOOL_VALUES = frozenset(("0", "false", "no", "off"))


def parse_strict_env_bool(
    value: str | None,
    *,
    name: str,
    default: bool | None = None,
) -> bool | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return default
    if normalized in TRUE_ENV_BOOL_VALUES:
        return True
    if normalized in FALSE_ENV_BOOL_VALUES:
        return False
    raise ValueError(f"{name}_INVALID")
