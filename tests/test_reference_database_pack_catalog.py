from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from apps.remote_runner.database_layers import (
    DATABASE_LAYER_DOWNLOADABLE_PACK,
    DATABASE_LAYER_PRODUCTION_FULL,
    REGISTERABLE_DATABASE_LAYERS,
)
from apps.remote_runner.database_pack_catalog import (
    DATABASE_PACK_CATALOG_CONTRACT_VERSION,
    DATABASE_PACK_INSTALL_MODE_MANUAL_EXTERNAL,
    DATABASE_PACK_LIFECYCLE_CONTRACT_VERSION,
    build_database_pack_catalog,
    list_downloadable_database_packs,
)
from apps.remote_runner.database_templates import DATABASE_TEMPLATES
from apps.remote_runner.databases import list_reference_databases
from scripts.register_gtdbtk_r232_database import (
    DEFAULT_DATABASE_ID,
    DEFAULT_PACK_ID,
    DEFAULT_REMOTE_ROOT,
    GTDBTK_R232_ARCHIVE_BYTES,
    GTDBTK_R232_MD5,
    GTDBTK_R232_SOURCE_URL,
)
from tests.helpers.reference_database import make_configured_remote_runner


REQUIRED_PACK_FIELDS = {
    "packId",
    "templateId",
    "lifecycleContractVersion",
    "installMode",
    "operatorActionRequired",
    "noAutomaticExecution",
    "databaseLayer",
    "name",
    "version",
    "type",
    "category",
    "supportLevel",
    "pathKind",
    "pathLabel",
    "runtimeValue",
    "runtimeShape",
    "capabilities",
    "expectedFiles",
    "sourceUrl",
    "checksum",
    "checksumAlgorithm",
    "checksumValue",
    "archiveSizeBytes",
    "installedLayer",
    "manualInstall",
    "registrationHandoff",
    "evidencePolicy",
    "layerSeparation",
    "license",
    "citations",
}


def test_downloadable_database_pack_catalog_publishes_positive_contract() -> None:
    packs = list_downloadable_database_packs()

    assert packs
    for pack in packs:
        assert set(pack) == REQUIRED_PACK_FIELDS
        assert pack["templateId"] in DATABASE_TEMPLATES
        assert pack["lifecycleContractVersion"] == DATABASE_PACK_LIFECYCLE_CONTRACT_VERSION
        assert pack["installMode"] == DATABASE_PACK_INSTALL_MODE_MANUAL_EXTERNAL
        assert pack["operatorActionRequired"] is True
        assert pack["noAutomaticExecution"] is True
        assert pack["databaseLayer"] == DATABASE_LAYER_DOWNLOADABLE_PACK
        assert pack["name"]
        assert pack["version"]
        assert pack["pathKind"]
        assert pack["runtimeValue"]
        assert isinstance(pack["runtimeShape"], dict)
        assert isinstance(pack["capabilities"], list)
        assert isinstance(pack["expectedFiles"], list)
        assert pack["installedLayer"] in REGISTERABLE_DATABASE_LAYERS
        assert pack["installedLayer"] != DATABASE_LAYER_DOWNLOADABLE_PACK
        assert isinstance(pack["archiveSizeBytes"], int)
        assert pack["archiveSizeBytes"] > 0
        assert pack["sourceUrl"].startswith(("https://", "s3://", "file://"))
        assert pack["checksum"].startswith(("sha256:", "md5:"))
        assert pack["checksum"] == f"{pack['checksumAlgorithm']}:{pack['checksumValue']}"
        assert pack["manualInstall"]["mode"] == DATABASE_PACK_INSTALL_MODE_MANUAL_EXTERNAL
        assert pack["manualInstall"]["operatorSteps"]
        assert pack["registrationHandoff"]["databaseLayer"] == pack["installedLayer"]
        assert pack["evidencePolicy"]["acceptedEvidenceType"] == "real-database-acceptance"
        assert pack["evidencePolicy"]["requiresDatabaseLayer"] == pack["installedLayer"]
        assert pack["evidencePolicy"]["rejectsCatalogLayerAsEvidence"] is True
        assert pack["evidencePolicy"]["validationFixtureAccepted"] is False
        assert pack["layerSeparation"]["catalogLayer"] == DATABASE_LAYER_DOWNLOADABLE_PACK
        assert pack["layerSeparation"]["registrationLayer"] == pack["installedLayer"]
        assert pack["layerSeparation"]["catalogRegistryMutation"] == "none"


