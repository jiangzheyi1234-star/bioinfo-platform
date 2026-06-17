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
DATABASE_PACK_LIFECYCLE_CONTRACT_VERSION = "database-pack-lifecycle-v1"
DATABASE_PACK_INSTALL_MODE_MANUAL_EXTERNAL = "manual_external"


_REQUIRED_PACK_FIELDS = (
    "packId",
    "templateId",
    "databaseLayer",
    "sourceUrl",
    "checksum",
    "archiveSizeBytes",
    "installedLayer",
    "manualInstall",
    "registrationHandoff",
    "evidencePolicy",
    "layerSeparation",
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
        "manualInstall": {
            "mode": DATABASE_PACK_INSTALL_MODE_MANUAL_EXTERNAL,
            "remoteRoot": "/home/zyserver/databases/gtdbtk-r232-official",
            "archivePath": "/home/zyserver/databases/gtdbtk-r232-official/download/gtdbtk_r232_data.tar.gz",
            "readyDirHint": "/home/zyserver/databases/gtdbtk-r232-official/extracted/release",
            "statusFile": "/home/zyserver/databases/gtdbtk-r232-official/status.tsv",
            "operatorSteps": [
                {
                    "step": "download",
                    "instruction": "Download the official archive on the remote runner host.",
                    "command": (
                        "mkdir -p /home/zyserver/databases/gtdbtk-r232-official/download && "
                        "curl -L --fail --continue-at - "
                        "--output /home/zyserver/databases/gtdbtk-r232-official/download/gtdbtk_r232_data.tar.gz "
                        "https://data.gtdb.aau.ecogenomic.org/releases/release232/232.0/"
                        "auxillary_files/gtdbtk_package/full_package/gtdbtk_r232_data.tar.gz"
                    ),
                },
                {
                    "step": "verify_checksum",
                    "instruction": "Verify the archive before extraction.",
                    "command": (
                        "printf '25a59e0352b1fd150c589f56559767d4  "
                        "/home/zyserver/databases/gtdbtk-r232-official/download/gtdbtk_r232_data.tar.gz\\n' "
                        "| md5sum -c -"
                    ),
                },
                {
                    "step": "extract",
                    "instruction": "Extract externally and confirm the ready directory contains the GTDB-Tk structure.",
                    "command": (
                        "mkdir -p /home/zyserver/databases/gtdbtk-r232-official/extracted && "
                        "tar -xzf /home/zyserver/databases/gtdbtk-r232-official/download/gtdbtk_r232_data.tar.gz "
                        "-C /home/zyserver/databases/gtdbtk-r232-official/extracted"
                    ),
                },
                {
                    "step": "declare_ready",
                    "instruction": "Write status.tsv only after archive, checksum, ready directory, and structure checks pass.",
                },
            ],
        },
        "registrationHandoff": {
            "mode": "local_api_script_after_manual_ready_status",
            "scriptPath": "scripts/register_gtdbtk_r232_database.py",
            "apiEndpoint": "/api/v1/databases",
            "databaseLayer": DATABASE_LAYER_PRODUCTION_FULL,
            "defaultDatabaseId": "p0-8c-gtdbtk-r232-official",
            "defaultRemoteRoot": "/home/zyserver/databases/gtdbtk-r232-official",
        },
        "evidencePolicy": {
            "productionEvidenceAllowed": True,
            "acceptedEvidenceType": "real-database-acceptance",
            "requiresRegisteredStatus": "available",
            "requiresTemplateId": "gtdbtk",
            "requiresDatabaseLayer": DATABASE_LAYER_PRODUCTION_FULL,
            "requiresRunResourceBinding": True,
            "rejectsCatalogLayerAsEvidence": True,
            "validationFixtureAccepted": False,
        },
        "layerSeparation": {
            "catalogLayer": DATABASE_LAYER_DOWNLOADABLE_PACK,
            "registrationLayer": DATABASE_LAYER_PRODUCTION_FULL,
            "manualUserLayer": "user_manual",
            "validationFixtureLayer": "validation_fixture",
            "catalogRegistryMutation": "none",
        },
        "license": "",
        "citations": [],
    },
)


def list_downloadable_database_packs() -> list[dict[str, Any]]:
    return build_database_pack_catalog(_DOWNLOADABLE_DATABASE_PACKS, DATABASE_TEMPLATES)


def downloadable_database_pack_by_id(pack_id: str) -> dict[str, Any] | None:
    normalized = str(pack_id or "").strip()
    if not normalized:
        return None
    for pack in list_downloadable_database_packs():
        if pack["packId"] == normalized:
            return pack
    return None


