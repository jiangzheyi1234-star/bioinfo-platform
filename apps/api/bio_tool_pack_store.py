"""Persistent Bio Tool Pack review/import/enable registry."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from config import get_app_data_dir

from .bio_tool_pack_acceptance import reliability_acceptance_matrix
from .bio_tool_pack_capability_graph import semantic_capability_graph
from .bio_tool_pack_manifest import BioToolPackManifestError, load_bio_tool_pack_manifest
from .tool_profile_definitions import TOOL_PROFILES
from .tool_profile_identity import profile_tool_name
from .tool_profile_model import ToolProfile


REGISTRY_VERSION = 1
REVIEW_CONTRACT_VERSION = "bio-tool-pack-import-review-v1"


class BioToolPackRegistryError(ValueError):
    """Raised when the Bio Tool Pack registry cannot be safely updated."""


def get_bio_tool_pack_registry_path() -> Path:
    return get_app_data_dir() / "tool-packs" / "registry-v1.json"


def review_bio_tool_pack_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    normalized = _json_clone(manifest)
    profiles = load_bio_tool_pack_manifest(normalized)
    matrix = reliability_acceptance_matrix(profiles)
    graph = semantic_capability_graph(profiles=profiles)
    failed = int(matrix.get("summary", {}).get("failed") or 0)
    return {
        "contractVersion": REVIEW_CONTRACT_VERSION,
        "pack": _manifest_summary(normalized, profiles),
        "decision": {
            "status": "AcceptedForImport" if failed == 0 else "Rejected",
            "canImport": failed == 0,
            "canEnable": failed == 0,
            "reason": "" if failed == 0 else "BIO_TOOL_PACK_ACCEPTANCE_FAILED",
        },
        "acceptance": matrix,
        "capabilityGraph": graph,
    }


def import_bio_tool_pack_manifest(
    manifest: dict[str, Any],
    *,
    enable: bool = False,
    registry_path: Path | None = None,
) -> dict[str, Any]:
    path = registry_path or get_bio_tool_pack_registry_path()
    normalized = _json_clone(manifest)
    review = review_bio_tool_pack_manifest(normalized)
    profiles = load_bio_tool_pack_manifest(normalized)
    pack_id = _pack_id(normalized)
    registry = _read_registry(path)
    _assert_unique_profile_ids(pack_id, profiles, registry)
    now = _now()
    record = {
        "packId": pack_id,
        "version": str(normalized.get("version") or ""),
        "name": str(normalized.get("name") or pack_id),
        "status": "Enabled" if enable else "Imported",
        "enabled": bool(enable),
        "profileCount": len(profiles),
        "profileIds": [profile.profile_id for profile in profiles],
        "importedAt": now,
        "enabledAt": now if enable else "",
        "manifest": normalized,
        "acceptanceSummary": dict(review.get("acceptance", {}).get("summary") or {}),
    }
    _upsert_record(registry, record)
    _write_registry(path, registry)
    return {"pack": _public_record(record), "review": review}


def enable_bio_tool_pack(pack_id: str, *, registry_path: Path | None = None) -> dict[str, Any]:
    path = registry_path or get_bio_tool_pack_registry_path()
    registry = _read_registry(path)
    record = _find_record(registry, pack_id)
    manifest = _record_manifest(record)
    profiles = load_bio_tool_pack_manifest(manifest)
    _assert_unique_profile_ids(_pack_id(manifest), profiles, registry)
    review = review_bio_tool_pack_manifest(manifest)
    record["status"] = "Enabled"
    record["enabled"] = True
    record["enabledAt"] = _now()
    record["acceptanceSummary"] = dict(review.get("acceptance", {}).get("summary") or {})
    _write_registry(path, registry)
    return {"pack": _public_record(record), "review": review}


def disable_bio_tool_pack(pack_id: str, *, registry_path: Path | None = None) -> dict[str, Any]:
    path = registry_path or get_bio_tool_pack_registry_path()
    registry = _read_registry(path)
    record = _find_record(registry, pack_id)
    record["status"] = "Imported"
    record["enabled"] = False
    record["enabledAt"] = ""
    _write_registry(path, registry)
    return {"pack": _public_record(record)}


def list_bio_tool_packs(*, registry_path: Path | None = None) -> dict[str, Any]:
    registry = _read_registry(registry_path or get_bio_tool_pack_registry_path())
    items = [_public_record(record) for record in _records(registry)]
    enabled = sum(1 for item in items if item.get("enabled") is True)
    return {
        "registryVersion": REGISTRY_VERSION,
        "items": items,
        "summary": {"total": len(items), "enabled": enabled, "imported": len(items) - enabled},
    }


def enabled_bio_tool_pack_profiles(*, registry_path: Path | None = None) -> tuple[ToolProfile, ...]:
    registry = _read_registry(registry_path or get_bio_tool_pack_registry_path(), missing_ok=True)
    profiles: list[ToolProfile] = []
    for record in _records(registry):
        if record.get("enabled") is not True:
            continue
        profiles.extend(load_bio_tool_pack_manifest(_record_manifest(record)))
    return tuple(profiles)


def _assert_unique_profile_ids(
    pack_id: str,
    profiles: tuple[ToolProfile, ...],
    registry: dict[str, Any],
) -> None:
    reserved = {profile.profile_id for profile in TOOL_PROFILES}
    reserved_tool_ids = {profile_tool_name(profile) for profile in TOOL_PROFILES}
    for record in _records(registry):
        if str(record.get("packId") or "") == pack_id:
            continue
        reserved.update(str(value) for value in record.get("profileIds") or [] if str(value or ""))
        reserved_manifest = _record_manifest(record)
        for profile in load_bio_tool_pack_manifest(reserved_manifest):
            reserved_tool_ids.add(profile_tool_name(profile))
    duplicates = sorted(profile.profile_id for profile in profiles if profile.profile_id in reserved)
    if duplicates:
        raise BioToolPackManifestError(f"BIO_TOOL_PACK_PROFILE_ID_DUPLICATE: {duplicates[0]}")
    tool_id_duplicates = sorted(profile_tool_name(profile) for profile in profiles if profile_tool_name(profile) in reserved_tool_ids)
    if tool_id_duplicates:
        raise BioToolPackManifestError(f"BIO_TOOL_PACK_PROFILE_TOOL_ID_DUPLICATE: {tool_id_duplicates[0]}")


def _read_registry(path: Path, *, missing_ok: bool = False) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"version": REGISTRY_VERSION, "packs": []}
    except json.JSONDecodeError as exc:
        raise BioToolPackRegistryError("BIO_TOOL_PACK_REGISTRY_INVALID_JSON") from exc
    if not isinstance(payload, dict) or int(payload.get("version") or 0) != REGISTRY_VERSION:
        raise BioToolPackRegistryError("BIO_TOOL_PACK_REGISTRY_VERSION_UNSUPPORTED")
    if not isinstance(payload.get("packs"), list):
        raise BioToolPackRegistryError("BIO_TOOL_PACK_REGISTRY_PACKS_INVALID")
    return payload


def _write_registry(path: Path, registry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def _records(registry: dict[str, Any]) -> list[dict[str, Any]]:
    return [record for record in registry.get("packs") or [] if isinstance(record, dict)]


def _find_record(registry: dict[str, Any], pack_id: str) -> dict[str, Any]:
    wanted = str(pack_id or "").strip()
    for record in _records(registry):
        if str(record.get("packId") or "") == wanted:
            return record
    raise BioToolPackRegistryError("BIO_TOOL_PACK_NOT_FOUND")


def _upsert_record(registry: dict[str, Any], record: dict[str, Any]) -> None:
    packs = registry.setdefault("packs", [])
    for index, current in enumerate(_records(registry)):
        if current.get("packId") == record["packId"]:
            packs[index] = record
            return
    packs.append(record)


def _record_manifest(record: dict[str, Any]) -> dict[str, Any]:
    manifest = record.get("manifest")
    if not isinstance(manifest, dict):
        raise BioToolPackRegistryError("BIO_TOOL_PACK_RECORD_MANIFEST_INVALID")
    return _json_clone(manifest)


def _manifest_summary(manifest: dict[str, Any], profiles: tuple[ToolProfile, ...]) -> dict[str, Any]:
    return {
        "packId": _pack_id(manifest),
        "version": str(manifest.get("version") or ""),
        "name": str(manifest.get("name") or _pack_id(manifest)),
        "source": str(manifest.get("source") or ""),
        "license": str(manifest.get("license") or ""),
        "profileCount": len(profiles),
        "profileIds": [profile.profile_id for profile in profiles],
    }


def _public_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "packId": str(record.get("packId") or ""),
        "version": str(record.get("version") or ""),
        "name": str(record.get("name") or ""),
        "status": str(record.get("status") or "Imported"),
        "enabled": record.get("enabled") is True,
        "profileCount": int(record.get("profileCount") or 0),
        "profileIds": list(record.get("profileIds") or []),
        "importedAt": str(record.get("importedAt") or ""),
        "enabledAt": str(record.get("enabledAt") or ""),
        "acceptanceSummary": dict(record.get("acceptanceSummary") or {}),
    }


def _pack_id(manifest: dict[str, Any]) -> str:
    pack_id = str(manifest.get("packId") or "").strip()
    if not pack_id:
        raise BioToolPackManifestError("BIO_TOOL_PACK_ID_REQUIRED")
    return pack_id


def _json_clone(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BioToolPackManifestError("BIO_TOOL_PACK_MANIFEST_REQUIRED")
    return json.loads(json.dumps(deepcopy(value), ensure_ascii=False))


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
