from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any


MANAGED_EXTENSION_LIST_SCHEMA_VERSION = "h2ometa.managed-extension-list.v2"
MANAGED_EXTENSION_MANIFEST_SCHEMA_VERSION = "h2ometa.managed-extension-manifest.v2"
MANAGED_EXTENSION_ACTION_RESULT_SCHEMA_VERSION = "h2ometa.managed-extension-action-result.v1"
MANAGED_EXTENSION_ACTION_TYPE = "managed-extension-action"

MANAGED_EXTENSION_PLACEMENTS = {"control-plane", "remote-executor", "both", "data-only"}
MANAGED_EXTENSION_ACTION_TYPES = {MANAGED_EXTENSION_ACTION_TYPE, "navigate", "agent-capability"}
MANAGED_EXTENSION_RISKS = {"low", "medium", "high", "destructive"}

_MANIFEST_FIELDS = {
    "schemaVersion",
    "id",
    "registryId",
    "kind",
    "displayName",
    "placement",
    "installTargets",
    "distribution",
    "compatibility",
    "actions",
    "permissions",
    "capabilities",
    "stateProjection",
}
_INSTALL_TARGET_FIELDS = {"kind", "label", "requiresServerProfile"}
_DISTRIBUTION_FIELDS = {
    "mode",
    "channel",
    "delivery",
    "packageType",
    "latestVersion",
    "immutable",
    "variants",
}
_VARIANT_FIELDS = {
    "version",
    "platform",
    "archiveName",
    "sizeBytes",
    "sha256",
    "downloadAvailable",
    "sbomAvailable",
    "provenanceAvailable",
    "attestationAvailable",
    "signatureAvailable",
    "builderId",
    "sourceCommit",
}
_COMPATIBILITY_FIELDS = {
    "h2ometaApiRange",
    "runnerProtocolRange",
    "platforms",
    "operatingSystems",
    "architectures",
    "libc",
    "pythonAbi",
    "accelerators",
    "dependencies",
    "conflicts",
}
_ACTION_FIELDS = {
    "id",
    "label",
    "type",
    "driver",
    "operation",
    "jobKind",
    "mode",
    "confirmation",
    "requiresPreview",
    "requiresConfirmation",
    "risk",
    "href",
    "capabilityId",
}
_PERMISSION_FIELDS = {"id", "risk", "confirmation", "description"}
_CAPABILITY_FIELDS = {"id", "label", "operation", "workflowStage", "agentSelectable"}
_STATE_PROJECTION_FIELDS = {"source", "versionField", "readyField"}
_CATALOG_REQUIRED_FIELDS = {
    "id",
    "kind",
    "slug",
    "name",
    "summary",
    "description",
    "icon",
    "publisher",
    "categoryIds",
    "tags",
    "featured",
    "requiresRunner",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ManagedExtensionContractError(ValueError):
    def __init__(self, reason_code: str, *, path: str, message: str) -> None:
        super().__init__(f"{reason_code} at {path}: {message}")
        self.reason_code = reason_code
        self.path = path
        self.message = message

    def to_detail(self) -> dict[str, Any]:
        return {
            "reasonCode": self.reason_code,
            "path": self.path,
            "message": self.message,
        }


class ManagedExtensionResolutionError(RuntimeError):
    status_code = 400
    reason_code = "MANAGED_EXTENSION_RESOLUTION_FAILED"

    def __init__(self, message: str, **context: str) -> None:
        super().__init__(message)
        self.context = {key: value for key, value in context.items() if value}

    def to_detail(self) -> dict[str, Any]:
        return {"reasonCode": self.reason_code, **self.context}


class ManagedExtensionNotFoundError(ManagedExtensionResolutionError):
    status_code = 404
    reason_code = "MANAGED_EXTENSION_NOT_FOUND"


class ManagedExtensionActionNotFoundError(ManagedExtensionResolutionError):
    reason_code = "MANAGED_EXTENSION_ACTION_UNSUPPORTED"


class ManagedExtensionActionNotExecutableError(ManagedExtensionResolutionError):
    reason_code = "MANAGED_EXTENSION_ACTION_NOT_EXECUTABLE"


class ManagedExtensionActionUnavailableError(ManagedExtensionResolutionError):
    status_code = 409
    reason_code = "MANAGED_EXTENSION_ACTION_UNAVAILABLE"


class ManagedExtensionDriverNotFoundError(ManagedExtensionResolutionError):
    reason_code = "MANAGED_EXTENSION_DRIVER_NOT_FOUND"


@dataclass(frozen=True)
class ManagedExtensionRegistryDescriptor:
    id: str
    label: str
    type: str
    priority: int
    package_import: bool

    def __post_init__(self) -> None:
        for field_name in ("id", "label", "type"):
            if not str(getattr(self, field_name) or "").strip():
                raise ManagedExtensionContractError(
                    "MANAGED_EXTENSION_REGISTRY_DESCRIPTOR_INVALID",
                    path=f"registry.{field_name}",
                    message=f"{field_name} must be a non-empty string",
                )
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise ManagedExtensionContractError(
                "MANAGED_EXTENSION_REGISTRY_DESCRIPTOR_INVALID",
                path="registry.priority",
                message="priority must be an integer",
            )
        if not isinstance(self.package_import, bool):
            raise ManagedExtensionContractError(
                "MANAGED_EXTENSION_REGISTRY_DESCRIPTOR_INVALID",
                path="registry.packageImport",
                message="packageImport must be a boolean",
            )

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "type": self.type,
            "priority": self.priority,
            "packageImport": self.package_import,
        }


