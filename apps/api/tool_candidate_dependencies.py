"""Helpers for deriving package identities from candidate environment hints."""

from __future__ import annotations

import re
from typing import Any


SUPPORTED_CONDA_SOURCES = {"bioconda", "conda-forge", "qiime2"}
RANGE_OPERATORS = (">=", "<=", ">", "<", "~=", "!=")


def conda_dependency_from_environment_hints(
    hints: dict[str, Any],
    *,
    preferred_name: str,
) -> dict[str, str] | None:
    environment = hints.get("environment") if isinstance(hints.get("environment"), dict) else {}
    conda = environment.get("conda") if isinstance(environment.get("conda"), dict) else {}
    channels = [str(item).strip() for item in conda.get("channels", []) if str(item or "").strip()]
    dependencies = [str(item).strip() for item in conda.get("dependencies", []) if str(item or "").strip()]
    candidates = [
        dependency
        for dependency in (parse_conda_dependency(raw_dependency, channels=channels) for raw_dependency in dependencies)
        if dependency is not None
    ]
    if not candidates:
        return None
    normalized_preferred = normalize_package_name(preferred_name)
    for dependency in candidates:
        if normalize_package_name(dependency["name"]) == normalized_preferred:
            return dependency
    for dependency in candidates:
        if normalize_package_name(dependency["name"]) != "snakemake-wrapper-utils":
            return dependency
    return candidates[0]


def parse_conda_dependency(raw: str, *, channels: list[str]) -> dict[str, str] | None:
    text = str(raw or "").strip()
    if not text:
        return None
    source = ""
    explicit_source = False
    if "::" in text:
        explicit_source = True
        source, text = [part.strip() for part in text.split("::", 1)]
    if explicit_source and source not in SUPPORTED_CONDA_SOURCES:
        return None
    if source not in SUPPORTED_CONDA_SOURCES:
        source = "bioconda" if "bioconda" in channels else "conda-forge"
    normalized = " ".join(text.replace("==", "=").split())
    if any(operator in normalized for operator in RANGE_OPERATORS):
        return None
    name = normalized
    version = ""
    if "=" in normalized:
        name, version = [part.strip() for part in normalized.split("=", 1)]
    if not name or name.startswith("-"):
        return None
    return {"source": source, "name": name, "version": version}


def package_spec_from_conda_dependency(dependency: dict[str, str]) -> str:
    source = dependency["source"]
    name = dependency["name"]
    version = dependency.get("version") or ""
    return f"{source}::{name}={version}" if version else f"{source}::{name}"


def normalize_package_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9.+-]+", "-", str(value or "").lower()).strip("-")
