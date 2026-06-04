from __future__ import annotations

from pathlib import Path
from typing import Any

from . import database_validation
from .database_errors import DatabaseCandidateConflictError, DatabaseRegistryError
from .database_templates import DATABASE_TEMPLATES


def resolve_candidate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    template_id = str(payload.get("templateId") or (payload.get("metadata") or {}).get("templateId") or "").strip().lower()
    template = DATABASE_TEMPLATES.get(template_id)
    if template is None:
        return payload
    selected_entry = str(payload.get("selectedEntryPath") or (payload.get("metadata") or {}).get("selectedEntryPath") or "").strip()
    input_path = str(payload.get("path") or "").strip()
    if not input_path:
        return payload
    data_path = Path(input_path)
    path_kind = str(template.get("pathKind") or "directory")
    candidates = _candidate_entries(data_path, template_id, template)
    if selected_entry:
        candidate = next((item for item in candidates if item["entryPath"] == selected_entry), None)
        if candidate is None:
            raise DatabaseRegistryError("DATABASE_CANDIDATE_NOT_FOUND")
        return _payload_with_candidate(payload, candidate)
    if len(candidates) == 1:
        return _payload_with_candidate(payload, candidates[0])
    if len(candidates) > 1:
        detail = {
            "status": "multiple_candidates",
            "message": f"检测到多个 {template.get('label') or template_id} 数据库入口，请选择一个。",
            "templateId": template_id,
            "pathKind": path_kind,
            "inputPath": input_path,
            "candidates": candidates,
        }
        raise DatabaseCandidateConflictError(detail)
    return payload


def _payload_with_candidate(payload: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(payload.get("metadata") or {})
    metadata["inputPath"] = candidate["inputPath"]
    metadata["entryPath"] = candidate["entryPath"]
    metadata["resolvedCandidate"] = candidate
    return {
        **payload,
        "metadata": metadata,
    }


def _candidate_entries(data_path: Path, template_id: str, template: dict[str, Any]) -> list[dict[str, Any]]:
    path_kind = str(template.get("pathKind") or "directory")
    if path_kind == "directory":
        return [_candidate(data_path, input_path=data_path, path_kind=path_kind, template_id=template_id, evidence=list(template.get("requiredFiles") or []))]
    if path_kind == "prefix":
        return _prefix_candidates(data_path, template_id, template)
    if path_kind == "file":
        return _file_candidates(data_path, template_id, template)
    if path_kind == "primary_with_sidecars":
        return _primary_with_sidecar_candidates(data_path, template_id, template)
    return []


def _candidate(entry_path: Path, *, input_path: Path, path_kind: str, template_id: str, evidence: list[str]) -> dict[str, Any]:
    return {
        "label": entry_path.name or str(entry_path),
        "entryPath": str(entry_path),
        "inputPath": str(input_path),
        "pathKind": path_kind,
        "templateId": template_id,
        "evidence": evidence,
    }


def _prefix_candidates(data_path: Path, template_id: str, template: dict[str, Any]) -> list[dict[str, Any]]:
    if data_path.is_dir():
        prefixes = database_validation.prefix_alias_prefixes_in_directory(data_path, template)
        if not prefixes:
            prefixes = database_validation.complete_prefixes_in_directory(data_path, template)
        candidates = []
        for prefix in prefixes:
            evidence = _prefix_evidence(prefix, template)
            candidates.append(_candidate(prefix, input_path=data_path, path_kind="prefix", template_id=template_id, evidence=evidence))
        return candidates
    prefix = database_validation.resolve_prefix_path(data_path, template)
    if database_validation.prefix_structure_error(prefix, template):
        return []
    return [_candidate(prefix, input_path=data_path, path_kind="prefix", template_id=template_id, evidence=_prefix_evidence(prefix, template))]


def _prefix_evidence(prefix: Path, template: dict[str, Any]) -> list[str]:
    for pattern in template.get("prefixAliasPatterns") or []:
        pattern_text = str(pattern)
        if not pattern_text.startswith("*"):
            continue
        alias_path = Path(str(prefix) + pattern_text[1:])
        if alias_path.exists():
            return [alias_path.name]
    for pattern_set in template.get("prefixPatternSets") or []:
        paths = [Path(str(prefix) + str(suffix)) for suffix in pattern_set]
        if all(path.exists() for path in paths):
            return [path.name for path in paths]
    return []


def _file_candidates(data_path: Path, template_id: str, template: dict[str, Any]) -> list[dict[str, Any]]:
    paths = database_validation.template_file_matches(data_path, template) if data_path.is_dir() else [data_path]
    candidates = []
    for path in paths:
        if path.is_file() and not database_validation.validate_template_file_path(path, template_id, template):
            candidates.append(_candidate(path, input_path=data_path, path_kind="file", template_id=template_id, evidence=[path.name]))
    return candidates


def _primary_with_sidecar_candidates(data_path: Path, template_id: str, template: dict[str, Any]) -> list[dict[str, Any]]:
    paths = database_validation.template_file_matches(data_path, template) if data_path.is_dir() else [data_path]
    candidates = []
    for path in paths:
        if path.is_file() and not database_validation.primary_with_sidecars_structure_error(path, template):
            evidence = [path.name, *[path.name + str(suffix) for suffix in template.get("indexSuffixes", [])]]
            candidates.append(_candidate(path, input_path=data_path, path_kind="primary_with_sidecars", template_id=template_id, evidence=evidence))
    return candidates