@dataclass(frozen=True)
class ManagedExtensionProjectionContext:
    active_server_profile: dict[str, Any] | None
    active_remote_provisioning_job: dict[str, Any] | None
    remote_provisioning_queue: dict[str, Any]


@dataclass(frozen=True)
class ManagedExtensionDefinition:
    registry_id: str
    catalog: dict[str, Any]
    manifest: dict[str, Any]
    state_projector: Callable[
        ["ManagedExtensionDefinition", ManagedExtensionProjectionContext],
        dict[str, Any],
    ]

    def __post_init__(self) -> None:
        catalog = deepcopy(self.catalog)
        missing_catalog_fields = _CATALOG_REQUIRED_FIELDS - set(catalog)
        if missing_catalog_fields:
            _raise_contract(
                "MANAGED_EXTENSION_CATALOG_FIELDS_MISSING",
                "catalog",
                f"missing fields: {', '.join(sorted(missing_catalog_fields))}",
            )
        for field_name in ("id", "kind", "slug", "name", "summary", "icon", "publisher"):
            _require_non_empty_string(catalog.get(field_name), f"catalog.{field_name}")
        _require_string(catalog.get("description"), "catalog.description")
        _require_string_list(catalog.get("categoryIds"), "catalog.categoryIds", allow_empty=False)
        _require_string_list(catalog.get("tags"), "catalog.tags", allow_empty=False)
        _require_bool(catalog.get("featured"), "catalog.featured")
        _require_bool(catalog.get("requiresRunner"), "catalog.requiresRunner")
        if not callable(self.state_projector):
            _raise_contract(
                "MANAGED_EXTENSION_STATE_PROJECTOR_INVALID",
                "definition.stateProjector",
                "state projector must be callable",
            )

        manifest = validate_managed_extension_manifest(self.manifest)
        if str(self.registry_id or "").strip() != manifest["registryId"]:
            _raise_contract(
                "MANAGED_EXTENSION_REGISTRY_ID_MISMATCH",
                "definition.registryId",
                "definition and manifest registry ids must match",
            )
        if catalog["id"] != manifest["id"]:
            _raise_contract(
                "MANAGED_EXTENSION_ID_MISMATCH",
                "definition.catalog.id",
                "catalog and manifest ids must match",
            )
        if catalog["kind"] != manifest["kind"] and manifest["kind"] != "managed-runtime":
            _raise_contract(
                "MANAGED_EXTENSION_KIND_MISMATCH",
                "definition.catalog.kind",
                "catalog and manifest kinds must match",
            )
        object.__setattr__(self, "catalog", catalog)
        object.__setattr__(self, "manifest", manifest)

    @property
    def id(self) -> str:
        return str(self.manifest["id"])

    def require_action(self, action_id: str) -> dict[str, Any]:
        for action in self.manifest["actions"]:
            if action["id"] == action_id:
                return deepcopy(action)
        raise ManagedExtensionActionNotFoundError(
            f"Unsupported managed extension action: {action_id}",
            extensionId=self.id,
            action=action_id,
        )

    def catalog_payload(self) -> dict[str, Any]:
        payload = deepcopy(self.catalog)
        payload.update(
            {
                "registryId": self.registry_id,
                "capabilities": deepcopy(self.manifest["capabilities"]),
                "manifest": deepcopy(self.manifest),
            }
        )
        return payload


