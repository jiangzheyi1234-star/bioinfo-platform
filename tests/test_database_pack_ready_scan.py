from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from apps.remote_runner.api_models import DatabasePackReadyScanRequest
from apps.remote_runner.database_pack_catalog import list_downloadable_database_packs
from apps.remote_runner.database_pack_ready_scan import scan_database_pack_ready
from apps.remote_runner.database_service import scan_database_pack_ready_from_request
from apps.remote_runner.databases import list_reference_databases
from apps.remote_runner.governance_audit import list_governance_audit_events
from tests.helpers.reference_database import make_configured_remote_runner


DEFAULT_PACK_ID = "h2ometa-gtdbtk-r232-official"


def test_database_pack_ready_scan_reuses_template_checks_without_registry_mutation(tmp_path: Path) -> None:
    ready_dir = _make_gtdbtk_ready_dir(tmp_path / "gtdbtk-release")

    result = scan_database_pack_ready({"packId": DEFAULT_PACK_ID, "readyPath": str(ready_dir)})

    assert result["schemaVersion"] == "h2ometa.database-pack-ready-scan.v1"
    assert result["packId"] == DEFAULT_PACK_ID
    assert result["templateId"] == "gtdbtk"
    assert result["status"] == "ready"
    assert result["readyPath"] == str(ready_dir)
    assert result["entryPath"] == str(ready_dir)
    assert result["registrationPrefill"]["path"] == str(ready_dir)
    assert result["registrationPrefill"]["databaseLayer"] == "production_full"
    assert result["registrationPrefill"]["metadata"]["installedFromPackId"] == DEFAULT_PACK_ID
    assert result["redactionPolicy"]["registryMutated"] is False
    assert result["redactionPolicy"]["catalogMutated"] is False
    assert result["redactionPolicy"]["automaticExecution"] is False


def test_database_pack_ready_scan_reports_missing_path() -> None:
    result = scan_database_pack_ready({"packId": DEFAULT_PACK_ID, "readyPath": "/missing/h2ometa/gtdbtk"})

    assert result["status"] == "missing"
    assert "does not exist" in result["message"]


def test_database_pack_ready_scan_service_is_audited_and_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path, token="database-pack-ready-scan-token")
    ready_dir = _make_gtdbtk_ready_dir(tmp_path / "gtdbtk-release")
    monkeypatch.setattr("apps.remote_runner.database_service.authorized_config", lambda _authorization, **_kwargs: cfg)

    response = asyncio.run(
        scan_database_pack_ready_from_request(
            DatabasePackReadyScanRequest(packId=DEFAULT_PACK_ID, readyPath=str(ready_dir)),
            authorization=f"Bearer {cfg.token}",
        )
    )

    assert response["data"]["status"] == "ready"
    assert list_reference_databases(cfg) == []
    events = list_governance_audit_events(cfg, action="database_pack.ready_scan")["items"]
    assert len(events) == 1
    assert events[0]["subjectKind"] == "database-pack"
    assert events[0]["subjectId"] == DEFAULT_PACK_ID
    assert events[0]["details"]["status"] == "ready"
    assert events[0]["details"]["registryMutated"] is False
    assert events[0]["details"]["catalogMutated"] is False
    assert str(ready_dir) not in json.dumps(events[0], ensure_ascii=False)


def test_database_pack_ready_scan_route_stays_outside_immutable_catalog_subtree() -> None:
    route_source = Path("apps/remote_runner/database_routes.py").read_text(encoding="utf-8")
    api_route_source = Path("apps/api/database_routes.py").read_text(encoding="utf-8")

    assert '@router.post("/api/v1/database-pack-ready-scans")' in route_source
    assert '@router.post("/api/v1/database-pack-ready-scans")' in api_route_source
    assert '@router.post("/api/v1/database-packs' not in route_source + api_route_source


def _make_gtdbtk_ready_dir(base_dir: Path) -> Path:
    pack = {item["packId"]: item for item in list_downloadable_database_packs()}[DEFAULT_PACK_ID]
    for name in pack["expectedFiles"]:
        target = base_dir / name
        if "." in target.name:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("metadata", encoding="utf-8")
        else:
            target.mkdir(parents=True, exist_ok=True)
    (base_dir / "metadata.txt").write_text("metadata", encoding="utf-8")
    return base_dir
