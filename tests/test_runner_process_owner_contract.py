from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

from core.contracts.linux_process_incarnation import (
    build_linux_process_incarnation,
)
from core.contracts.runner_process_lifetime import (
    RUNNER_PROCESS_LIFETIME_LOCK_PROFILE,
)
from core.contracts.runner_process_owner import (
    RUNNER_PROCESS_OWNER_CONFIGURED_MODES,
    RUNNER_PROCESS_OWNER_DIRECTORY_NAME,
    RUNNER_PROCESS_OWNER_FINGERPRINT_ENV,
    RUNNER_PROCESS_OWNER_LAUNCH_ID_ENV,
    RUNNER_PROCESS_OWNER_PHASE,
    RUNNER_PROCESS_OWNER_POINTER_FILENAME,
    RUNNER_PROCESS_OWNER_PROFILE,
    RUNNER_PROCESS_OWNER_REFERENCE_SCHEMA,
    RUNNER_PROCESS_OWNER_SCHEMA,
    RUNNER_PROCESS_OWNER_SERVICE,
    RUNNER_PROCESS_OWNER_UNAVAILABLE_EXIT_STATUS,
    build_runner_process_owner,
    build_runner_process_owner_reference,
    require_runner_process_owner,
    require_runner_process_owner_reference,
    runner_process_owner_canonical_json,
    runner_process_owner_fingerprint,
)


LAUNCH_ID = "0123456789abcdef0123456789abcdef"
EXPECTED_OWNER_CANONICAL = (
    '{"launchId":"0123456789abcdef0123456789abcdef",'
    '"lifetimeLock":{"device":2049,"inode":98765,'
    '"path":"/opt/h2ometa/shared/runtime/runner.lock",'
    '"profile":"linux-flock-cooperating-single-instance-v1"},'
    '"phase":"launcher-preparation","processIncarnation":{'
    '"bootId":"12345678-90ab-cdef-1234-567890abcdef",'
    '"evidenceProfile":"linux-procfs-boot-id-pid-starttime-v1",'
    '"pid":4242,"procStartTicks":987654,'
    '"schemaVersion":"h2ometa.linux-process-incarnation.v1"},'
    '"profile":"linux-procfs-flock-startup-binding-v1",'
    '"schemaVersion":"h2ometa.runner-process-owner.v1",'
    '"startupBinding":{"artifactArchiveSha256Path":'
    '"/opt/h2ometa/releases/0.2.0.tar.gz.sha256",'
    '"bootstrapManifestFingerprint":"sha256:'
    + "4" * 64
    + '","bootstrapManifestPath":'
    '"/opt/h2ometa/releases/bootstrap_manifest.json",'
    '"configPath":"/opt/h2ometa/shared/config/runner.json",'
    '"configuredMode":"systemd_user",'
    '"declaredArtifactArchiveSha256":"sha256:'
    + "5" * 64
    + '","effectiveConfigFingerprint":"sha256:'
    + "2" * 64
    + '","packagePath":"/opt/h2ometa/releases/remote_runner",'
    '"persistedConfigFingerprint":"sha256:'
    + "1" * 64
    + '","protocolFingerprint":"sha256:'
    + "3" * 64
    + '","protocolVersion":"runner-protocol.v5",'
    '"runnerPythonPath":"/opt/h2ometa/releases/runtime/bin/python",'
    '"service":"h2ometa-remote","version":"0.2.0-control-plane"}}'
)


def _process_incarnation() -> dict[str, object]:
    return build_linux_process_incarnation(
        boot_id="12345678-90ab-cdef-1234-567890abcdef",
        pid=4242,
        proc_start_ticks=987654,
    )