def validate_managed_extension_manifest(raw: Mapping[str, Any]) -> dict[str, Any]:
    manifest = _require_mapping(raw, "manifest")
    _require_exact_fields(manifest, _MANIFEST_FIELDS, "manifest")
    if manifest.get("schemaVersion") != MANAGED_EXTENSION_MANIFEST_SCHEMA_VERSION:
        _raise_contract(
            "MANAGED_EXTENSION_MANIFEST_SCHEMA_UNSUPPORTED",
            "manifest.schemaVersion",
            f"expected {MANAGED_EXTENSION_MANIFEST_SCHEMA_VERSION}",
        )
    for field_name in ("id", "registryId", "kind", "displayName"):
        _require_non_empty_string(manifest.get(field_name), f"manifest.{field_name}")
    placement = _require_non_empty_string(manifest.get("placement"), "manifest.placement")
    if placement not in MANAGED_EXTENSION_PLACEMENTS:
        _raise_contract(
            "MANAGED_EXTENSION_PLACEMENT_UNSUPPORTED",
            "manifest.placement",
            f"unsupported placement: {placement}",
        )
    _validate_install_targets(manifest.get("installTargets"))
    _validate_distribution(manifest.get("distribution"))
    _validate_compatibility(manifest.get("compatibility"))
    _validate_actions(manifest.get("actions"))
    _validate_permissions(manifest.get("permissions"))
    _validate_capabilities(manifest.get("capabilities"))
    state_projection = _require_mapping(manifest.get("stateProjection"), "manifest.stateProjection")
    _require_allowed_fields(state_projection, _STATE_PROJECTION_FIELDS, "manifest.stateProjection")
    for field_name, value in state_projection.items():
        _require_non_empty_string(value, f"manifest.stateProjection.{field_name}")
    return deepcopy(dict(manifest))


def _validate_install_targets(raw: Any) -> None:
    targets = _require_list(raw, "manifest.installTargets", allow_empty=False)
    seen: set[str] = set()
    for index, raw_target in enumerate(targets):
        path = f"manifest.installTargets[{index}]"
        target = _require_mapping(raw_target, path)
        _require_exact_fields(target, _INSTALL_TARGET_FIELDS, path)
        kind = _require_non_empty_string(target.get("kind"), f"{path}.kind")
        _require_non_empty_string(target.get("label"), f"{path}.label")
        _require_bool(target.get("requiresServerProfile"), f"{path}.requiresServerProfile")
        if kind in seen:
            _raise_contract("MANAGED_EXTENSION_INSTALL_TARGET_DUPLICATE", f"{path}.kind", kind)
        seen.add(kind)


def _validate_distribution(raw: Any) -> None:
    distribution = _require_mapping(raw, "manifest.distribution")
    _require_exact_fields(distribution, _DISTRIBUTION_FIELDS, "manifest.distribution")
    for field_name in ("mode", "channel", "delivery", "packageType"):
        _require_non_empty_string(distribution.get(field_name), f"manifest.distribution.{field_name}")
    latest_version = _require_string(distribution.get("latestVersion"), "manifest.distribution.latestVersion")
    _require_bool(distribution.get("immutable"), "manifest.distribution.immutable")
    variants = _require_list(distribution.get("variants"), "manifest.distribution.variants", allow_empty=True)
    seen_platforms: set[str] = set()
    for index, raw_variant in enumerate(variants):
        path = f"manifest.distribution.variants[{index}]"
        variant = _require_mapping(raw_variant, path)
        _require_exact_fields(variant, _VARIANT_FIELDS, path)
        version = _require_non_empty_string(variant.get("version"), f"{path}.version")
        platform = _require_non_empty_string(variant.get("platform"), f"{path}.platform")
        _require_non_empty_string(variant.get("archiveName"), f"{path}.archiveName")
        size_bytes = variant.get("sizeBytes")
        if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes <= 0:
            _raise_contract(
                "MANAGED_EXTENSION_ARTIFACT_SIZE_INVALID",
                f"{path}.sizeBytes",
                "sizeBytes must be a positive integer",
            )
        sha256 = _require_non_empty_string(variant.get("sha256"), f"{path}.sha256")
        if not _SHA256_RE.fullmatch(sha256):
            _raise_contract(
                "MANAGED_EXTENSION_ARTIFACT_SHA256_INVALID",
                f"{path}.sha256",
                "sha256 must contain 64 lowercase hexadecimal characters",
            )
        for field_name in (
            "downloadAvailable",
            "sbomAvailable",
            "provenanceAvailable",
            "attestationAvailable",
            "signatureAvailable",
        ):
            _require_bool(variant.get(field_name), f"{path}.{field_name}")
        _require_string(variant.get("builderId"), f"{path}.builderId")
        _require_string(variant.get("sourceCommit"), f"{path}.sourceCommit")
        if latest_version != version:
            _raise_contract(
                "MANAGED_EXTENSION_ARTIFACT_VERSION_MISMATCH",
                f"{path}.version",
                "variant version must equal distribution.latestVersion",
            )
        if platform in seen_platforms:
            _raise_contract("MANAGED_EXTENSION_ARTIFACT_PLATFORM_DUPLICATE", f"{path}.platform", platform)
        seen_platforms.add(platform)
    if variants and not latest_version:
        _raise_contract(
            "MANAGED_EXTENSION_LATEST_VERSION_REQUIRED",
            "manifest.distribution.latestVersion",
            "release variants require latestVersion",
        )


