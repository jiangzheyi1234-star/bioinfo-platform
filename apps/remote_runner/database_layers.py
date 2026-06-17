from __future__ import annotations

from typing import Any

from .database_errors import DatabaseRegistryError


DATABASE_LAYER_PRODUCTION_FULL = "production_full"
DATABASE_LAYER_VALIDATION_FIXTURE = "validation_fixture"
DATABASE_LAYER_USER_MANUAL = "user_manual"
DATABASE_LAYER_DOWNLOADABLE_PACK = "downloadable_pack"
DATABASE_LAYER_UNSPECIFIED = "unspecified"

DATABASE_LAYERS = {
    DATABASE_LAYER_PRODUCTION_FULL,
    DATABASE_LAYER_VALIDATION_FIXTURE,
    DATABASE_LAYER_USER_MANUAL,
    DATABASE_LAYER_DOWNLOADABLE_PACK,
}

REGISTERABLE_DATABASE_LAYERS = {
    DATABASE_LAYER_PRODUCTION_FULL,
    DATABASE_LAYER_VALIDATION_FIXTURE,
    DATABASE_LAYER_USER_MANUAL,
}

PRODUCTION_EVIDENCE_DATABASE_LAYERS = {
    DATABASE_LAYER_PRODUCTION_FULL,
    DATABASE_LAYER_USER_MANUAL,
}


def normalize_database_layer(payload: dict[str, Any], metadata: dict[str, Any]) -> str:
    layer = str(
        payload.get("databaseLayer")
        or payload.get("layer")
        or metadata.get("databaseLayer")
        or DATABASE_LAYER_USER_MANUAL
    ).strip()
    if layer not in DATABASE_LAYERS:
        raise DatabaseRegistryError("DATABASE_LAYER_UNSUPPORTED")
    if layer == DATABASE_LAYER_DOWNLOADABLE_PACK:
        raise DatabaseRegistryError("DATABASE_LAYER_DOWNLOADABLE_PACK_NOT_REGISTERABLE")
    return layer


def layer_metadata(metadata: dict[str, Any], layer: str) -> dict[str, Any]:
    normalized = dict(metadata)
    normalized["databaseLayer"] = layer
    normalized["productionEligible"] = layer in PRODUCTION_EVIDENCE_DATABASE_LAYERS
    return normalized


def database_layer(item: dict[str, Any]) -> str:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    layer = str(metadata.get("databaseLayer") or item.get("databaseLayer") or "").strip()
    return layer if layer in DATABASE_LAYERS else DATABASE_LAYER_UNSPECIFIED


def production_evidence_database_layer_supported(item: dict[str, Any]) -> bool:
    return database_layer(item) in PRODUCTION_EVIDENCE_DATABASE_LAYERS
