from __future__ import annotations

import hashlib
import json

import pytest

from core.contracts.runner_systemd_service import (
    RUNNER_SYSTEMD_SERVICE_EVIDENCE_PROFILE,
    RUNNER_SYSTEMD_SERVICE_MANAGER,
    RUNNER_SYSTEMD_MINIMUM_VERSION,
    RUNNER_SYSTEMD_SERVICE_OBSERVATION_SCHEMA,
    RUNNER_SYSTEMD_SERVICE_SHOW_FIELDS,
    RUNNER_SYSTEMD_SERVICE_TEMPLATE_FILENAME,
    build_active_runner_systemd_service_observation,
    parse_runner_systemd_service_show,
    require_runner_systemd_service_observation,
    runner_systemd_service_observation_canonical_json,
    runner_systemd_service_observation_fingerprint,
)


ACTIVATION_ID = "0123456789abcdef0123456789abcdef"
INVOCATION_ID = "abcdef0123456789abcdef0123456789"
UNIT = f"h2ometa-remote@{ACTIVATION_ID}.service"
CONTROL_GROUP = "/user.slice/user-1000.slice/user@1000.service/app.slice/" + UNIT
FRAGMENT_PATH = "/home/researcher/.config/systemd/user/h2ometa-remote@.service"


def _show_properties() -> dict[str, str]:
    return {
        "ActiveState": "active",
        "ControlGroup": CONTROL_GROUP,
        "DropInPaths": "",
        "FragmentPath": FRAGMENT_PATH,
        "Id": UNIT,
        "InvocationID": INVOCATION_ID,
        "KillMode": "control-group",
        "LoadState": "loaded",
        "MainPID": "4242",
        "NeedDaemonReload": "no",
        "NotifyAccess": "main",
        "PIDFile": "",
        "Restart": "on-failure",
        "RestartPreventExitStatus": "73 74 75 76 77",
        "SendSIGKILL": "yes",
        "SubState": "running",
        "Type": "notify",
    }


def _show_raw(
    *,
    properties: dict[str, str] | None = None,
    order: tuple[str, ...] = RUNNER_SYSTEMD_SERVICE_SHOW_FIELDS,
    final_newline: bool = True,
) -> str:
    values = properties or _show_properties()
    raw = "\n".join(f"{field}={values[field]}" for field in order)
    return raw + ("\n" if final_newline else "")


def _observation() -> dict[str, object]:
    return build_active_runner_systemd_service_observation(_show_raw())