def _validate_compatibility(raw: Any) -> None:
    compatibility = _require_mapping(raw, "manifest.compatibility")
    _require_exact_fields(compatibility, _COMPATIBILITY_FIELDS, "manifest.compatibility")
    _require_non_empty_string(compatibility.get("h2ometaApiRange"), "manifest.compatibility.h2ometaApiRange")
    _require_non_empty_string(
        compatibility.get("runnerProtocolRange"),
        "manifest.compatibility.runnerProtocolRange",
    )
    for field_name in _COMPATIBILITY_FIELDS - {"h2ometaApiRange", "runnerProtocolRange"}:
        _require_string_list(
            compatibility.get(field_name),
            f"manifest.compatibility.{field_name}",
            allow_empty=True,
        )


def _validate_actions(raw: Any) -> None:
    actions = _require_list(raw, "manifest.actions", allow_empty=False)
    seen: set[str] = set()
    for index, raw_action in enumerate(actions):
        path = f"manifest.actions[{index}]"
        action = _require_mapping(raw_action, path)
        _require_allowed_fields(action, _ACTION_FIELDS, path)
        action_id = _require_non_empty_string(action.get("id"), f"{path}.id")
        action_type = _require_non_empty_string(action.get("type"), f"{path}.type")
        if action_type not in MANAGED_EXTENSION_ACTION_TYPES:
            _raise_contract("MANAGED_EXTENSION_ACTION_TYPE_UNSUPPORTED", f"{path}.type", action_type)
        if action_id in seen:
            _raise_contract("MANAGED_EXTENSION_ACTION_DUPLICATE", f"{path}.id", action_id)
        seen.add(action_id)
        if "label" in action:
            _require_non_empty_string(action.get("label"), f"{path}.label")
        if action_type == MANAGED_EXTENSION_ACTION_TYPE:
            _require_non_empty_string(action.get("label"), f"{path}.label")
            _require_non_empty_string(action.get("driver"), f"{path}.driver")
            _require_non_empty_string(action.get("operation"), f"{path}.operation")
        elif "driver" in action:
            _raise_contract(
                "MANAGED_EXTENSION_ACTION_DRIVER_FORBIDDEN",
                f"{path}.driver",
                "only managed-extension-action may declare a driver",
            )
        if action_type == "navigate":
            _require_non_empty_string(action.get("href"), f"{path}.href")
        if action_type == "agent-capability":
            _require_non_empty_string(action.get("capabilityId"), f"{path}.capabilityId")
        for field_name in ("requiresPreview", "requiresConfirmation"):
            if field_name in action:
                _require_bool(action.get(field_name), f"{path}.{field_name}")
        if action.get("requiresConfirmation") is True:
            _require_non_empty_string(action.get("confirmation"), f"{path}.confirmation")
        if "risk" in action and action.get("risk") not in MANAGED_EXTENSION_RISKS:
            _raise_contract("MANAGED_EXTENSION_RISK_UNSUPPORTED", f"{path}.risk", str(action.get("risk")))
        for field_name in ("operation", "jobKind", "mode", "confirmation", "href", "capabilityId"):
            if field_name in action:
                _require_non_empty_string(action.get(field_name), f"{path}.{field_name}")


