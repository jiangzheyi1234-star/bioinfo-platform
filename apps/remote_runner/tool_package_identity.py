from __future__ import annotations

from .tool_contract import package_version_from_spec
from .tools_errors import ToolRegistryError


def normalize_package_identity(*, source: str, name: str, version: str, package_spec: str) -> dict[str, str]:
    requested_version = str(version or "").strip()
    normalized_spec = str(package_spec or "").strip()
    if not normalized_spec:
        normalized_spec = f"{source}::{name}={requested_version}" if requested_version else f"{source}::{name}"
    locked_version = package_version_from_spec(normalized_spec)
    if not locked_version:
        raise ToolRegistryError("TOOL_PACKAGE_VERSION_REQUIRED")
    spec_channel, spec_name = _package_spec_identity(normalized_spec)
    if spec_channel and spec_channel.lower() != source.lower():
        raise ToolRegistryError("TOOL_PACKAGE_SOURCE_MISMATCH")
    if spec_name and spec_name.lower() != name.lower():
        raise ToolRegistryError("TOOL_PACKAGE_NAME_MISMATCH")
    if requested_version and requested_version != locked_version:
        raise ToolRegistryError("TOOL_PACKAGE_VERSION_MISMATCH")
    return {"version": locked_version, "packageSpec": normalized_spec}


def _package_spec_identity(package_spec: str) -> tuple[str, str]:
    package = str(package_spec or "").strip()
    channel = ""
    if "::" in package:
        channel, package = package.split("::", 1)
    for separator in ("==", "="):
        if separator in package:
            package = package.split(separator, 1)[0]
            break
    return channel.strip(), package.strip()