def _startup_binding() -> dict[str, object]:
    return {
        "artifactArchiveSha256Path": "/opt/h2ometa/releases/0.2.0.tar.gz.sha256",
        "bootstrapManifestFingerprint": "sha256:" + "4" * 64,
        "bootstrapManifestPath": "/opt/h2ometa/releases/bootstrap_manifest.json",
        "configPath": "/opt/h2ometa/shared/config/runner.json",
        "configuredMode": "systemd_user",
        "declaredArtifactArchiveSha256": "sha256:" + "5" * 64,
        "effectiveConfigFingerprint": "sha256:" + "2" * 64,
        "packagePath": "/opt/h2ometa/releases/remote_runner",
        "persistedConfigFingerprint": "sha256:" + "1" * 64,
        "protocolFingerprint": "sha256:" + "3" * 64,
        "protocolVersion": "runner-protocol.v5",
        "runnerPythonPath": "/opt/h2ometa/releases/runtime/bin/python",
        "service": "h2ometa-remote",
        "version": "0.2.0-control-plane",
    }


def _lifetime_lock() -> dict[str, object]:
    return {
        "device": 2049,
        "inode": 98765,
        "path": "/opt/h2ometa/shared/runtime/runner.lock",
        "profile": RUNNER_PROCESS_LIFETIME_LOCK_PROFILE,
    }


def _owner() -> dict[str, object]:
    return build_runner_process_owner(
        launch_id=LAUNCH_ID,
        process_incarnation=_process_incarnation(),
        startup_binding=_startup_binding(),
        lifetime_lock=_lifetime_lock(),
    )


def test_runner_process_owner_public_constants_are_exact() -> None:
    assert RUNNER_PROCESS_OWNER_SCHEMA == "h2ometa.runner-process-owner.v1"
    assert (
        RUNNER_PROCESS_OWNER_PROFILE
        == "linux-procfs-flock-startup-binding-v1"
    )
    assert RUNNER_PROCESS_OWNER_REFERENCE_SCHEMA == (
        "h2ometa.runner-process-owner-reference.v1"
    )
    assert RUNNER_PROCESS_OWNER_PHASE == "launcher-preparation"
    assert RUNNER_PROCESS_OWNER_SERVICE == "h2ometa-remote"
    assert RUNNER_PROCESS_OWNER_CONFIGURED_MODES == (
        "background_process",
        "systemd_user",
    )
    assert RUNNER_PROCESS_OWNER_DIRECTORY_NAME == "process-owners"
    assert RUNNER_PROCESS_OWNER_POINTER_FILENAME == "runner-process-owner.json"
    assert RUNNER_PROCESS_OWNER_FINGERPRINT_ENV == (
        "H2OMETA_RUNNER_PROCESS_OWNER_FINGERPRINT"
    )
    assert RUNNER_PROCESS_OWNER_LAUNCH_ID_ENV == (
        "H2OMETA_RUNNER_PROCESS_OWNER_LAUNCH_ID"
    )
    assert RUNNER_PROCESS_OWNER_UNAVAILABLE_EXIT_STATUS == 75


def test_build_runner_process_owner_returns_exact_detached_body() -> None:
    process_incarnation = _process_incarnation()
    startup_binding = _startup_binding()
    lifetime_lock = _lifetime_lock()

    owner = build_runner_process_owner(
        launch_id=LAUNCH_ID,
        process_incarnation=process_incarnation,
        startup_binding=startup_binding,
        lifetime_lock=lifetime_lock,
    )

    assert owner == {
        "launchId": LAUNCH_ID,
        "lifetimeLock": _lifetime_lock(),
        "phase": "launcher-preparation",
        "processIncarnation": _process_incarnation(),
        "profile": "linux-procfs-flock-startup-binding-v1",
        "schemaVersion": "h2ometa.runner-process-owner.v1",
        "startupBinding": _startup_binding(),
    }
    assert owner["processIncarnation"] is not process_incarnation
    assert owner["startupBinding"] is not startup_binding
    assert owner["lifetimeLock"] is not lifetime_lock
    startup_binding["version"] = "drifted"
    lifetime_lock["inode"] = 1
    process_incarnation["pid"] = 1
    assert owner["startupBinding"]["version"] == "0.2.0-control-plane"
    assert owner["lifetimeLock"]["inode"] == 98765
    assert owner["processIncarnation"]["pid"] == 4242