def test_public_constants_are_exact() -> None:
    assert RUNNER_SYSTEMD_SERVICE_OBSERVATION_SCHEMA == (
        "h2ometa.runner-systemd-user-service-observation.v1"
    )
    assert RUNNER_SYSTEMD_SERVICE_EVIDENCE_PROFILE == (
        "systemd-user-show-mainpid-invocation-cgroup-v1"
    )
    assert RUNNER_SYSTEMD_SERVICE_MANAGER == "systemd-user"
    assert RUNNER_SYSTEMD_MINIMUM_VERSION == 232
    assert RUNNER_SYSTEMD_SERVICE_TEMPLATE_FILENAME == ("h2ometa-remote@.service")
    assert RUNNER_SYSTEMD_SERVICE_SHOW_FIELDS == (
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


def test_strict_parser_accepts_exact_properties_in_any_order() -> None:
    reversed_order = tuple(reversed(RUNNER_SYSTEMD_SERVICE_SHOW_FIELDS))

    parsed = parse_runner_systemd_service_show(
        _show_raw(order=reversed_order, final_newline=False)
    )

    assert parsed == _show_properties()
    assert tuple(parsed) == RUNNER_SYSTEMD_SERVICE_SHOW_FIELDS
    assert parsed is not _show_properties()


def test_builder_returns_exact_active_user_service_observation() -> None:
    observation = _observation()

    assert observation == {
        "activationId": ACTIVATION_ID,
        "activeState": "active",
        "controlGroup": CONTROL_GROUP,
        "dropInPaths": [],
        "evidenceProfile": ("systemd-user-show-mainpid-invocation-cgroup-v1"),
        "fragmentPath": FRAGMENT_PATH,
        "invocationId": INVOCATION_ID,
        "killMode": "control-group",
        "loadState": "loaded",
        "mainPid": 4242,
        "manager": "systemd-user",
        "needDaemonReload": False,
        "notifyAccess": "main",
        "pidFile": "",
        "restart": "on-failure",
        "restartPreventExitStatus": [73, 74, 75, 76, 77],
        "schemaVersion": ("h2ometa.runner-systemd-user-service-observation.v1"),
        "sendSigkill": True,
        "subState": "running",
        "type": "notify",
        "unit": UNIT,
    }


@pytest.mark.parametrize(
    "raw",
    [
        None,
        b"Id=unit",
        "",
        "\n",
        "\n" + _show_raw(),
        _show_raw() + "\n",
        _show_raw().replace("\n", "\r\n"),
        _show_raw().replace("Id=", "Id=bad\x00", 1),
        _show_raw().replace("Id=", "Id=bad\t", 1),
        _show_raw().replace("Id=", "Id=bad\x7f", 1),
        _show_raw().replace("Id=", "Id=" + chr(0xD800), 1),
    ],
)
def test_parser_rejects_invalid_output_envelopes(raw: object) -> None:
    with pytest.raises(ValueError, match="show output is invalid|property is invalid"):
        parse_runner_systemd_service_show(raw)


@pytest.mark.parametrize(
    "line",
    [
        "not-a-property",
        "=value",
    ],
)
def test_parser_rejects_malformed_property_lines(line: str) -> None:
    with pytest.raises(ValueError, match="show line is invalid"):
        parse_runner_systemd_service_show(_show_raw() + line + "\n")


@pytest.mark.parametrize(
    "field",
    tuple(
        field
        for field in RUNNER_SYSTEMD_SERVICE_SHOW_FIELDS
        if field not in {"DropInPaths", "PIDFile"}
    ),
)
def test_parser_rejects_empty_nonempty_property_value(field: str) -> None:
    properties = _show_properties()
    properties[field] = ""

    with pytest.raises(ValueError, match=f"property is invalid: {field}"):
        parse_runner_systemd_service_show(_show_raw(properties=properties))


def test_parser_allows_empty_values_only_for_drop_ins_and_pid_file() -> None:
    parsed = parse_runner_systemd_service_show(_show_raw())

    assert parsed["DropInPaths"] == ""
    assert parsed["PIDFile"] == ""


def test_parser_rejects_duplicate_properties() -> None:
    raw = _show_raw() + f"Id={UNIT}\n"

    with pytest.raises(ValueError, match="property is duplicated: Id"):
        parse_runner_systemd_service_show(raw)


def test_parser_rejects_unknown_properties() -> None:
    raw = _show_raw() + "Description=H2OMeta Remote Runner\n"

    with pytest.raises(ValueError, match="property is unexpected: Description"):
        parse_runner_systemd_service_show(raw)


@pytest.mark.parametrize("missing", RUNNER_SYSTEMD_SERVICE_SHOW_FIELDS)
def test_parser_rejects_every_missing_property(missing: str) -> None:
    properties = _show_properties()
    properties.pop(missing)
    order = tuple(
        field for field in RUNNER_SYSTEMD_SERVICE_SHOW_FIELDS if field != missing
    )

    with pytest.raises(ValueError, match="properties must match exactly"):
        parse_runner_systemd_service_show(_show_raw(properties=properties, order=order))


@pytest.mark.parametrize(
    "unit",
    [
        "h2ometa-remote.service",
        "h2ometa-remote@.service",
        "h2ometa-remote@" + "0" * 31 + ".service",
        "h2ometa-remote@" + "0" * 33 + ".service",
        "h2ometa-remote@" + "A" * 32 + ".service",
        "other-remote@" + "0" * 32 + ".service",
        "h2ometa-remote@" + "g" * 32 + ".service",
        "h2ometa-remote@" + "0" * 32 + ".timer",
    ],
)
def test_parser_requires_unique_canonical_runner_unit(unit: str) -> None:
    properties = _show_properties()
    properties["Id"] = unit

    with pytest.raises(ValueError, match="unit is invalid"):
        parse_runner_systemd_service_show(_show_raw(properties=properties))


@pytest.mark.parametrize(
    "invocation_id",
    [
        "",
        "0" * 31,
        "0" * 33,
        "A" * 32,
        "g" * 32,
        "00000000-0000-0000-0000-000000000000",
    ],
)
def test_parser_requires_canonical_invocation_id(invocation_id: str) -> None:
    properties = _show_properties()
    properties["InvocationID"] = invocation_id

    with pytest.raises(ValueError, match="InvocationID|show line is invalid"):
        parse_runner_systemd_service_show(_show_raw(properties=properties))


@pytest.mark.parametrize(
    "main_pid",
    ["", "0", "-1", "+1", "01", " 1", "1 ", "1.0", "true"],
)
def test_parser_requires_canonical_positive_main_pid(main_pid: str) -> None:
    properties = _show_properties()
    properties["MainPID"] = main_pid

    with pytest.raises(ValueError, match="MainPID|show line is invalid"):
        parse_runner_systemd_service_show(_show_raw(properties=properties))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ActiveState", "activating"),
        ("ActiveState", "inactive"),
        ("SubState", "start-pre"),
        ("SubState", "exited"),
        ("LoadState", "not-found"),
        ("LoadState", "error"),
        ("NeedDaemonReload", "yes"),
        ("NeedDaemonReload", "false"),
    ],
)
def test_parser_requires_exact_active_running_loaded_state(
    field: str,
    value: str,
) -> None:
    properties = _show_properties()
    properties[field] = value

    with pytest.raises(ValueError, match=f"{field}|property is invalid"):
        parse_runner_systemd_service_show(_show_raw(properties=properties))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("DropInPaths", "/etc/systemd/user/h2ometa-remote@.service.d/override.conf"),
        ("Type", "simple"),
        ("Type", "forking"),
        ("NotifyAccess", "all"),
        ("NotifyAccess", "none"),
        ("KillMode", "process"),
        ("KillMode", "mixed"),
        ("SendSIGKILL", "no"),
        ("SendSIGKILL", "true"),
        ("PIDFile", "/run/user/1000/h2ometa.pid"),
        ("Restart", "no"),
        ("Restart", "always"),
        ("RestartPreventExitStatus", "73 74 75 76"),
        ("RestartPreventExitStatus", "73 74 75 76 77 78"),
        ("RestartPreventExitStatus", "77 76 75 74 73"),
        ("RestartPreventExitStatus", "EX_CANTCREAT EX_IOERR EX_TEMPFAIL"),
    ],
)
def test_parser_requires_exact_effective_service_semantics(
    field: str,
    value: str,
) -> None:
    properties = _show_properties()
    properties[field] = value

    with pytest.raises(ValueError, match=field):
        parse_runner_systemd_service_show(_show_raw(properties=properties))


