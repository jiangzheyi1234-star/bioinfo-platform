"""Strict controller observation of one active runner systemd user service.

This contract normalizes the point-in-time result of a controller-issued
``systemctl --user show`` probe.  It is useful only when correlated with other
activation, procfs, process-owner, and readiness evidence.  The observation is
not independently authenticated and is not, by itself, proof of process
identity, authorization, liveness, listener ownership, or exclusive control.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import json
from pathlib import PurePosixPath
import re


RUNNER_SYSTEMD_SERVICE_OBSERVATION_SCHEMA = (
    "h2ometa.runner-systemd-user-service-observation.v1"
)
RUNNER_SYSTEMD_SERVICE_EVIDENCE_PROFILE = (
    "systemd-user-show-mainpid-invocation-cgroup-v1"
)
RUNNER_SYSTEMD_SERVICE_MANAGER = "systemd-user"
RUNNER_SYSTEMD_MINIMUM_VERSION = 232
RUNNER_SYSTEMD_SERVICE_TEMPLATE_FILENAME = "h2ometa-remote@.service"
RUNNER_SYSTEMD_SERVICE_SHOW_FIELDS = (
    "ActiveState",
    "ControlGroup",
    "DropInPaths",
    "FragmentPath",
    "Id",
    "InvocationID",
    "KillMode",
    "LoadState",
    "MainPID",
    "NeedDaemonReload",
    "NotifyAccess",
    "PIDFile",
    "Restart",
    "RestartPreventExitStatus",
    "SendSIGKILL",
    "SubState",
    "Type",
)

_OBSERVATION_FIELDS = frozenset(
    {
        "activationId",
        "activeState",
        "controlGroup",
        "dropInPaths",
        "evidenceProfile",
        "fragmentPath",
        "invocationId",
        "killMode",
        "loadState",
        "mainPid",
        "manager",
        "needDaemonReload",
        "notifyAccess",
        "pidFile",
        "restart",
        "restartPreventExitStatus",
        "schemaVersion",
        "sendSigkill",
        "subState",
        "type",
        "unit",
    }
)
_SHOW_FIELD_SET = frozenset(RUNNER_SYSTEMD_SERVICE_SHOW_FIELDS)
_EMPTY_SHOW_FIELDS = frozenset({"DropInPaths", "PIDFile"})
_RESTART_PREVENT_EXIT_STATUSES = (73, 74, 75, 76, 77)
_RESTART_PREVENT_EXIT_STATUS_SHOW = "73 74 75 76 77"
_ACTIVATION_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_INVOCATION_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_UNIT_PATTERN = re.compile(
    r"^h2ometa-remote@(?P<activation_id>[0-9a-f]{32})[.]service$"
)
_FINGERPRINT_DOMAIN = RUNNER_SYSTEMD_SERVICE_OBSERVATION_SCHEMA.encode("ascii")
_MAX_SYSTEMD_SHOW_OUTPUT_BYTES = 64 * 1024
_MAX_SYSTEMD_SHOW_LINE_BYTES = 8 * 1024
_MAX_SYSTEMD_PATH_BYTES = 4096


def parse_runner_systemd_service_show(
    raw: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, str]:
    """Parse and validate the exact expected ``systemctl show`` properties."""

    if not isinstance(raw, str) or not raw or "\x7f" in raw:
        raise make_error("runner systemd service show output is invalid")
    if (
        len(raw.encode("utf-8", errors="surrogatepass"))
        > _MAX_SYSTEMD_SHOW_OUTPUT_BYTES
    ):
        raise make_error("runner systemd service show output is invalid")
    if "\r" in raw:
        raise make_error("runner systemd service show output is invalid")
    lines = raw.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not lines or any(not line for line in lines):
        raise make_error("runner systemd service show output is invalid")

    properties: dict[str, str] = {}
    for line in lines:
        if (
            len(line.encode("utf-8", errors="surrogatepass"))
            > _MAX_SYSTEMD_SHOW_LINE_BYTES
        ):
            raise make_error("runner systemd service show line is invalid")
        key, separator, value = line.partition("=")
        if not separator or not key:
            raise make_error("runner systemd service show line is invalid")
        if key not in _SHOW_FIELD_SET:
            raise make_error(
                f"runner systemd service show property is unexpected: {key}"
            )
        if key in properties:
            raise make_error(
                f"runner systemd service show property is duplicated: {key}"
            )
        if (
            (not value and key not in _EMPTY_SHOW_FIELDS)
            or _contains_surrogate(value)
            or any(
                ord(character) < 0x20 or ord(character) == 0x7F for character in value
            )
        ):
            raise make_error(f"runner systemd service show property is invalid: {key}")
        properties[key] = value

    if frozenset(properties) != _SHOW_FIELD_SET:
        raise make_error("runner systemd service show properties must match exactly")
    _normalize_show_properties(properties, make_error=make_error)
    return {field: properties[field] for field in RUNNER_SYSTEMD_SERVICE_SHOW_FIELDS}


def build_active_runner_systemd_service_observation(
    raw: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, object]:
    """Build one exact active-service observation from strict show output."""

    properties = parse_runner_systemd_service_show(raw, make_error=make_error)
    normalized = _normalize_show_properties(properties, make_error=make_error)
    return require_runner_systemd_service_observation(
        {
            "activationId": normalized["activationId"],
            "activeState": "active",
            "controlGroup": normalized["controlGroup"],
            "dropInPaths": normalized["dropInPaths"],
            "evidenceProfile": RUNNER_SYSTEMD_SERVICE_EVIDENCE_PROFILE,
            "fragmentPath": normalized["fragmentPath"],
            "invocationId": normalized["invocationId"],
            "killMode": normalized["killMode"],
            "loadState": "loaded",
            "mainPid": normalized["mainPid"],
            "manager": RUNNER_SYSTEMD_SERVICE_MANAGER,
            "needDaemonReload": False,
            "notifyAccess": normalized["notifyAccess"],
            "pidFile": normalized["pidFile"],
            "restart": normalized["restart"],
            "restartPreventExitStatus": normalized["restartPreventExitStatus"],
            "schemaVersion": RUNNER_SYSTEMD_SERVICE_OBSERVATION_SCHEMA,
            "sendSigkill": normalized["sendSigkill"],
            "subState": "running",
            "type": normalized["type"],
            "unit": normalized["unit"],
        },
        make_error=make_error,
    )


def require_runner_systemd_service_observation(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, object]:
    """Validate an exact observation payload and return a detached copy."""

    if not isinstance(payload, Mapping):
        raise make_error("runner systemd service observation must be an object")
    if frozenset(payload.keys()) != _OBSERVATION_FIELDS:
        raise make_error("runner systemd service observation fields must match exactly")
    _require_exact_string(
        payload.get("schemaVersion"),
        expected=RUNNER_SYSTEMD_SERVICE_OBSERVATION_SCHEMA,
        field="schemaVersion",
        make_error=make_error,
    )
    _require_exact_string(
        payload.get("evidenceProfile"),
        expected=RUNNER_SYSTEMD_SERVICE_EVIDENCE_PROFILE,
        field="evidenceProfile",
        make_error=make_error,
    )
    _require_exact_string(
        payload.get("manager"),
        expected=RUNNER_SYSTEMD_SERVICE_MANAGER,
        field="manager",
        make_error=make_error,
    )
    activation_id = _require_pattern_string(
        payload.get("activationId"),
        pattern=_ACTIVATION_ID_PATTERN,
        field="activationId",
        make_error=make_error,
    )
    unit, unit_activation_id = _require_unique_runner_unit(
        payload.get("unit"),
        make_error,
    )
    if unit_activation_id != activation_id:
        raise make_error(
            "runner systemd service observation activationId does not match unit"
        )
    invocation_id = _require_pattern_string(
        payload.get("invocationId"),
        pattern=_INVOCATION_ID_PATTERN,
        field="invocationId",
        make_error=make_error,
    )
    main_pid = _require_positive_integer(
        payload.get("mainPid"),
        field="mainPid",
        make_error=make_error,
    )
    _require_exact_string(
        payload.get("activeState"),
        expected="active",
        field="activeState",
        make_error=make_error,
    )
    _require_exact_string(
        payload.get("subState"),
        expected="running",
        field="subState",
        make_error=make_error,
    )
    _require_exact_string(
        payload.get("loadState"),
        expected="loaded",
        field="loadState",
        make_error=make_error,
    )
    _require_exact_string(
        payload.get("type"),
        expected="notify",
        field="type",
        make_error=make_error,
    )
    _require_exact_string(
        payload.get("notifyAccess"),
        expected="main",
        field="notifyAccess",
        make_error=make_error,
    )
    _require_exact_string(
        payload.get("killMode"),
        expected="control-group",
        field="killMode",
        make_error=make_error,
    )
    if payload.get("sendSigkill") is not True:
        raise make_error("runner systemd service observation sendSigkill is invalid")
    drop_in_paths = _require_empty_list(
        payload.get("dropInPaths"),
        field="dropInPaths",
        make_error=make_error,
    )
    _require_exact_string(
        payload.get("pidFile"),
        expected="",
        field="pidFile",
        make_error=make_error,
    )
    _require_exact_string(
        payload.get("restart"),
        expected="on-failure",
        field="restart",
        make_error=make_error,
    )
    restart_prevent_exit_status = _require_exact_integer_list(
        payload.get("restartPreventExitStatus"),
        expected=_RESTART_PREVENT_EXIT_STATUSES,
        field="restartPreventExitStatus",
        make_error=make_error,
    )
    if payload.get("needDaemonReload") is not False:
        raise make_error(
            "runner systemd service observation needDaemonReload is invalid"
        )
    control_group = _require_canonical_absolute_posix_path(
        payload.get("controlGroup"),
        field="controlGroup",
        make_error=make_error,
    )
    if PurePosixPath(control_group).name != unit:
        raise make_error(
            "runner systemd service observation controlGroup does not match unit"
        )
    fragment_path = _require_canonical_absolute_posix_path(
        payload.get("fragmentPath"),
        field="fragmentPath",
        make_error=make_error,
    )
    if PurePosixPath(fragment_path).name != RUNNER_SYSTEMD_SERVICE_TEMPLATE_FILENAME:
        raise make_error(
            "runner systemd service observation fragmentPath is not the template"
        )
    return {
        "activationId": activation_id,
        "activeState": "active",
        "controlGroup": control_group,
        "dropInPaths": drop_in_paths,
        "evidenceProfile": RUNNER_SYSTEMD_SERVICE_EVIDENCE_PROFILE,
        "fragmentPath": fragment_path,
        "invocationId": invocation_id,
        "killMode": "control-group",
        "loadState": "loaded",
        "mainPid": main_pid,
        "manager": RUNNER_SYSTEMD_SERVICE_MANAGER,
        "needDaemonReload": False,
        "notifyAccess": "main",
        "pidFile": "",
        "restart": "on-failure",
        "restartPreventExitStatus": restart_prevent_exit_status,
        "schemaVersion": RUNNER_SYSTEMD_SERVICE_OBSERVATION_SCHEMA,
        "sendSigkill": True,
        "subState": "running",
        "type": "notify",
        "unit": unit,
    }


def runner_systemd_service_observation_canonical_json(payload: object) -> str:
    """Return stable canonical JSON for a valid controller observation."""

    normalized = require_runner_systemd_service_observation(payload)
    return json.dumps(
        normalized,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def runner_systemd_service_observation_fingerprint(payload: object) -> str:
    """Return a domain-separated fingerprint for a valid observation."""

    canonical = runner_systemd_service_observation_canonical_json(payload)
    digest = hashlib.sha256(
        _FINGERPRINT_DOMAIN + b"\x00" + canonical.encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"


def _normalize_show_properties(
    properties: Mapping[str, str],
    *,
    make_error: Callable[[str], Exception],
) -> dict[str, object]:
    unit, activation_id = _require_unique_runner_unit(
        properties.get("Id"),
        make_error,
    )
    invocation_id = _require_pattern_string(
        properties.get("InvocationID"),
        pattern=_INVOCATION_ID_PATTERN,
        field="InvocationID",
        make_error=make_error,
    )
    main_pid = _parse_canonical_positive_integer(
        properties.get("MainPID"),
        field="MainPID",
        make_error=make_error,
    )
    _require_show_value(
        properties,
        field="ActiveState",
        expected="active",
        make_error=make_error,
    )
    _require_show_value(
        properties,
        field="SubState",
        expected="running",
        make_error=make_error,
    )
    _require_show_value(
        properties,
        field="LoadState",
        expected="loaded",
        make_error=make_error,
    )
    _require_show_value(
        properties,
        field="NeedDaemonReload",
        expected="no",
        make_error=make_error,
    )
    _require_show_value(
        properties,
        field="DropInPaths",
        expected="",
        make_error=make_error,
    )
    _require_show_value(
        properties,
        field="Type",
        expected="notify",
        make_error=make_error,
    )
    _require_show_value(
        properties,
        field="NotifyAccess",
        expected="main",
        make_error=make_error,
    )
    _require_show_value(
        properties,
        field="KillMode",
        expected="control-group",
        make_error=make_error,
    )
    _require_show_value(
        properties,
        field="SendSIGKILL",
        expected="yes",
        make_error=make_error,
    )
    _require_show_value(
        properties,
        field="PIDFile",
        expected="",
        make_error=make_error,
    )
    _require_show_value(
        properties,
        field="Restart",
        expected="on-failure",
        make_error=make_error,
    )
    _require_show_value(
        properties,
        field="RestartPreventExitStatus",
        expected=_RESTART_PREVENT_EXIT_STATUS_SHOW,
        make_error=make_error,
    )
    control_group = _require_canonical_absolute_posix_path(
        properties.get("ControlGroup"),
        field="ControlGroup",
        make_error=make_error,
    )
    if PurePosixPath(control_group).name != unit:
        raise make_error("runner systemd service show ControlGroup does not match Id")
    fragment_path = _require_canonical_absolute_posix_path(
        properties.get("FragmentPath"),
        field="FragmentPath",
        make_error=make_error,
    )
    if PurePosixPath(fragment_path).name != RUNNER_SYSTEMD_SERVICE_TEMPLATE_FILENAME:
        raise make_error("runner systemd service show FragmentPath is not the template")
    return {
        "activationId": activation_id,
        "controlGroup": control_group,
        "dropInPaths": [],
        "fragmentPath": fragment_path,
        "invocationId": invocation_id,
        "killMode": "control-group",
        "mainPid": main_pid,
        "notifyAccess": "main",
        "pidFile": "",
        "restart": "on-failure",
        "restartPreventExitStatus": list(_RESTART_PREVENT_EXIT_STATUSES),
        "sendSigkill": True,
        "type": "notify",
        "unit": unit,
    }


def _require_unique_runner_unit(
    value: object,
    make_error: Callable[[str], Exception],
) -> tuple[str, str]:
    if not isinstance(value, str):
        raise make_error("runner systemd service unit is invalid")
    match = _UNIT_PATTERN.fullmatch(value)
    if match is None:
        raise make_error("runner systemd service unit is invalid")
    return value, match.group("activation_id")


def _require_show_value(
    properties: Mapping[str, str],
    *,
    field: str,
    expected: str,
    make_error: Callable[[str], Exception],
) -> None:
    if properties.get(field) != expected:
        raise make_error(f"runner systemd service show {field} is invalid")


def _parse_canonical_positive_integer(
    value: object,
    *,
    field: str,
    make_error: Callable[[str], Exception],
) -> int:
    if (
        not isinstance(value, str)
        or not value.isascii()
        or not value.isdecimal()
        or (len(value) > 1 and value.startswith("0"))
    ):
        raise make_error(f"runner systemd service show {field} is invalid")
    parsed = int(value)
    if parsed <= 0 or str(parsed) != value:
        raise make_error(f"runner systemd service show {field} is invalid")
    return parsed


def _require_positive_integer(
    value: object,
    *,
    field: str,
    make_error: Callable[[str], Exception],
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise make_error(f"runner systemd service observation {field} is invalid")
    return value


def _require_pattern_string(
    value: object,
    *,
    pattern: re.Pattern[str],
    field: str,
    make_error: Callable[[str], Exception],
) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise make_error(f"runner systemd service observation {field} is invalid")
    return value


def _require_exact_string(
    value: object,
    *,
    expected: str,
    field: str,
    make_error: Callable[[str], Exception],
) -> None:
    if not isinstance(value, str) or value != expected:
        raise make_error(f"runner systemd service observation {field} is invalid")


def _require_empty_list(
    value: object,
    *,
    field: str,
    make_error: Callable[[str], Exception],
) -> list[object]:
    if not isinstance(value, list) or value:
        raise make_error(f"runner systemd service observation {field} is invalid")
    return []


def _require_exact_integer_list(
    value: object,
    *,
    expected: tuple[int, ...],
    field: str,
    make_error: Callable[[str], Exception],
) -> list[int]:
    if (
        not isinstance(value, list)
        or any(isinstance(item, bool) or not isinstance(item, int) for item in value)
        or value != list(expected)
    ):
        raise make_error(f"runner systemd service observation {field} is invalid")
    return list(expected)


def _require_canonical_absolute_posix_path(
    value: object,
    *,
    field: str,
    make_error: Callable[[str], Exception],
) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or _contains_surrogate(value)
    ):
        raise make_error(f"runner systemd service {field} is invalid")
    if len(value.encode("utf-8")) > _MAX_SYSTEMD_PATH_BYTES or any(
        ord(character) < 0x20 or ord(character) == 0x7F for character in value
    ):
        raise make_error(f"runner systemd service {field} is invalid")
    path = PurePosixPath(value)
    if (
        not path.is_absolute()
        or value.startswith("//")
        or str(path) != value
        or ".." in path.parts
    ):
        raise make_error(f"runner systemd service {field} is invalid")
    return value


def _contains_surrogate(value: str) -> bool:
    return any(0xD800 <= ord(character) <= 0xDFFF for character in value)


__all__ = [
    "RUNNER_SYSTEMD_SERVICE_EVIDENCE_PROFILE",
    "RUNNER_SYSTEMD_SERVICE_MANAGER",
    "RUNNER_SYSTEMD_MINIMUM_VERSION",
    "RUNNER_SYSTEMD_SERVICE_OBSERVATION_SCHEMA",
    "RUNNER_SYSTEMD_SERVICE_SHOW_FIELDS",
    "RUNNER_SYSTEMD_SERVICE_TEMPLATE_FILENAME",
    "build_active_runner_systemd_service_observation",
    "parse_runner_systemd_service_show",
    "require_runner_systemd_service_observation",
    "runner_systemd_service_observation_canonical_json",
    "runner_systemd_service_observation_fingerprint",
]