def test_require_runner_process_owner_returns_detached_normalized_copy() -> None:
    owner = _owner()

    normalized = require_runner_process_owner(owner)

    assert normalized == owner
    assert normalized is not owner
    assert normalized["startupBinding"] is not owner["startupBinding"]
    assert normalized["lifetimeLock"] is not owner["lifetimeLock"]
    assert normalized["processIncarnation"] is not owner["processIncarnation"]


@pytest.mark.parametrize(
    "field",
    [
        "launchId",
        "lifetimeLock",
        "phase",
        "processIncarnation",
        "profile",
        "schemaVersion",
        "startupBinding",
    ],
)
def test_owner_rejects_missing_top_level_fields(field: str) -> None:
    owner = _owner()
    owner.pop(field)

    with pytest.raises(ValueError, match="fields must match exactly"):
        require_runner_process_owner(owner)


def test_owner_rejects_embedded_fingerprint_or_other_unknown_fields() -> None:
    owner = _owner()
    owner["ownerFingerprint"] = "sha256:" + "0" * 64

    with pytest.raises(ValueError, match="fields must match exactly"):
        require_runner_process_owner(owner)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("schemaVersion", "h2ometa.runner-process-owner.v2"),
        ("profile", "different-profile"),
        ("phase", "runtime-serving"),
    ],
)
def test_owner_rejects_wrong_fixed_values(field: str, replacement: object) -> None:
    owner = _owner()
    owner[field] = replacement

    with pytest.raises(ValueError, match=field):
        require_runner_process_owner(owner)


@pytest.mark.parametrize(
    "launch_id",
    [
        "0123456789abcdef0123456789abcde",
        "0123456789abcdef0123456789abcdef0",
        "0123456789ABCDEF0123456789ABCDEF",
        "01234567-89ab-cdef-0123-456789abcdef",
        123,
        None,
    ],
)
def test_owner_rejects_noncanonical_launch_ids(launch_id: object) -> None:
    owner = _owner()
    owner["launchId"] = launch_id

    with pytest.raises(ValueError, match="launchId is invalid"):
        require_runner_process_owner(owner)


def test_owner_reuses_strict_process_incarnation_validator() -> None:
    owner = _owner()
    owner["processIncarnation"]["pid"] = True

    with pytest.raises(ValueError, match="incarnation pid is invalid"):
        require_runner_process_owner(owner)


@pytest.mark.parametrize(
    "field",
    [
        "artifactArchiveSha256Path",
        "bootstrapManifestFingerprint",
        "bootstrapManifestPath",
        "configPath",
        "configuredMode",
        "declaredArtifactArchiveSha256",
        "effectiveConfigFingerprint",
        "packagePath",
        "persistedConfigFingerprint",
        "protocolFingerprint",
        "protocolVersion",
        "runnerPythonPath",
        "service",
        "version",
    ],
)
def test_owner_rejects_missing_startup_binding_fields(field: str) -> None:
    owner = _owner()
    owner["startupBinding"].pop(field)

    with pytest.raises(ValueError, match="startupBinding fields must match exactly"):
        require_runner_process_owner(owner)


def test_owner_rejects_unknown_startup_binding_fields() -> None:
    owner = _owner()
    owner["startupBinding"]["createdAt"] = "2099-01-01T00:00:00Z"

    with pytest.raises(ValueError, match="startupBinding fields must match exactly"):
        require_runner_process_owner(owner)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("service", "other-service"),
        ("version", ""),
        ("version", " leading-space"),
        ("version", "control\ncharacter"),
        ("version", "surrogate-" + chr(0xD800)),
        ("version", "surrogate-" + chr(0xDFFF)),
        ("version", 5),
        ("configuredMode", "daemon"),
        ("configuredMode", True),
        ("protocolVersion", "runner-protocol.v0"),
        ("protocolVersion", "runner-protocol.v05"),
        ("protocolVersion", "runner-protocol.v5 "),
        ("protocolVersion", 5),
    ],
)
def test_owner_rejects_invalid_startup_scalar_values(
    field: str,
    replacement: object,
) -> None:
    owner = _owner()
    owner["startupBinding"][field] = replacement

    with pytest.raises(ValueError, match=field):
        require_runner_process_owner(owner)