@pytest.mark.parametrize(
    "path",
    [
        "",
        "relative/path",
        "C:/runner/path",
        "//server/share",
        "/user.slice/../escape",
        "/user.slice//double",
        "/user.slice/./dot",
        "/user.slice/trailing/",
        "/user.slice\\windows",
        "/user.slice/" + chr(0xD800),
        "/user.slice/bad\x00path",
    ],
)
@pytest.mark.parametrize("field", ["ControlGroup", "FragmentPath"])
def test_parser_rejects_noncanonical_absolute_paths(
    field: str,
    path: str,
) -> None:
    properties = _show_properties()
    properties[field] = path

    with pytest.raises(ValueError, match=field):
        parse_runner_systemd_service_show(_show_raw(properties=properties))


def test_parser_binds_control_group_to_unique_unit() -> None:
    properties = _show_properties()
    properties["ControlGroup"] = (
        "/user.slice/user-1000.slice/user@1000.service/app.slice/"
        "h2ometa-remote@ffffffffffffffffffffffffffffffff.service"
    )

    with pytest.raises(ValueError, match="ControlGroup does not match Id"):
        parse_runner_systemd_service_show(_show_raw(properties=properties))


def test_fragment_path_may_be_a_canonical_template_unit_path() -> None:
    properties = _show_properties()
    properties["FragmentPath"] = (
        "/home/researcher/units=production/h2ometa-remote@.service"
    )

    observation = build_active_runner_systemd_service_observation(
        _show_raw(properties=properties)
    )

    assert observation["fragmentPath"] == properties["FragmentPath"]


@pytest.mark.parametrize(
    "filename",
    [
        UNIT,
        "h2ometa-remote.service",
        "other-remote@.service",
    ],
)
def test_parser_requires_static_template_fragment_filename(filename: str) -> None:
    properties = _show_properties()
    properties["FragmentPath"] = f"/etc/systemd/user/{filename}"

    with pytest.raises(ValueError, match="FragmentPath is not the template"):
        parse_runner_systemd_service_show(_show_raw(properties=properties))


def test_parser_rejects_oversized_output() -> None:
    raw = _show_raw() + ("x" * (64 * 1024))

    with pytest.raises(ValueError, match="show output is invalid"):
        parse_runner_systemd_service_show(raw)


def test_parser_rejects_oversized_line() -> None:
    properties = _show_properties()
    properties["FragmentPath"] = "/" + ("x" * (8 * 1024))

    with pytest.raises(ValueError, match="show line is invalid"):
        parse_runner_systemd_service_show(_show_raw(properties=properties))


def test_parser_rejects_oversized_path_before_line_limit() -> None:
    properties = _show_properties()
    properties["FragmentPath"] = "/" + ("x" * 4096)

    with pytest.raises(ValueError, match="FragmentPath is invalid"):
        parse_runner_systemd_service_show(_show_raw(properties=properties))


def test_require_observation_returns_detached_normalized_copy() -> None:
    observation = _observation()

    normalized = require_runner_systemd_service_observation(observation)

    assert normalized == observation
    assert normalized is not observation
    assert normalized["dropInPaths"] is not observation["dropInPaths"]
    assert (
        normalized["restartPreventExitStatus"]
        is not observation["restartPreventExitStatus"]
    )