def _validate_permissions(raw: Any) -> None:
    permissions = _require_list(raw, "manifest.permissions", allow_empty=True)
    seen: set[str] = set()
    for index, raw_permission in enumerate(permissions):
        path = f"manifest.permissions[{index}]"
        permission = _require_mapping(raw_permission, path)
        _require_allowed_fields(permission, _PERMISSION_FIELDS, path)
        permission_id = _require_non_empty_string(permission.get("id"), f"{path}.id")
        risk = _require_non_empty_string(permission.get("risk"), f"{path}.risk")
        if risk not in MANAGED_EXTENSION_RISKS:
            _raise_contract("MANAGED_EXTENSION_RISK_UNSUPPORTED", f"{path}.risk", risk)
        if permission_id in seen:
            _raise_contract("MANAGED_EXTENSION_PERMISSION_DUPLICATE", f"{path}.id", permission_id)
        seen.add(permission_id)
        for field_name in ("confirmation", "description"):
            if field_name in permission:
                _require_non_empty_string(permission.get(field_name), f"{path}.{field_name}")


def _validate_capabilities(raw: Any) -> None:
    capabilities = _require_list(raw, "manifest.capabilities", allow_empty=True)
    seen: set[str] = set()
    for index, raw_capability in enumerate(capabilities):
        path = f"manifest.capabilities[{index}]"
        capability = _require_mapping(raw_capability, path)
        _require_allowed_fields(capability, _CAPABILITY_FIELDS, path)
        capability_id = _require_non_empty_string(capability.get("id"), f"{path}.id")
        _require_non_empty_string(capability.get("label"), f"{path}.label")
        if capability_id in seen:
            _raise_contract("MANAGED_EXTENSION_CAPABILITY_DUPLICATE", f"{path}.id", capability_id)
        seen.add(capability_id)
        for field_name in ("operation", "workflowStage"):
            if field_name in capability:
                _require_non_empty_string(capability.get(field_name), f"{path}.{field_name}")
        if "agentSelectable" in capability:
            _require_bool(capability.get("agentSelectable"), f"{path}.agentSelectable")


def _require_mapping(raw: Any, path: str) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        _raise_contract("MANAGED_EXTENSION_OBJECT_REQUIRED", path, "expected an object")
    return dict(raw)


def _require_list(raw: Any, path: str, *, allow_empty: bool) -> list[Any]:
    if not isinstance(raw, list) or (not allow_empty and not raw):
        qualifier = "a list" if allow_empty else "a non-empty list"
        _raise_contract("MANAGED_EXTENSION_LIST_REQUIRED", path, f"expected {qualifier}")
    return raw


def _require_exact_fields(raw: Mapping[str, Any], expected: set[str], path: str) -> None:
    actual = set(raw)
    missing = expected - actual
    unknown = actual - expected
    if missing:
        _raise_contract(
            "MANAGED_EXTENSION_FIELDS_MISSING",
            path,
            f"missing fields: {', '.join(sorted(missing))}",
        )
    if unknown:
        _raise_contract(
            "MANAGED_EXTENSION_FIELDS_UNKNOWN",
            path,
            f"unknown fields: {', '.join(sorted(unknown))}",
        )


def _require_allowed_fields(raw: Mapping[str, Any], allowed: set[str], path: str) -> None:
    unknown = set(raw) - allowed
    if unknown:
        _raise_contract(
            "MANAGED_EXTENSION_FIELDS_UNKNOWN",
            path,
            f"unknown fields: {', '.join(sorted(unknown))}",
        )


def _require_non_empty_string(raw: Any, path: str) -> str:
    value = _require_string(raw, path).strip()
    if not value:
        _raise_contract("MANAGED_EXTENSION_STRING_REQUIRED", path, "expected a non-empty string")
    return value


def _require_string(raw: Any, path: str) -> str:
    if not isinstance(raw, str):
        _raise_contract("MANAGED_EXTENSION_STRING_REQUIRED", path, "expected a string")
    return raw


def _require_bool(raw: Any, path: str) -> None:
    if not isinstance(raw, bool):
        _raise_contract("MANAGED_EXTENSION_BOOLEAN_REQUIRED", path, "expected a boolean")


def _require_string_list(raw: Any, path: str, *, allow_empty: bool) -> None:
    values = _require_list(raw, path, allow_empty=allow_empty)
    for index, value in enumerate(values):
        _require_non_empty_string(value, f"{path}[{index}]")


def _raise_contract(reason_code: str, path: str, message: str) -> None:
    raise ManagedExtensionContractError(reason_code, path=path, message=message)