@pytest.mark.parametrize(
    "field",
    [
        "artifactArchiveSha256Path",
        "bootstrapManifestPath",
        "configPath",
        "packagePath",
        "runnerPythonPath",
    ],
)
@pytest.mark.parametrize(
    "replacement",
    [
        "relative/path",
        "C:/h2ometa/path",
        "/opt/h2ometa/../escape",
        "/opt//h2ometa/path",
        "/opt/h2ometa/path/",
        "/opt/h2ometa\\path",
        "/opt/h2ometa/" + chr(0xD800),
        "/opt/h2ometa/" + chr(0xDFFF),
        "//server/share",
        "",
        1,
    ],
)
def test_owner_rejects_noncanonical_absolute_posix_paths(
    field: str,
    replacement: object,
) -> None:
    owner = _owner()
    owner["startupBinding"][field] = replacement

    with pytest.raises(ValueError, match=field):
        require_runner_process_owner(owner)


@pytest.mark.parametrize(
    "field",
    [
        "bootstrapManifestFingerprint",
        "declaredArtifactArchiveSha256",
        "effectiveConfigFingerprint",
        "persistedConfigFingerprint",
        "protocolFingerprint",
    ],
)
@pytest.mark.parametrize(
    "replacement",
    [
        "0" * 64,
        "sha256:" + "A" * 64,
        "sha256:" + "0" * 63,
        "sha256:" + "0" * 65,
        "sha512:" + "0" * 64,
        1,
        None,
    ],
)
def test_owner_rejects_noncanonical_fingerprints(
    field: str,
    replacement: object,
) -> None:
    owner = _owner()
    owner["startupBinding"][field] = replacement

    with pytest.raises(ValueError, match=field):
        require_runner_process_owner(owner)


@pytest.mark.parametrize("field", ["device", "inode", "path", "profile"])
def test_owner_rejects_missing_lifetime_lock_fields(field: str) -> None:
    owner = _owner()
    owner["lifetimeLock"].pop(field)

    with pytest.raises(ValueError, match="lifetimeLock fields must match exactly"):
        require_runner_process_owner(owner)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("profile", "unsupported"),
        ("path", "relative/runner.lock"),
        ("path", "/shared/../runner.lock"),
        ("path", "/shared/" + chr(0xD800)),
        ("path", "/shared/" + chr(0xDFFF)),
        ("device", True),
        ("device", -1),
        ("device", 1.0),
        ("inode", False),
        ("inode", 0),
        ("inode", 1.0),
    ],
)
def test_owner_rejects_invalid_lifetime_lock_values(
    field: str,
    replacement: object,
) -> None:
    owner = _owner()
    owner["lifetimeLock"][field] = replacement

    with pytest.raises(ValueError, match=field):
        require_runner_process_owner(owner)


def test_owner_validation_uses_requested_error_factory() -> None:
    class OwnerError(RuntimeError):
        pass

    with pytest.raises(OwnerError, match="wrapped: runner process owner"):
        require_runner_process_owner(
            [],
            make_error=lambda message: OwnerError(f"wrapped: {message}"),
        )


def test_owner_accepts_utf8_scalar_strings_for_canonical_hashing() -> None:
    owner = _owner()
    owner["startupBinding"]["version"] = "版本-α"
    owner["startupBinding"]["packagePath"] = "/opt/h2ometa/版本"
    owner["lifetimeLock"]["path"] = "/opt/h2ometa/运行/runner.lock"

    normalized = require_runner_process_owner(owner)

    canonical = runner_process_owner_canonical_json(normalized)
    fingerprint = runner_process_owner_fingerprint(normalized)
    assert "版本-α" in canonical
    assert fingerprint.startswith("sha256:")


