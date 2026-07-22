"""Strict runtime evidence for the SQLite library loaded by remote-runner Python.

Observation and authorization are deliberately separate.  Observation may
return ``ok=False`` so startup diagnostics can report an outdated runtime, but
the ``require_*`` entry points fail closed unless both same-process version
sources agree and meet the fixed minimum.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import closing
import re
from typing import Protocol, TypedDict, cast


REMOTE_RUNNER_SQLITE_MINIMUM_VERSION = (3, 51, 3)
REMOTE_RUNNER_SQLITE_MINIMUM_VERSION_TEXT = "3.51.3"

_EVIDENCE_FIELDS = frozenset({"minimumVersion", "loadedVersion", "sqlVersion", "ok"})
_CANONICAL_VERSION = re.compile(
    r"^(?:0|[1-9][0-9]{0,9})\."
    r"(?:0|[1-9][0-9]{0,9})\."
    r"(?:0|[1-9][0-9]{0,9})$"
)
_MAX_VERSION_COMPONENT = 2_147_483_647
_SQLITE_VERSION_QUERY = "SELECT sqlite_version()"

type _Version = tuple[int, int, int]
type _ErrorFactory = Callable[[str], Exception]


class RemoteRunnerSqliteRuntimeEvidence(TypedDict):
    """Canonical, non-secret evidence safe to expose in startup diagnostics."""

    minimumVersion: str
    loadedVersion: str
    sqlVersion: str
    ok: bool


class _SqliteCursor(Protocol):
    def fetchone(self) -> object: ...

    def close(self) -> None: ...


class _SqliteConnection(Protocol):
    def execute(self, statement: str) -> _SqliteCursor: ...

    def close(self) -> None: ...


class _SqliteModule(Protocol):
    sqlite_version_info: object

    def connect(self, database: str, /) -> _SqliteConnection: ...


def collect_remote_runner_sqlite_runtime_evidence(
    *,
    sqlite_module: _SqliteModule | None = None,
    make_error: _ErrorFactory = ValueError,
) -> RemoteRunnerSqliteRuntimeEvidence:
    """Observe the loaded SQLite runtime twice inside this Python process.

    The module hook exists only for deterministic contract tests.  Production
    callers omit it and therefore inspect the standard-library ``sqlite3``
    module already loaded by their Python runtime.  A below-minimum runtime is
    represented as ``ok=False``; malformed or contradictory evidence raises.
    """

    module = sqlite_module if sqlite_module is not None else _loaded_sqlite_module()
    loaded_version = _read_loaded_version(module, make_error=make_error)
    sql_version = _query_loaded_version(module, make_error=make_error)
    if loaded_version != sql_version:
        raise make_error("remote runner SQLite runtime version sources disagree")

    return {
        "minimumVersion": REMOTE_RUNNER_SQLITE_MINIMUM_VERSION_TEXT,
        "loadedVersion": _version_text(loaded_version),
        "sqlVersion": _version_text(sql_version),
        "ok": loaded_version >= REMOTE_RUNNER_SQLITE_MINIMUM_VERSION,
    }


def require_remote_runner_sqlite_runtime(
    *,
    sqlite_module: _SqliteModule | None = None,
    make_error: _ErrorFactory = ValueError,
) -> RemoteRunnerSqliteRuntimeEvidence:
    """Return canonical evidence only when the current SQLite runtime is safe."""

    evidence = collect_remote_runner_sqlite_runtime_evidence(
        sqlite_module=sqlite_module,
        make_error=make_error,
    )
    if evidence["ok"] is not True:
        raise make_error(
            "remote runner SQLite runtime is below minimum version "
            f"{REMOTE_RUNNER_SQLITE_MINIMUM_VERSION_TEXT}"
        )
    return evidence


def require_remote_runner_sqlite_runtime_evidence(
    value: object,
    *,
    make_error: _ErrorFactory = ValueError,
) -> RemoteRunnerSqliteRuntimeEvidence:
    """Validate exact, canonical evidence for a runtime safety decision."""

    if not isinstance(value, Mapping):
        raise make_error("remote runner SQLite runtime evidence must be an object")
    if frozenset(value) != _EVIDENCE_FIELDS:
        raise make_error(
            "remote runner SQLite runtime evidence fields must match exactly"
        )

    minimum_text = value.get("minimumVersion")
    minimum_version = require_remote_runner_sqlite_version(
        minimum_text,
        field="minimumVersion",
        make_error=make_error,
    )
    if (
        minimum_text != REMOTE_RUNNER_SQLITE_MINIMUM_VERSION_TEXT
        or minimum_version != REMOTE_RUNNER_SQLITE_MINIMUM_VERSION
    ):
        raise make_error(
            "remote runner SQLite runtime evidence minimumVersion is unsupported"
        )

    loaded_text = value.get("loadedVersion")
    loaded_version = require_remote_runner_sqlite_version(
        loaded_text,
        field="loadedVersion",
        make_error=make_error,
    )
    sql_text = value.get("sqlVersion")
    sql_version = require_remote_runner_sqlite_version(
        sql_text,
        field="sqlVersion",
        make_error=make_error,
    )
    ok = value.get("ok")
    if type(ok) is not bool:
        raise make_error("remote runner SQLite runtime evidence ok must be a boolean")
    if loaded_version != sql_version:
        raise make_error("remote runner SQLite runtime evidence versions disagree")
    if loaded_version < REMOTE_RUNNER_SQLITE_MINIMUM_VERSION:
        raise make_error(
            "remote runner SQLite runtime evidence is below the minimum version"
        )
    if ok is not True:
        raise make_error("remote runner SQLite runtime evidence ok is inconsistent")

    return {
        "minimumVersion": REMOTE_RUNNER_SQLITE_MINIMUM_VERSION_TEXT,
        "loadedVersion": cast(str, loaded_text),
        "sqlVersion": cast(str, sql_text),
        "ok": True,
    }


def _loaded_sqlite_module() -> _SqliteModule:
    # Importing the module is safe on older runtimes; enforcement occurs only
    # when an explicit collect/require entry point is called.
    import sqlite3

    return cast(_SqliteModule, sqlite3)


def _read_loaded_version(
    sqlite_module: _SqliteModule,
    *,
    make_error: _ErrorFactory,
) -> _Version:
    try:
        value = sqlite_module.sqlite_version_info
    except Exception:
        raise make_error(
            "remote runner SQLite runtime sqlite_version_info is unavailable"
        ) from None
    return _require_version_tuple(
        value,
        field="sqlite_version_info",
        make_error=make_error,
    )


def _query_loaded_version(
    sqlite_module: _SqliteModule,
    *,
    make_error: _ErrorFactory,
) -> _Version:
    try:
        with closing(sqlite_module.connect(":memory:")) as connection:
            with closing(connection.execute(_SQLITE_VERSION_QUERY)) as cursor:
                row = cursor.fetchone()
    except Exception:
        raise make_error(
            "remote runner SQLite runtime SQL observation failed"
        ) from None

    if not isinstance(row, tuple) or len(row) != 1:
        raise make_error("remote runner SQLite runtime SQL result is invalid")
    return require_remote_runner_sqlite_version(
        row[0],
        field="SQL sqlite_version()",
        make_error=make_error,
    )


def _require_version_tuple(
    value: object,
    *,
    field: str,
    make_error: _ErrorFactory,
) -> _Version:
    if (
        not isinstance(value, tuple)
        or len(value) != 3
        or any(type(component) is not int for component in value)
        or any(
            component < 0 or component > _MAX_VERSION_COMPONENT for component in value
        )
    ):
        raise make_error(f"remote runner SQLite runtime {field} is invalid")
    return cast(_Version, value)


def require_remote_runner_sqlite_version(
    value: object,
    *,
    field: str = "version",
    make_error: _ErrorFactory = ValueError,
) -> _Version:
    """Parse one bounded canonical ``major.minor.patch`` SQLite version."""

    if (
        not isinstance(field, str)
        or not field
        or len(field) > 100
        or field != field.strip()
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in field)
    ):
        raise make_error("remote runner SQLite runtime version field is invalid")
    if not isinstance(value, str) or _CANONICAL_VERSION.fullmatch(value) is None:
        raise make_error(
            f"remote runner SQLite runtime {field} is not a canonical version"
        )
    components = tuple(int(component) for component in value.split("."))
    if any(component > _MAX_VERSION_COMPONENT for component in components):
        raise make_error(
            f"remote runner SQLite runtime {field} is not a canonical version"
        )
    return cast(_Version, components)


def _version_text(version: _Version) -> str:
    return ".".join(str(component) for component in version)


__all__ = [
    "REMOTE_RUNNER_SQLITE_MINIMUM_VERSION",
    "REMOTE_RUNNER_SQLITE_MINIMUM_VERSION_TEXT",
    "RemoteRunnerSqliteRuntimeEvidence",
    "collect_remote_runner_sqlite_runtime_evidence",
    "require_remote_runner_sqlite_runtime",
    "require_remote_runner_sqlite_runtime_evidence",
    "require_remote_runner_sqlite_version",
]
