from __future__ import annotations

from pathlib import Path

from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from apps.remote_runner.database_templates import list_database_templates
from apps.remote_runner.databases import add_reference_database
from apps.remote_runner.workflow_resources import build_workflow_resource_config


def _cfg(tmp_path: Path) -> RemoteRunnerConfig:
    return RemoteRunnerConfig(
        token="database-runtime-shape-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(Path.cwd() / "apps" / "remote_runner"),
    )


def test_database_templates_expose_runtime_shape_and_capabilities() -> None:
    templates = {item["id"]: item for item in list_database_templates()}

    assert templates["kraken2"]["runtimeShape"]["kind"] == "scalarPath"
    assert "taxonomy_database" in templates["kraken2"]["capabilities"]
    assert templates["blast"]["runtimeShape"]["kind"] == "prefix"
    assert "indexed_database" in templates["blast"]["capabilities"]
    assert templates["humann"]["runtimeShape"]["kind"] == "namedEntries"
    assert "multi_asset_database" in templates["humann"]["capabilities"]


def test_workflow_resource_config_checks_database_capabilities(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    db_path = tmp_path / "custom-db"
    db_path.mkdir()
    (db_path / "README.txt").write_text("custom database\n", encoding="utf-8")
    add_reference_database(
        cfg,
        {
            "id": "db_custom",
            "name": "Custom DB",
            "templateId": "custom",
            "version": "2026.05",
            "path": str(db_path),
        },
    )

    resolved = build_workflow_resource_config(
        cfg,
        workflow_resource_spec={
            "reference_database": {
                "type": "database",
                "acceptedCapabilities": ["reference_database"],
            }
        },
        bindings={"reference_database": {"databaseId": "db_custom"}},
    )

    resource = resolved["resources"]["reference_database"]
    assert resolved["config"]["reference_database"] == str(db_path)
    assert resource["runtimeShape"]["kind"] == "scalarPath"
    assert "reference_database" in resource["capabilities"]


def test_workflow_resource_config_rejects_missing_database_capability(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    db_path = tmp_path / "custom-db"
    db_path.mkdir()
    (db_path / "README.txt").write_text("custom database\n", encoding="utf-8")
    add_reference_database(
        cfg,
        {
            "id": "db_custom",
            "name": "Custom DB",
            "templateId": "custom",
            "version": "2026.05",
            "path": str(db_path),
        },
    )

    try:
        build_workflow_resource_config(
            cfg,
            workflow_resource_spec={
                "taxonomy_database": {
                    "type": "database",
                    "acceptedCapabilities": ["taxonomy_database"],
                }
            },
            bindings={"taxonomy_database": {"databaseId": "db_custom"}},
        )
    except ValueError as exc:
        assert str(exc) == "WORKFLOW_RESOURCE_CAPABILITY_UNSUPPORTED: taxonomy_database"
    else:
        raise AssertionError("database capability mismatch should be rejected")
