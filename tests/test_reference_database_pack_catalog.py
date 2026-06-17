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
    build_database_pack_catalog,
    list_downloadable_database_packs,
)
from apps.remote_runner.database_templates import DATABASE_TEMPLATES
from apps.remote_runner.databases import list_reference_databases
from scripts.register_gtdbtk_r232_database import (
    GTDBTK_R232_ARCHIVE_BYTES,
    GTDBTK_R232_MD5,
    GTDBTK_R232_SOURCE_URL,
)
from tests.helpers.reference_database import make_configured_remote_runner


REQUIRED_PACK_FIELDS = {
    "packId",
    "templateId",
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
    "archiveSizeBytes",
    "installedLayer",
    "license",
    "citations",
}


def test_downloadable_database_pack_catalog_publishes_positive_contract() -> None:
    packs = list_downloadable_database_packs()

    assert packs
    for pack in packs:
        assert set(pack) == REQUIRED_PACK_FIELDS
        assert pack["templateId"] in DATABASE_TEMPLATES
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


def test_gtdbtk_r232_downloadable_pack_matches_registration_contract() -> None:
    packs = {item["packId"]: item for item in list_downloadable_database_packs()}

    assert packs["h2ometa-gtdbtk-r232-official"] == {
        "packId": "h2ometa-gtdbtk-r232-official",
        "templateId": "gtdbtk",
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
        "archiveSizeBytes": GTDBTK_R232_ARCHIVE_BYTES,
        "installedLayer": DATABASE_LAYER_PRODUCTION_FULL,
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
    assert result["data"]["items"] == list_downloadable_database_packs()
    assert result["data"]["summary"] == {"total": len(result["data"]["items"])}
    assert list_reference_databases(cfg) == []


def test_database_pack_catalog_does_not_add_download_or_install_routes() -> None:
    route_source = Path("apps/remote_runner/database_routes.py").read_text(encoding="utf-8")
    service_source = Path("apps/remote_runner/database_service.py").read_text(encoding="utf-8")
    catalog_source = Path("apps/remote_runner/database_pack_catalog.py").read_text(encoding="utf-8")

    assert '@router.post("/api/v1/database-packs' not in route_source
    assert "install_database_pack" not in route_source + service_source + catalog_source
    assert "download_database_pack" not in route_source + service_source + catalog_source