def database_pack_catalog_response() -> dict[str, Any]:
    items = list_downloadable_database_packs()
    return {
        "contractVersion": DATABASE_PACK_CATALOG_CONTRACT_VERSION,
        "lifecycleContractVersion": DATABASE_PACK_LIFECYCLE_CONTRACT_VERSION,
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
    manual_install = _normalize_manual_install(raw.get("manualInstall"))
    registration_handoff = _normalize_registration_handoff(raw.get("registrationHandoff"), installed_layer)
    evidence_policy = _normalize_evidence_policy(raw.get("evidencePolicy"), template_id, installed_layer)
    layer_separation = _normalize_layer_separation(raw.get("layerSeparation"), database_layer, installed_layer)
    return {
        "packId": pack_id,
        "templateId": template_id,
        "lifecycleContractVersion": DATABASE_PACK_LIFECYCLE_CONTRACT_VERSION,
        "installMode": DATABASE_PACK_INSTALL_MODE_MANUAL_EXTERNAL,
        "operatorActionRequired": True,
        "noAutomaticExecution": True,
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
        "checksumAlgorithm": checksum.split(":", 1)[0],
        "checksumValue": checksum.split(":", 1)[1],
        "archiveSizeBytes": archive_size_bytes,
        "installedLayer": installed_layer,
        "manualInstall": manual_install,
        "registrationHandoff": registration_handoff,
        "evidencePolicy": evidence_policy,
        "layerSeparation": layer_separation,
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


def _normalize_manual_install(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("DATABASE_PACK_MANUAL_INSTALL_REQUIRED")
    if str(raw.get("mode") or "").strip() != DATABASE_PACK_INSTALL_MODE_MANUAL_EXTERNAL:
        raise ValueError("DATABASE_PACK_INSTALL_MODE_UNSUPPORTED")
    steps = raw.get("operatorSteps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("DATABASE_PACK_OPERATOR_STEPS_REQUIRED")
    normalized_steps: list[dict[str, str]] = []
    for raw_step in steps:
        if not isinstance(raw_step, dict):
            raise ValueError("DATABASE_PACK_OPERATOR_STEP_INVALID")
        step = str(raw_step.get("step") or "").strip()
        instruction = str(raw_step.get("instruction") or "").strip()
        command = str(raw_step.get("command") or "").strip()
        if not step or not instruction:
            raise ValueError("DATABASE_PACK_OPERATOR_STEP_INVALID")
        normalized_steps.append(
            {
                "step": step,
                "instruction": instruction,
                **({"command": command} if command else {}),
            }
        )
    required_text_fields = ("remoteRoot", "archivePath", "readyDirHint", "statusFile")
    return {
        "mode": DATABASE_PACK_INSTALL_MODE_MANUAL_EXTERNAL,
        **{field: _required_text(raw, field) for field in required_text_fields},
        "operatorSteps": normalized_steps,
    }


def _normalize_registration_handoff(raw: Any, installed_layer: str) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise ValueError("DATABASE_PACK_REGISTRATION_HANDOFF_REQUIRED")
    database_layer = _required_text(raw, "databaseLayer")
    if database_layer != installed_layer:
        raise ValueError("DATABASE_PACK_REGISTRATION_LAYER_MISMATCH")
    if database_layer == DATABASE_LAYER_DOWNLOADABLE_PACK:
        raise ValueError("DATABASE_PACK_REGISTRATION_LAYER_NOT_REGISTERABLE")
    return {
        "mode": _required_text(raw, "mode"),
        "scriptPath": _required_text(raw, "scriptPath"),
        "apiEndpoint": _required_text(raw, "apiEndpoint"),
        "databaseLayer": database_layer,
        "defaultDatabaseId": _required_text(raw, "defaultDatabaseId"),
        "defaultRemoteRoot": _required_text(raw, "defaultRemoteRoot"),
    }


def _normalize_evidence_policy(raw: Any, template_id: str, installed_layer: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("DATABASE_PACK_EVIDENCE_POLICY_REQUIRED")
    if str(raw.get("acceptedEvidenceType") or "").strip() != "real-database-acceptance":
        raise ValueError("DATABASE_PACK_EVIDENCE_TYPE_UNSUPPORTED")
    if str(raw.get("requiresTemplateId") or "").strip().lower() != template_id:
        raise ValueError("DATABASE_PACK_EVIDENCE_TEMPLATE_MISMATCH")
    if str(raw.get("requiresDatabaseLayer") or "").strip() != installed_layer:
        raise ValueError("DATABASE_PACK_EVIDENCE_LAYER_MISMATCH")
    if bool(raw.get("validationFixtureAccepted")):
        raise ValueError("DATABASE_PACK_FIXTURE_EVIDENCE_UNSUPPORTED")
    if not bool(raw.get("rejectsCatalogLayerAsEvidence")):
        raise ValueError("DATABASE_PACK_CATALOG_EVIDENCE_MUST_BE_REJECTED")
    return {
        "productionEvidenceAllowed": bool(raw.get("productionEvidenceAllowed")),
        "acceptedEvidenceType": "real-database-acceptance",
        "requiresRegisteredStatus": _required_text(raw, "requiresRegisteredStatus"),
        "requiresTemplateId": template_id,
        "requiresDatabaseLayer": installed_layer,
        "requiresRunResourceBinding": bool(raw.get("requiresRunResourceBinding")),
        "rejectsCatalogLayerAsEvidence": True,
        "validationFixtureAccepted": False,
    }


def _normalize_layer_separation(raw: Any, catalog_layer: str, installed_layer: str) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise ValueError("DATABASE_PACK_LAYER_SEPARATION_REQUIRED")
    if str(raw.get("catalogLayer") or "").strip() != catalog_layer:
        raise ValueError("DATABASE_PACK_CATALOG_LAYER_MISMATCH")
    if str(raw.get("registrationLayer") or "").strip() != installed_layer:
        raise ValueError("DATABASE_PACK_REGISTRATION_LAYER_MISMATCH")
    return {
        "catalogLayer": catalog_layer,
        "registrationLayer": installed_layer,
        "manualUserLayer": _required_text(raw, "manualUserLayer"),
        "validationFixtureLayer": _required_text(raw, "validationFixtureLayer"),
        "catalogRegistryMutation": _required_text(raw, "catalogRegistryMutation"),
    }


def _required_text(raw: dict[str, Any], field: str) -> str:
    value = str(raw.get(field) or "").strip()
    if not value:
        raise ValueError(f"DATABASE_PACK_FIELD_REQUIRED: {field}")
    return value
