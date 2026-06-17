from __future__ import annotations

from typing import Any

from .database_layers import (
    DATABASE_LAYER_DOWNLOADABLE_PACK,
    DATABASE_LAYER_PRODUCTION_FULL,
    REGISTERABLE_DATABASE_LAYERS,
)
from .database_template_catalog import build_database_template_catalog
from .database_template_definitions import DATABASE_TEMPLATES


DATABASE_PACK_CATALOG_CONTRACT_VERSION = "database-pack-catalog-v1"


_REQUIRED_PACK_FIELDS = (
    "packId",
    "templateId",
    "databaseLayer",
    "sourceUrl",
    "checksum",
    "archiveSizeBytes",
    "installedLayer",
)

_DOWNLOADABLE_DATABASE_PACKS: tuple[dict[str, Any], ...] = (
    {
        "packId": "h2ometa-gtdbtk-r232-official",
        "templateId": "gtdbtk",
        "databaseLayer": DATABASE_LAYER_DOWNLOADABLE_PACK,
        "name": "GTDB-Tk R232 official reference pack",
        "version": "R232",
        "sourceUrl": (
            "https://data.gtdb.aau.ecogenomic.org/releases/release232/232.0/"
            "auxillary_files/gtdbtk_package/full_package/gtdbtk_r232_data.tar.gz"
        ),
        "checksum": "md5:25a59e0352b1fd150c589f56559767d4",
        "archiveSizeBytes": 60806405195,
        "installedLayer": DATABASE_LAYER_PRODUCTION_FULL,
        "license": "",
        "citations": [],
    },
)


def list_downloadable_database_packs() -> list[dict[str, Any]]:
    return build_database_pack_catalog(_DOWNLOADABLE_DATABASE_PACKS, DATABASE_TEMPLATES)


def database_pack_catalog_response() -> dict[str, Any]:
    items = list_downloadable_database_packs()
    return {
        "contractVersion": DATABASE_PACK_CATALOG_CONTRACT_VERSION,
        "items": items,
        "summary": {"total": len(items)},
    }


def build_database_pack_catalog(
    packs: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    templates: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    template_catalog = {template["id"]: template for template in build_database_template_catalog(templates)}
    items = [_normalize_pack(pack, template_catalog) for pack in packs]
    return sorted(items, key=lambda item: (item["templateId"], item["packId"]))


def _normalize_pack(raw: dict[str, Any], templates: dict[str, dict[str, Any]]) -> dict[str, Any]:
    item = {field: raw.get(field) for field in _REQUIRED_PACK_FIELDS}
    missing = [field for field, value in item.items() if value is None or str(value).strip() == ""]
    if missing:
        raise ValueError(f"DATABASE_PACK_FIELD_REQUIRED: {missing[0]}")

    pack_id = str(item["packId"]).strip()
    template_id = str(item["templateId"]).strip().lower()
    database_layer = str(item["databaseLayer"]).strip()
    source_url = str(item["sourceUrl"]).strip()
    checksum = str(item["checksum"]).strip()
    installed_layer = str(item["installedLayer"]).strip()
    archive_size_bytes = _pack_size(item["archiveSizeBytes"])

    if template_id not in templates:
        raise ValueError(f"DATABASE_PACK_TEMPLATE_UNSUPPORTED: {template_id}")
    if database_layer != DATABASE_LAYER_DOWNLOADABLE_PACK:
        raise ValueError("DATABASE_PACK_LAYER_MUST_BE_DOWNLOADABLE")
    if installed_layer == DATABASE_LAYER_DOWNLOADABLE_PACK:
        raise ValueError("DATABASE_PACK_INSTALLED_LAYER_NOT_REGISTERABLE")
    if installed_layer not in REGISTERABLE_DATABASE_LAYERS:
        raise ValueError("DATABASE_PACK_INSTALLED_LAYER_UNSUPPORTED")
    if not checksum.startswith(("sha256:", "md5:")):
        raise ValueError("DATABASE_PACK_CHECKSUM_ALGORITHM_UNSUPPORTED")
    if not source_url.startswith(("https://", "s3://", "file://")):
        raise ValueError("DATABASE_PACK_SOURCE_UNSUPPORTED")

    template = templates[template_id]
    return {
        "packId": pack_id,
        "templateId": template_id,
        "databaseLayer": database_layer,
        "name": str(raw.get("name") or f"{template['name']} downloadable pack"),
        "version": str(raw.get("version") or "catalog"),
        "type": str(template.get("type") or "reference"),
        "category": str(template.get("category") or "custom"),
        "supportLevel": str(raw.get("supportLevel") or template.get("supportLevel") or "stable"),
        "pathKind": str(template.get("pathKind") or "directory"),
        "pathLabel": str(template.get("pathLabel") or "数据库目录"),
        "runtimeValue": str(template.get("runtimeValue") or "selected_path"),
        "runtimeShape": dict(template.get("runtimeShape") or {}),
        "capabilities": list(template.get("capabilities") or []),
        "expectedFiles": list(template.get("expectedFiles") or []),
        "sourceUrl": source_url,
        "checksum": checksum,
        "archiveSizeBytes": archive_size_bytes,
        "installedLayer": installed_layer,
        "license": str(raw.get("license") or ""),
        "citations": [str(item) for item in raw.get("citations") or [] if str(item).strip()],
    }


def _pack_size(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("DATABASE_PACK_SIZE_INVALID")
    try:
        size = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("DATABASE_PACK_SIZE_INVALID") from exc
    if size <= 0:
        raise ValueError("DATABASE_PACK_SIZE_INVALID")
    return size
