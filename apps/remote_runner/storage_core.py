from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

from .config import RemoteRunnerConfig
from .sqlite_migrations import (
    DATABASE_MISSING_ERROR,
    RemoteRunnerSQLiteSchemaError,
    configure_runtime_connection,
    ensure_runtime_schema_current,
)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def get_connection(cfg: RemoteRunnerConfig) -> sqlite3.Connection:
    db_path = Path(cfg.db_path)
    if not db_path.is_file():
        raise RemoteRunnerSQLiteSchemaError(DATABASE_MISSING_ERROR)
    connection = sqlite3.connect(str(db_path), check_same_thread=False, factory=_ObservedConnection)
    connection.row_factory = sqlite3.Row
    configure_runtime_connection(connection)
    ensure_runtime_schema_current(connection)
    return connection


class _ObservedConnection(sqlite3.Connection):
    def execute(self, sql: str, parameters: Any = (), /) -> sqlite3.Cursor:
        try:
            return super().execute(sql, parameters)
        except sqlite3.OperationalError as exc:
            _record_sqlite_operational_error(exc)
            raise

    def executemany(self, sql: str, parameters: Any, /) -> sqlite3.Cursor:
        try:
            return super().executemany(sql, parameters)
        except sqlite3.OperationalError as exc:
            _record_sqlite_operational_error(exc)
            raise

    def executescript(self, sql_script: str, /) -> sqlite3.Cursor:
        try:
            return super().executescript(sql_script)
        except sqlite3.OperationalError as exc:
            _record_sqlite_operational_error(exc)
            raise


def _record_sqlite_operational_error(exc: sqlite3.OperationalError) -> None:
    message = str(exc).lower()
    if "database is locked" not in message and "database table is locked" not in message and "busy" not in message:
        return
    from .metrics import record_sqlite_busy_error

    record_sqlite_busy_error()
