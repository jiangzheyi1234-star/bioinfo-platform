from __future__ import annotations

from copy import deepcopy
import sqlite3

import pytest

from core.contracts.remote_runner_sqlite_runtime import (
    REMOTE_RUNNER_SQLITE_MINIMUM_VERSION,
    REMOTE_RUNNER_SQLITE_MINIMUM_VERSION_TEXT,
    collect_remote_runner_sqlite_runtime_evidence,
    require_remote_runner_sqlite_runtime,
    require_remote_runner_sqlite_runtime_evidence,
    require_remote_runner_sqlite_version,
)


FIELDS = {"minimumVersion", "loadedVersion", "sqlVersion", "ok"}


class SqliteContractError(RuntimeError):
    pass


class FakeCursor:
    def __init__(self, row: object, *, fetch_error: Exception | None = None) -> None:
        self.row = row
        self.fetch_error = fetch_error
        self.closed = False

    def fetchone(self) -> object:
        if self.fetch_error is not None:
            raise self.fetch_error
        return self.row

    def close(self) -> None:
        self.closed = True


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self.cursor = cursor
        self.statements: list[str] = []
        self.closed = False

    def execute(self, statement: str) -> FakeCursor:
        self.statements.append(statement)
        return self.cursor

    def close(self) -> None:
        self.closed = True


class FakeSqliteModule:
    def __init__(
        self,
        version_info: object,
        sql_result: object,
        *,
        fetch_error: Exception | None = None,
        connect_error: Exception | None = None,
    ) -> None:
        self.sqlite_version_info = version_info
        self.cursor = FakeCursor(sql_result, fetch_error=fetch_error)
        self.connection = FakeConnection(self.cursor)
        self.connect_error = connect_error
        self.databases: list[str] = []

    def connect(self, database: str, /) -> FakeConnection:
        self.databases.append(database)
        if self.connect_error is not None:
            raise self.connect_error
        return self.connection


def _module(
    version_info: object = (3, 51, 3),
    sql_version: object = "3.51.3",
    **kwargs: object,
) -> FakeSqliteModule:
    return FakeSqliteModule(version_info, (sql_version,), **kwargs)


def _safe_evidence() -> dict[str, object]:
    return {
        "minimumVersion": "3.51.3",
        "loadedVersion": "3.51.3",
        "sqlVersion": "3.51.3",
        "ok": True,
    }


def test_minimum_version_is_fixed_to_sqlite_3_51_3() -> None:
    assert REMOTE_RUNNER_SQLITE_MINIMUM_VERSION == (3, 51, 3)
    assert REMOTE_RUNNER_SQLITE_MINIMUM_VERSION_TEXT == "3.51.3"


def test_public_version_parser_returns_a_canonical_tuple() -> None:
    assert require_remote_runner_sqlite_version("3.53.0") == (3, 53, 0)


@pytest.mark.parametrize("value", [True, "03.53.0", "3.53.0 ", "3.53"])
def test_public_version_parser_rejects_noncanonical_values(value: object) -> None:
    with pytest.raises(ValueError, match="artifact sqlite is not a canonical version"):
        require_remote_runner_sqlite_version(value, field="artifact sqlite")


@pytest.mark.parametrize("field", ["", " version", "version\n", "x" * 101])
def test_public_version_parser_rejects_malformed_field_context(field: str) -> None:
    with pytest.raises(ValueError, match="version field is invalid"):
        require_remote_runner_sqlite_version("3.53.0", field=field)


def test_collect_returns_exact_canonical_non_secret_evidence() -> None:
    module = _module((3, 53, 0), "3.53.0")

    evidence = collect_remote_runner_sqlite_runtime_evidence(sqlite_module=module)

    assert evidence == {
        "minimumVersion": "3.51.3",
        "loadedVersion": "3.53.0",
        "sqlVersion": "3.53.0",
        "ok": True,
    }
    assert set(evidence) == FIELDS
    assert module.databases == [":memory:"]
    assert module.connection.statements == ["SELECT sqlite_version()"]
    assert module.cursor.closed is True
    assert module.connection.closed is True