def test_owner_fingerprint_rejects_surrogates_before_utf8_encoding() -> None:
    owner = _owner()
    owner["startupBinding"]["version"] = "surrogate-" + chr(0xD800)

    with pytest.raises(
        ValueError,
        match="startupBinding.version is invalid",
    ) as exc_info:
        runner_process_owner_fingerprint(owner)

    assert type(exc_info.value) is ValueError


def test_owner_canonical_json_has_a_stable_golden_representation() -> None:
    owner = _owner()
    reordered = dict(reversed(tuple(owner.items())))

    canonical = runner_process_owner_canonical_json(reordered)

    assert canonical == EXPECTED_OWNER_CANONICAL
    assert canonical == json.dumps(
        owner,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    assert " " not in canonical
    assert "\n" not in canonical
    assert runner_process_owner_canonical_json(owner) == canonical


def test_owner_fingerprint_is_domain_separated_and_has_a_fixed_golden() -> None:
    owner = _owner()
    canonical = runner_process_owner_canonical_json(owner)
    expected = hashlib.sha256(
        b"h2ometa.runner-process-owner.v1\x00" + canonical.encode("utf-8")
    ).hexdigest()

    assert expected == "aadffa817ae38b2a445d7bd14015f1ec9e4438c386b31a77476905b05df30956"
    assert runner_process_owner_fingerprint(owner) == f"sha256:{expected}"
    assert runner_process_owner_fingerprint(deepcopy(owner)) == f"sha256:{expected}"


def test_owner_fingerprint_rejects_non_current_payload() -> None:
    owner = _owner()
    owner["phase"] = "serving"

    with pytest.raises(ValueError, match="phase"):
        runner_process_owner_fingerprint(owner)


def test_build_owner_reference_returns_exact_body() -> None:
    reference = build_runner_process_owner_reference(
        launch_id=LAUNCH_ID,
        owner_fingerprint="sha256:" + "a" * 64,
    )

    assert reference == {
        "launchId": LAUNCH_ID,
        "ownerFingerprint": "sha256:" + "a" * 64,
        "schemaVersion": "h2ometa.runner-process-owner-reference.v1",
    }
    assert require_runner_process_owner_reference(reference) == reference
    assert require_runner_process_owner_reference(reference) is not reference


@pytest.mark.parametrize("field", ["launchId", "ownerFingerprint", "schemaVersion"])
def test_owner_reference_rejects_missing_fields(field: str) -> None:
    reference = build_runner_process_owner_reference(
        launch_id=LAUNCH_ID,
        owner_fingerprint="sha256:" + "a" * 64,
    )
    reference.pop(field)

    with pytest.raises(ValueError, match="reference fields must match exactly"):
        require_runner_process_owner_reference(reference)


def test_owner_reference_rejects_unknown_fields() -> None:
    reference = build_runner_process_owner_reference(
        launch_id=LAUNCH_ID,
        owner_fingerprint="sha256:" + "a" * 64,
    )
    reference["createdAt"] = "2099-01-01T00:00:00Z"

    with pytest.raises(ValueError, match="reference fields must match exactly"):
        require_runner_process_owner_reference(reference)


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        ("schemaVersion", "old", "reference.schemaVersion"),
        ("launchId", "A" * 32, "launchId"),
        ("ownerFingerprint", "a" * 64, "ownerFingerprint"),
        ("ownerFingerprint", "sha256:" + "A" * 64, "ownerFingerprint"),
    ],
)
def test_owner_reference_rejects_invalid_values(
    field: str,
    replacement: object,
    message: str,
) -> None:
    reference = build_runner_process_owner_reference(
        launch_id=LAUNCH_ID,
        owner_fingerprint="sha256:" + "a" * 64,
    )
    reference[field] = replacement

    with pytest.raises(ValueError, match=message):
        require_runner_process_owner_reference(reference)


def test_owner_reference_validation_uses_requested_error_type() -> None:
    class ReferenceError(RuntimeError):
        pass

    with pytest.raises(ReferenceError, match="must be an object"):
        require_runner_process_owner_reference([], make_error=ReferenceError)