@pytest.mark.parametrize("field", sorted(_observation()))
def test_require_observation_rejects_every_missing_field(field: str) -> None:
    observation = _observation()
    observation.pop(field)

    with pytest.raises(ValueError, match="fields must match exactly"):
        require_runner_systemd_service_observation(observation)


def test_require_observation_rejects_unknown_fields() -> None:
    observation = _observation()
    observation["authenticated"] = True

    with pytest.raises(ValueError, match="fields must match exactly"):
        require_runner_systemd_service_observation(observation)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("schemaVersion", "h2ometa.runner-systemd-user-service-observation.v2"),
        ("evidenceProfile", "systemd-authenticated-identity-v1"),
        ("manager", "systemd-system"),
        ("activeState", "inactive"),
        ("subState", "exited"),
        ("loadState", "not-found"),
        ("needDaemonReload", True),
        ("needDaemonReload", 0),
        ("type", "simple"),
        ("notifyAccess", "all"),
        ("killMode", "process"),
        ("sendSigkill", False),
        ("sendSigkill", 1),
        ("pidFile", "/run/user/1000/h2ometa.pid"),
        ("restart", "always"),
        ("invocationId", "A" * 32),
        ("mainPid", True),
        ("mainPid", 0),
        ("mainPid", "4242"),
    ],
)
def test_require_observation_rejects_invalid_scalar_values(
    field: str,
    replacement: object,
) -> None:
    observation = _observation()
    observation[field] = replacement

    with pytest.raises(ValueError, match=field):
        require_runner_systemd_service_observation(observation)


@pytest.mark.parametrize(
    "replacement",
    [
        None,
        "",
        (),
        ["/etc/systemd/user/h2ometa-remote@.service.d/override.conf"],
    ],
)
def test_require_observation_requires_empty_drop_in_paths(
    replacement: object,
) -> None:
    observation = _observation()
    observation["dropInPaths"] = replacement

    with pytest.raises(ValueError, match="dropInPaths"):
        require_runner_systemd_service_observation(observation)


@pytest.mark.parametrize(
    "replacement",
    [
        None,
        "73 74 75 76 77",
        (73, 74, 75, 76, 77),
        [73, 74, 75, 76],
        [73, 74, 75, 76, 77, 78],
        [77, 76, 75, 74, 73],
        [73, 74, 75, 76, True],
    ],
)
def test_require_observation_requires_exact_restart_prevent_statuses(
    replacement: object,
) -> None:
    observation = _observation()
    observation["restartPreventExitStatus"] = replacement

    with pytest.raises(ValueError, match="restartPreventExitStatus"):
        require_runner_systemd_service_observation(observation)


def test_require_observation_binds_activation_id_to_unit() -> None:
    observation = _observation()
    observation["activationId"] = "f" * 32

    with pytest.raises(ValueError, match="activationId does not match unit"):
        require_runner_systemd_service_observation(observation)


def test_require_observation_rejects_non_template_fragment_filename() -> None:
    observation = _observation()
    observation["fragmentPath"] = f"/etc/systemd/user/{UNIT}"

    with pytest.raises(ValueError, match="fragmentPath is not the template"):
        require_runner_systemd_service_observation(observation)


def test_require_observation_rejects_del_in_path() -> None:
    observation = _observation()
    observation["fragmentPath"] = "/etc/systemd/user/bad\x7f.service"

    with pytest.raises(ValueError, match="fragmentPath is invalid"):
        require_runner_systemd_service_observation(observation)


def test_observation_validation_uses_requested_error_factory() -> None:
    class ObservationError(RuntimeError):
        pass

    with pytest.raises(ObservationError, match="wrapped: runner systemd"):
        build_active_runner_systemd_service_observation(
            "invalid",
            make_error=lambda message: ObservationError(f"wrapped: {message}"),
        )


def test_canonical_json_and_fingerprint_are_stable_and_domain_separated() -> None:
    observation = _observation()
    reordered = dict(reversed(tuple(observation.items())))

    canonical = runner_systemd_service_observation_canonical_json(reordered)
    expected_fingerprint = hashlib.sha256(
        b"h2ometa.runner-systemd-user-service-observation.v1\x00"
        + canonical.encode("utf-8")
    ).hexdigest()

    assert canonical == json.dumps(
        observation,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    assert " " not in canonical
    assert "\n" not in canonical
    assert runner_systemd_service_observation_canonical_json(observation) == canonical
    assert runner_systemd_service_observation_fingerprint(observation) == (
        f"sha256:{expected_fingerprint}"
    )
    assert len(runner_systemd_service_observation_fingerprint(observation)) == 71


def test_fingerprint_revalidates_payload_before_hashing() -> None:
    observation = _observation()
    observation["unit"] = "h2ometa-remote.service"

    with pytest.raises(ValueError, match="unit is invalid"):
        runner_systemd_service_observation_fingerprint(observation)