def test_gtdbtk_r232_downloadable_pack_matches_registration_contract() -> None:
    packs = {item["packId"]: item for item in list_downloadable_database_packs()}

    assert packs["h2ometa-gtdbtk-r232-official"] == {
        "packId": DEFAULT_PACK_ID,
        "templateId": "gtdbtk",
        "lifecycleContractVersion": DATABASE_PACK_LIFECYCLE_CONTRACT_VERSION,
        "installMode": DATABASE_PACK_INSTALL_MODE_MANUAL_EXTERNAL,
        "operatorActionRequired": True,
        "noAutomaticExecution": True,
        "databaseLayer": DATABASE_LAYER_DOWNLOADABLE_PACK,
        "name": "GTDB-Tk R232 official reference pack",
        "version": "R232",
        "type": "taxonomy",
        "category": "taxonomy",
        "supportLevel": "stable",
        "pathKind": "directory",
        "pathLabel": "GTDB-Tk 数据目录",
        "runtimeValue": "selected_path",
        "runtimeShape": {"kind": "scalarPath", "valueKey": "default", "jsonType": "string"},
        "capabilities": ["taxonomy_database"],
        "expectedFiles": [
            "markers",
            "masks",
            "metadata",
            "mrca_red",
            "msa",
            "pplacer",
            "radii",
            "skani",
            "split",
            "taxonomy",
            "metadata.txt",
            "VERSION",
        ],
        "sourceUrl": GTDBTK_R232_SOURCE_URL,
        "checksum": f"md5:{GTDBTK_R232_MD5}",
        "checksumAlgorithm": "md5",
        "checksumValue": GTDBTK_R232_MD5,
        "archiveSizeBytes": GTDBTK_R232_ARCHIVE_BYTES,
        "installedLayer": DATABASE_LAYER_PRODUCTION_FULL,
        "manualInstall": {
            "mode": DATABASE_PACK_INSTALL_MODE_MANUAL_EXTERNAL,
            "remoteRoot": DEFAULT_REMOTE_ROOT,
            "archivePath": f"{DEFAULT_REMOTE_ROOT}/download/gtdbtk_r232_data.tar.gz",
            "readyDirHint": f"{DEFAULT_REMOTE_ROOT}/extracted/release",
            "statusFile": f"{DEFAULT_REMOTE_ROOT}/status.tsv",
            "operatorSteps": [
                {
                    "step": "download",
                    "instruction": "Download the official archive on the remote runner host.",
                    "command": (
                        f"mkdir -p {DEFAULT_REMOTE_ROOT}/download && "
                        "curl -L --fail --continue-at - "
                        f"--output {DEFAULT_REMOTE_ROOT}/download/gtdbtk_r232_data.tar.gz "
                        f"{GTDBTK_R232_SOURCE_URL}"
                    ),
                },
                {
                    "step": "verify_checksum",
                    "instruction": "Verify the archive before extraction.",
                    "command": (
                        f"printf '{GTDBTK_R232_MD5}  "
                        f"{DEFAULT_REMOTE_ROOT}/download/gtdbtk_r232_data.tar.gz\\n' | md5sum -c -"
                    ),
                },
                {
                    "step": "extract",
                    "instruction": "Extract externally and confirm the ready directory contains the GTDB-Tk structure.",
                    "command": (
                        f"mkdir -p {DEFAULT_REMOTE_ROOT}/extracted && "
                        f"tar -xzf {DEFAULT_REMOTE_ROOT}/download/gtdbtk_r232_data.tar.gz "
                        f"-C {DEFAULT_REMOTE_ROOT}/extracted"
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
            "defaultDatabaseId": DEFAULT_DATABASE_ID,
            "defaultRemoteRoot": DEFAULT_REMOTE_ROOT,
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
    }


def test_database_pack_catalog_rejects_invalid_contract_entries() -> None:
    valid_pack = list_downloadable_database_packs()[0]

    invalid_cases: list[tuple[str, dict[str, Any], str]] = [
        ("missing field", {**valid_pack, "packId": ""}, "DATABASE_PACK_FIELD_REQUIRED: packId"),
        ("unknown template", {**valid_pack, "templateId": "missing"}, "DATABASE_PACK_TEMPLATE_UNSUPPORTED: missing"),
        (
            "wrong layer",
            {**valid_pack, "databaseLayer": "user_manual"},
            "DATABASE_PACK_LAYER_MUST_BE_DOWNLOADABLE",
        ),
        (
            "non-registerable installed layer",
            {**valid_pack, "installedLayer": DATABASE_LAYER_DOWNLOADABLE_PACK},
            "DATABASE_PACK_INSTALLED_LAYER_NOT_REGISTERABLE",
        ),
        ("bad checksum", {**valid_pack, "checksum": "25a59e"}, "DATABASE_PACK_CHECKSUM_ALGORITHM_UNSUPPORTED"),
        ("bad source", {**valid_pack, "sourceUrl": "manual://pack"}, "DATABASE_PACK_SOURCE_UNSUPPORTED"),
        ("bad size", {**valid_pack, "archiveSizeBytes": 0}, "DATABASE_PACK_SIZE_INVALID"),
        (
            "automatic install",
            {**valid_pack, "manualInstall": {**valid_pack["manualInstall"], "mode": "automatic"}},
            "DATABASE_PACK_INSTALL_MODE_UNSUPPORTED",
        ),
        (
            "registration layer mismatch",
            {
                **valid_pack,
                "registrationHandoff": {**valid_pack["registrationHandoff"], "databaseLayer": "user_manual"},
            },
            "DATABASE_PACK_REGISTRATION_LAYER_MISMATCH",
        ),
        (
            "fixture evidence accepted",
            {
                **valid_pack,
                "evidencePolicy": {**valid_pack["evidencePolicy"], "validationFixtureAccepted": True},
            },
            "DATABASE_PACK_FIXTURE_EVIDENCE_UNSUPPORTED",
        ),
        (
            "catalog layer mismatch",
            {
                **valid_pack,
                "layerSeparation": {**valid_pack["layerSeparation"], "catalogLayer": "user_manual"},
            },
            "DATABASE_PACK_CATALOG_LAYER_MISMATCH",
        ),
    ]

    for _label, pack, message in invalid_cases:
        with pytest.raises(ValueError, match=message):
            build_database_pack_catalog([pack], DATABASE_TEMPLATES)


def test_remote_database_pack_route_is_read_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = make_configured_remote_runner(tmp_path, token="database-pack-catalog-token")
    monkeypatch.setattr("apps.remote_runner.route_utils.load_remote_runner_config", lambda: cfg)

    from apps.remote_runner.database_routes import get_database_packs

    result = asyncio.run(get_database_packs(authorization=f"Bearer {cfg.token}"))

    assert result["data"]["contractVersion"] == DATABASE_PACK_CATALOG_CONTRACT_VERSION
    assert result["data"]["lifecycleContractVersion"] == DATABASE_PACK_LIFECYCLE_CONTRACT_VERSION
    assert result["data"]["items"] == list_downloadable_database_packs()
    assert result["data"]["summary"] == {"total": len(result["data"]["items"])}
    assert list_reference_databases(cfg) == []


def test_database_pack_catalog_does_not_add_download_or_install_routes() -> None:
    route_source = Path("apps/remote_runner/database_routes.py").read_text(encoding="utf-8")
    service_source = Path("apps/remote_runner/database_service.py").read_text(encoding="utf-8")
    catalog_source = Path("apps/remote_runner/database_pack_catalog.py").read_text(encoding="utf-8")

    assert '@router.post("/api/v1/database-packs' not in route_source
    assert '@router.patch("/api/v1/database-packs' not in route_source
    assert '@router.delete("/api/v1/database-packs' not in route_source
    assert "install_database_pack" not in route_source + service_source + catalog_source
    assert "download_database_pack" not in route_source + service_source + catalog_source
