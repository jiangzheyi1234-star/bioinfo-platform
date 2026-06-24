from __future__ import annotations

from pathlib import Path

import pytest

from apps.remote_runner.artifact_product_service import export_result_package
from apps.remote_runner.result_package_lifecycle_service import retire_result_package_export
from apps.remote_runner.result_package_listing_service import list_result_package_exports
from apps.remote_runner.storage_core import get_connection
from tests.helpers.reference_database import make_configured_remote_runner
from tests.test_result_package_lifecycle import _create_exportable_result


def test_result_package_listing_returns_sanitized_lifecycle_inventory(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_exportable_result(cfg, "run_package_inventory")
    full_package = export_result_package(cfg, "res_run_package_inventory", include_artifacts=True)
    metadata_package = export_result_package(cfg, "res_run_package_inventory", include_artifacts=False)
    _set_package_created_at(cfg, full_package["packageExportId"], "2025-01-01T00:00:01Z")
    _set_package_created_at(cfg, metadata_package["packageExportId"], "2025-01-01T00:00:02Z")

    listing = list_result_package_exports(cfg, result_id="res_run_package_inventory")

    assert listing["schemaVersion"] == "h2ometa.result-package-export-list.v1"
    assert listing["resultId"] == "res_run_package_inventory"
    assert listing["lifecycleState"] == "all"
    assert [item["packageExportId"] for item in listing["items"]] == [
        metadata_package["packageExportId"],
        full_package["packageExportId"],
    ]
    assert {item["artifactPayloadMode"] for item in listing["items"]} == {"included", "metadata-only"}
    for item in listing["items"]:
        assert item["lifecycleState"] == "active"
        assert item["download"]["href"] == (
            f"/api/v1/results/res_run_package_inventory/exports/{item['packageExportId']}/download"
        )
        assert item["download"]["filename"].endswith(".zip")
        assert item["evidenceId"]
        assert "evidenceEventId" not in item
        assert "packagePath" not in item
        assert "packageUri" not in item
        assert "file://" not in repr(item)


def test_result_package_listing_keeps_retired_records_without_download(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_exportable_result(cfg, "run_package_retired_list")
    package = export_result_package(cfg, "res_run_package_retired_list", include_artifacts=False)

    retire_result_package_export(
        cfg,
        "res_run_package_retired_list",
        package["packageExportId"],
        confirmation="retire-result-package-export",
        actor="operator",
    )

    all_listing = list_result_package_exports(cfg, result_id="res_run_package_retired_list")
    retired_listing = list_result_package_exports(
        cfg,
        result_id="res_run_package_retired_list",
        lifecycle_state="retired",
    )
    active_listing = list_result_package_exports(
        cfg,
        result_id="res_run_package_retired_list",
        lifecycle_state="active",
    )

    assert all_listing["items"][0]["packageExportId"] == package["packageExportId"]
    assert all_listing["items"][0]["lifecycleState"] == "retired"
    assert "download" not in all_listing["items"][0]
    assert retired_listing["items"][0]["packageExportId"] == package["packageExportId"]
    assert active_listing["items"] == []


def test_result_package_listing_does_not_infer_lifecycle_from_zip_presence(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_exportable_result(cfg, "run_package_missing_zip_list")
    package = export_result_package(cfg, "res_run_package_missing_zip_list", include_artifacts=True)
    Path(package["packagePath"]).unlink()

    listing = list_result_package_exports(cfg, result_id="res_run_package_missing_zip_list")

    assert listing["items"][0]["packageExportId"] == package["packageExportId"]
    assert listing["items"][0]["lifecycleState"] == "active"
    assert listing["items"][0]["download"]["href"].endswith(f"/{package['packageExportId']}/download")


def test_result_package_listing_rejects_unsupported_filter(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_exportable_result(cfg, "run_package_bad_filter")
    export_result_package(cfg, "res_run_package_bad_filter", include_artifacts=False)

    with pytest.raises(ValueError, match="RESULT_PACKAGE_LIFECYCLE_STATE_UNSUPPORTED: deleted"):
        list_result_package_exports(
            cfg,
            result_id="res_run_package_bad_filter",
            lifecycle_state="deleted",
        )


def _set_package_created_at(cfg, package_export_id: str, created_at: str) -> None:
    with get_connection(cfg) as connection:
        connection.execute(
            "UPDATE result_package_exports SET created_at = ? WHERE package_export_id = ?",
            (created_at, package_export_id),
        )
        connection.commit()
