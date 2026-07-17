"""Immutable generation and unique activation-target contracts."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import PurePosixPath
import re

from .runner_activation_validation import (
    canonical_json as _canonical_json,
    fingerprint as _fingerprint,
    require_absolute_posix_path as _require_absolute_posix_path,
    require_exact_string as _require_exact_string,
    require_fingerprint as _require_fingerprint,
    require_id as _require_id,
    require_mapping as _require_mapping,
)


RUNNER_ACTIVATION_GENERATION_SCHEMA = "h2ometa.runner-activation-generation.v1"
RUNNER_ACTIVATION_TARGET_SCHEMA = "h2ometa.runner-activation-target.v1"
RUNNER_ACTIVATION_SERVICE = "h2ometa-remote"
RUNNER_ACTIVATION_UNIT_TEMPLATE = "h2ometa-remote@{activation_id}.service"
RUNNER_ACTIVATION_UNIT_TEMPLATE_FILENAME = "h2ometa-remote@.service"
RUNNER_ACTIVATION_GUARD_OWNER_TEMPLATE = "h2ometa-remote:{operation}:{activation_id}"
RUNNER_ACTIVATION_OPERATIONS = (
    "install",
    "upgrade",
    "token_rotation",
    "repair",
    "rollback",
)

_GENERATION_FIELDS = frozenset(
    {
        "configFingerprint",
        "configPath",
        "generationId",
        "profileFingerprint",
        "profilePath",
        "protocolFingerprint",
        "protocolVersion",
        "releaseArtifactSha256",
        "releasePath",
        "runtimeConfigFingerprint",
        "schemaVersion",
        "service",
        "systemdUnitTemplateFingerprint",
        "tokenGenerationId",
    }
)
_TARGET_FIELDS = frozenset(
    {
        "activationId",
        "currentLinkPath",
        "currentLinkTarget",
        "generation",
        "lifecycleGuardOwner",
        "operation",
        "schemaVersion",
        "systemdUnit",
        "systemdUnitTemplatePath",
    }
)
_PROTOCOL_VERSION_PATTERN = re.compile(r"^runner-protocol\.v[1-9][0-9]*$")
_GENERATION_FINGERPRINT_DOMAIN = RUNNER_ACTIVATION_GENERATION_SCHEMA.encode("ascii")
_TARGET_FINGERPRINT_DOMAIN = RUNNER_ACTIVATION_TARGET_SCHEMA.encode("ascii")


def build_runner_activation_generation(
    *,
    generation_id: object,
    release_path: object,
    release_artifact_sha256: object,
    config_path: object,
    config_fingerprint: object,
    runtime_config_fingerprint: object,
    profile_path: object,
    profile_fingerprint: object,
    protocol_version: object,
    protocol_fingerprint: object,
    systemd_unit_template_fingerprint: object,
    token_generation_id: object,
) -> dict[str, object]:
    """Build one exact immutable generation snapshot without secret material."""

    return require_runner_activation_generation(
        {
            "configFingerprint": config_fingerprint,
            "configPath": config_path,
            "generationId": generation_id,
            "profileFingerprint": profile_fingerprint,
            "profilePath": profile_path,
            "protocolFingerprint": protocol_fingerprint,
            "protocolVersion": protocol_version,
            "releaseArtifactSha256": release_artifact_sha256,
            "releasePath": release_path,
            "runtimeConfigFingerprint": runtime_config_fingerprint,
            "schemaVersion": RUNNER_ACTIVATION_GENERATION_SCHEMA,
            "service": RUNNER_ACTIVATION_SERVICE,
            "systemdUnitTemplateFingerprint": (systemd_unit_template_fingerprint),
            "tokenGenerationId": token_generation_id,
        }
    )


def require_runner_activation_generation(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, object]:
    """Validate a generation and return a normalized detached copy."""

    mapping = _require_mapping(
        payload,
        expected=_GENERATION_FIELDS,
        context="runner activation generation",
        make_error=make_error,
    )
    _require_exact_string(
        mapping.get("schemaVersion"),
        expected=RUNNER_ACTIVATION_GENERATION_SCHEMA,
        field="generation.schemaVersion",
        make_error=make_error,
    )
    _require_exact_string(
        mapping.get("service"),
        expected=RUNNER_ACTIVATION_SERVICE,
        field="generation.service",
        make_error=make_error,
    )
    generation_id = _require_id(
        mapping.get("generationId"), "generation.generationId", make_error
    )
    token_generation_id = _require_id(
        mapping.get("tokenGenerationId"),
        "generation.tokenGenerationId",
        make_error,
    )
    if token_generation_id == generation_id:
        raise make_error(
            "runner activation generation tokenGenerationId must be distinct"
        )
    release_path = _require_absolute_posix_path(
        mapping.get("releasePath"), "generation.releasePath", make_error
    )
    config_path = _require_absolute_posix_path(
        mapping.get("configPath"), "generation.configPath", make_error
    )
    profile_path = _require_absolute_posix_path(
        mapping.get("profilePath"), "generation.profilePath", make_error
    )
    runner_root = release_path.parent.parent
    if (
        release_path.parent.name != "releases"
        or runner_root.name != "runner"
        or runner_root.parent.name != ".h2ometa"
    ):
        raise make_error("runner activation generation releasePath is invalid")
    generation_root = (
        runner_root / "shared" / "activation" / "generations" / generation_id
    )
    if config_path != generation_root / "runner.json":
        raise make_error("runner activation generation configPath is invalid")
    if profile_path != generation_root / "profile.v9+.yaml":
        raise make_error("runner activation generation profilePath is invalid")
    protocol_version = mapping.get("protocolVersion")
    if (
        not isinstance(protocol_version, str)
        or _PROTOCOL_VERSION_PATTERN.fullmatch(protocol_version) is None
    ):
        raise make_error("runner activation generation protocolVersion is invalid")
    return {
        "configFingerprint": _require_fingerprint(
            mapping.get("configFingerprint"),
            "generation.configFingerprint",
            make_error,
        ),
        "configPath": str(config_path),
        "generationId": generation_id,
        "profileFingerprint": _require_fingerprint(
            mapping.get("profileFingerprint"),
            "generation.profileFingerprint",
            make_error,
        ),
        "profilePath": str(profile_path),
        "protocolFingerprint": _require_fingerprint(
            mapping.get("protocolFingerprint"),
            "generation.protocolFingerprint",
            make_error,
        ),
        "protocolVersion": protocol_version,
        "releaseArtifactSha256": _require_fingerprint(
            mapping.get("releaseArtifactSha256"),
            "generation.releaseArtifactSha256",
            make_error,
        ),
        "releasePath": str(release_path),
        "runtimeConfigFingerprint": _require_fingerprint(
            mapping.get("runtimeConfigFingerprint"),
            "generation.runtimeConfigFingerprint",
            make_error,
        ),
        "schemaVersion": RUNNER_ACTIVATION_GENERATION_SCHEMA,
        "service": RUNNER_ACTIVATION_SERVICE,
        "systemdUnitTemplateFingerprint": _require_fingerprint(
            mapping.get("systemdUnitTemplateFingerprint"),
            "generation.systemdUnitTemplateFingerprint",
            make_error,
        ),
        "tokenGenerationId": token_generation_id,
    }


def runner_activation_generation_canonical_json(payload: object) -> str:
    return _canonical_json(require_runner_activation_generation(payload))


def runner_activation_generation_fingerprint(payload: object) -> str:
    return _fingerprint(
        _GENERATION_FINGERPRINT_DOMAIN,
        runner_activation_generation_canonical_json(payload),
    )


def build_runner_activation_target(
    *,
    activation_id: object,
    operation: object,
    generation: object,
    current_link_path: object,
    current_link_target: object,
    systemd_unit: object,
    systemd_unit_template_path: object,
) -> dict[str, object]:
    """Build the exact target for one uniquely named activation attempt."""

    return require_runner_activation_target(
        {
            "activationId": activation_id,
            "currentLinkPath": current_link_path,
            "currentLinkTarget": current_link_target,
            "generation": generation,
            "lifecycleGuardOwner": (
                RUNNER_ACTIVATION_GUARD_OWNER_TEMPLATE.format(
                    operation=operation,
                    activation_id=activation_id,
                )
            ),
            "operation": operation,
            "schemaVersion": RUNNER_ACTIVATION_TARGET_SCHEMA,
            "systemdUnit": systemd_unit,
            "systemdUnitTemplatePath": systemd_unit_template_path,
        }
    )


def require_runner_activation_target(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, object]:
    """Validate an activation target and return a detached normalized copy."""

    mapping = _require_mapping(
        payload,
        expected=_TARGET_FIELDS,
        context="runner activation target",
        make_error=make_error,
    )
    _require_exact_string(
        mapping.get("schemaVersion"),
        expected=RUNNER_ACTIVATION_TARGET_SCHEMA,
        field="target.schemaVersion",
        make_error=make_error,
    )
    activation_id = _require_id(
        mapping.get("activationId"), "target.activationId", make_error
    )
    generation = require_runner_activation_generation(
        mapping.get("generation"), make_error=make_error
    )
    if activation_id in {
        generation["generationId"],
        generation["tokenGenerationId"],
    }:
        raise make_error("runner activation target activationId must be distinct")
    operation = mapping.get("operation")
    if not isinstance(operation, str) or operation not in RUNNER_ACTIVATION_OPERATIONS:
        raise make_error("runner activation target operation is invalid")
    expected_guard_owner = RUNNER_ACTIVATION_GUARD_OWNER_TEMPLATE.format(
        operation=operation,
        activation_id=activation_id,
    )
    _require_exact_string(
        mapping.get("lifecycleGuardOwner"),
        expected=expected_guard_owner,
        field="target.lifecycleGuardOwner",
        make_error=make_error,
    )
    current_link_path = _require_absolute_posix_path(
        mapping.get("currentLinkPath"), "target.currentLinkPath", make_error
    )
    current_link_target = _require_absolute_posix_path(
        mapping.get("currentLinkTarget"),
        "target.currentLinkTarget",
        make_error,
    )
    release_path = PurePosixPath(str(generation["releasePath"]))
    runner_root = release_path.parent.parent
    if current_link_path != runner_root / "current":
        raise make_error("runner activation target currentLinkPath is invalid")
    if current_link_target != release_path:
        raise make_error("runner activation target currentLinkTarget is invalid")
    expected_unit = RUNNER_ACTIVATION_UNIT_TEMPLATE.format(activation_id=activation_id)
    _require_exact_string(
        mapping.get("systemdUnit"),
        expected=expected_unit,
        field="target.systemdUnit",
        make_error=make_error,
    )
    template_path = _require_absolute_posix_path(
        mapping.get("systemdUnitTemplatePath"),
        "target.systemdUnitTemplatePath",
        make_error,
    )
    expected_template_path = (
        runner_root.parent.parent
        / ".config"
        / "systemd"
        / "user"
        / RUNNER_ACTIVATION_UNIT_TEMPLATE_FILENAME
    )
    if template_path != expected_template_path:
        raise make_error("runner activation target systemdUnitTemplatePath is invalid")
    return {
        "activationId": activation_id,
        "currentLinkPath": str(current_link_path),
        "currentLinkTarget": str(current_link_target),
        "generation": generation,
        "lifecycleGuardOwner": expected_guard_owner,
        "operation": operation,
        "schemaVersion": RUNNER_ACTIVATION_TARGET_SCHEMA,
        "systemdUnit": expected_unit,
        "systemdUnitTemplatePath": str(template_path),
    }


def runner_activation_target_canonical_json(payload: object) -> str:
    return _canonical_json(require_runner_activation_target(payload))


def runner_activation_target_fingerprint(payload: object) -> str:
    return _fingerprint(
        _TARGET_FINGERPRINT_DOMAIN,
        runner_activation_target_canonical_json(payload),
    )


__all__ = [
    "RUNNER_ACTIVATION_GENERATION_SCHEMA",
    "RUNNER_ACTIVATION_GUARD_OWNER_TEMPLATE",
    "RUNNER_ACTIVATION_OPERATIONS",
    "RUNNER_ACTIVATION_SERVICE",
    "RUNNER_ACTIVATION_TARGET_SCHEMA",
    "RUNNER_ACTIVATION_UNIT_TEMPLATE",
    "RUNNER_ACTIVATION_UNIT_TEMPLATE_FILENAME",
    "build_runner_activation_generation",
    "build_runner_activation_target",
    "require_runner_activation_generation",
    "require_runner_activation_target",
    "runner_activation_generation_canonical_json",
    "runner_activation_generation_fingerprint",
    "runner_activation_target_canonical_json",
    "runner_activation_target_fingerprint",
]