def test_collect_exposes_below_minimum_runtime_as_negative_diagnostics() -> None:
    module = _module((3, 45, 3), "3.45.3")

    evidence = collect_remote_runner_sqlite_runtime_evidence(sqlite_module=module)

    assert evidence == {
        "minimumVersion": "3.51.3",
        "loadedVersion": "3.45.3",
        "sqlVersion": "3.45.3",
        "ok": False,
    }
    with pytest.raises(ValueError, match="below minimum version 3.51.3"):
        require_remote_runner_sqlite_runtime(sqlite_module=module)


def test_default_observation_reads_the_actual_loaded_sqlite_runtime() -> None:
    evidence = collect_remote_runner_sqlite_runtime_evidence()
    loaded = tuple(sqlite3.sqlite_version_info)

    with sqlite3.connect(":memory:") as connection:
        sql_version = connection.execute("SELECT sqlite_version()").fetchone()[0]

    assert evidence["loadedVersion"] == ".".join(str(part) for part in loaded)
    assert evidence["sqlVersion"] == sql_version
    assert evidence["ok"] is (loaded >= REMOTE_RUNNER_SQLITE_MINIMUM_VERSION)
    if evidence["ok"]:
        assert require_remote_runner_sqlite_runtime() == evidence
    else:
        with pytest.raises(ValueError, match="below minimum version 3.51.3"):
            require_remote_runner_sqlite_runtime()


@pytest.mark.parametrize(
    "version_info",
    [
        [3, 51, 3],
        (3, 51),
        (3, 51, 3, 0),
        (True, 51, 3),
        (3, False, 3),
        (3, 51, True),
        (3, 51, "3"),
        (-1, 51, 3),
        (3, 51, 2_147_483_648),
    ],
)
def test_collect_rejects_malformed_or_boolean_loaded_version_info(
    version_info: object,
) -> None:
    with pytest.raises(ValueError, match="sqlite_version_info is invalid"):
        collect_remote_runner_sqlite_runtime_evidence(
            sqlite_module=_module(version_info)
        )


@pytest.mark.parametrize(
    "sql_version",
    [
        True,
        3,
        "",
        "3.51",
        "3.51.3.0",
        "03.51.3",
        "3.051.3",
        "3.51.03",
        " 3.51.3",
        "3.51.3 ",
        "3.51.3+build",
        "3.51.-1",
        "3.51.2147483648",
        "3.51.99999999999",
    ],
)
def test_collect_rejects_noncanonical_sql_versions(sql_version: object) -> None:
    with pytest.raises(ValueError, match="not a canonical version"):
        collect_remote_runner_sqlite_runtime_evidence(
            sqlite_module=_module(sql_version=sql_version)
        )


@pytest.mark.parametrize("row", [None, (), ("3.51.3", "extra"), ["3.51.3"]])
def test_collect_rejects_malformed_sql_rows(row: object) -> None:
    module = FakeSqliteModule((3, 51, 3), row)

    with pytest.raises(ValueError, match="SQL result is invalid"):
        collect_remote_runner_sqlite_runtime_evidence(sqlite_module=module)


def test_collect_rejects_disagreement_between_same_process_sources() -> None:
    with pytest.raises(ValueError, match="version sources disagree"):
        collect_remote_runner_sqlite_runtime_evidence(
            sqlite_module=_module((3, 51, 3), "3.51.4")
        )


@pytest.mark.parametrize("failure", ["connect", "fetch"])
def test_collect_redacts_operational_failures_and_closes_resources(
    failure: str,
) -> None:
    secret = r"C:\sensitive\sqlite.dll"
    kwargs = (
        {"connect_error": RuntimeError(secret)}
        if failure == "connect"
        else {"fetch_error": RuntimeError(secret)}
    )
    module = _module(**kwargs)

    with pytest.raises(
        SqliteContractError,
        match="SQL observation failed",
    ) as captured:
        collect_remote_runner_sqlite_runtime_evidence(
            sqlite_module=module,
            make_error=SqliteContractError,
        )

    assert secret not in str(captured.value)
    if failure == "fetch":
        assert module.cursor.closed is True
        assert module.connection.closed is True


def test_require_runtime_accepts_the_exact_minimum() -> None:
    assert (
        require_remote_runner_sqlite_runtime(sqlite_module=_module())
        == _safe_evidence()
    )


def test_evidence_validator_is_exact_and_detaches_the_mapping() -> None:
    evidence = _safe_evidence()

    normalized = require_remote_runner_sqlite_runtime_evidence(evidence)

    assert normalized == evidence
    assert normalized is not evidence
    evidence["loadedVersion"] = "3.99.0"
    assert normalized["loadedVersion"] == "3.51.3"


@pytest.mark.parametrize("extra", [True, False])
def test_evidence_validator_rejects_extra_or_missing_fields(extra: bool) -> None:
    evidence = _safe_evidence()
    if extra:
        evidence["unexpected"] = "value"
    else:
        evidence.pop("sqlVersion")

    with pytest.raises(ValueError, match="fields must match exactly"):
        require_remote_runner_sqlite_runtime_evidence(evidence)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("minimumVersion", True),
        ("loadedVersion", False),
        ("sqlVersion", 35103),
        ("loadedVersion", "03.51.3"),
        ("loadedVersion", "3.051.3"),
        ("loadedVersion", "3.51.03"),
        ("sqlVersion", "3.51.3 "),
    ],
)
def test_evidence_validator_rejects_boolean_or_noncanonical_versions(
    field: str,
    value: object,
) -> None:
    evidence = _safe_evidence()
    evidence[field] = value

    with pytest.raises(ValueError, match="canonical version"):
        require_remote_runner_sqlite_runtime_evidence(evidence)


@pytest.mark.parametrize("minimum", ["3.50.0", "3.51.4", "4.0.0"])
def test_evidence_validator_rejects_an_alternate_minimum(minimum: str) -> None:
    evidence = _safe_evidence()
    evidence["minimumVersion"] = minimum

    with pytest.raises(ValueError, match="minimumVersion is unsupported"):
        require_remote_runner_sqlite_runtime_evidence(evidence)


def test_evidence_validator_rejects_mismatched_versions() -> None:
    evidence = _safe_evidence()
    evidence["sqlVersion"] = "3.51.4"

    with pytest.raises(ValueError, match="versions disagree"):
        require_remote_runner_sqlite_runtime_evidence(evidence)


@pytest.mark.parametrize("ok", [True, False])
def test_evidence_validator_rejects_below_minimum_evidence(ok: bool) -> None:
    evidence = _safe_evidence()
    evidence.update({"loadedVersion": "3.45.3", "sqlVersion": "3.45.3", "ok": ok})

    with pytest.raises(ValueError, match="below the minimum version"):
        require_remote_runner_sqlite_runtime_evidence(evidence)


@pytest.mark.parametrize("ok", [1, 0, "true", None, [], {}])
def test_evidence_validator_rejects_non_boolean_ok(ok: object) -> None:
    evidence = _safe_evidence()
    evidence["ok"] = ok

    with pytest.raises(ValueError, match="ok must be a boolean"):
        require_remote_runner_sqlite_runtime_evidence(evidence)


def test_evidence_validator_rejects_false_ok_for_a_safe_runtime() -> None:
    evidence = _safe_evidence()
    evidence["ok"] = False

    with pytest.raises(ValueError, match="ok is inconsistent"):
        require_remote_runner_sqlite_runtime_evidence(evidence)


def test_evidence_validator_uses_the_caller_error_type() -> None:
    evidence = deepcopy(_safe_evidence())
    evidence["minimumVersion"] = "3.51.4"

    with pytest.raises(SqliteContractError, match="unsupported"):
        require_remote_runner_sqlite_runtime_evidence(
            evidence,
            make_error=SqliteContractError,
        )
