from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from apps.remote_runner.databases import (
    DATABASE_TEMPLATES,
    add_reference_database,
    check_reference_database,
    resolve_run_databases,
)
from apps.remote_runner.executor import run_snakemake_execution
from apps.remote_runner.storage import persist_upload
from core.remote_runner.manager import RemoteRunnerManager, RemoteRunnerManagerError
from tests.generated_workflow_test_helpers import generated_workflow_run_spec, upsert_ready_tool
from tests.helpers.reference_database import (
    expected_template_entry_path as _expected_template_entry_path,
    make_configured_remote_runner as _cfg,
    materialize_template_selection as _materialize_template_selection,
)


def test_hmmer_pfam_template_accepts_hmmpress_index(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    database_dir = tmp_path / "pfam"
    database_dir.mkdir()
    hmm_path = database_dir / "Pfam-A.hmm"
    hmm_path.write_text("hmm", encoding="utf-8")
    for suffix in ("h3f", "h3i", "h3m"):
        (database_dir / f"Pfam-A.hmm.{suffix}").write_text("index", encoding="utf-8")

    saved = add_reference_database(
        cfg,
        {
            "id": "pfam",
            "name": "Pfam",
            "templateId": "hmmer_pfam",
            "path": str(hmm_path),
        },
    )

    missing = check_reference_database(cfg, saved["id"])
    assert missing["status"] == "missing"
    assert "h3p" in missing["message"]

    (database_dir / "Pfam-A.hmm.h3p").write_text("index", encoding="utf-8")
    checked = check_reference_database(cfg, saved["id"])
    assert checked["status"] == "available"


def test_directory_templates_accept_required_files_with_matching_pattern(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    database_dir = tmp_path / "kaiju"
    database_dir.mkdir()
    (database_dir / "nodes.dmp").write_text("nodes", encoding="utf-8")
    (database_dir / "names.dmp").write_text("names", encoding="utf-8")
    (database_dir / "proteins.fmi").write_text("fmi", encoding="utf-8")

    saved = add_reference_database(
        cfg,
        {
            "id": "kaiju-db",
            "name": "Kaiju DB",
            "templateId": "kaiju",
            "path": str(database_dir),
        },
    )

    checked = check_reference_database(cfg, saved["id"])
    assert checked["status"] == "available"


def test_single_file_database_templates_validate_file_suffix(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    wrong_file = tmp_path / "random.txt"
    wrong_file.write_text("not a diamond database", encoding="utf-8")

    saved = add_reference_database(
        cfg,
        {
            "id": "diamond-file",
            "name": "DIAMOND file",
            "templateId": "diamond",
            "path": str(wrong_file),
        },
    )
    missing = check_reference_database(cfg, saved["id"])
    assert missing["status"] == "missing"
    assert "*.dmnd" in missing["message"]

    diamond_file = tmp_path / "nr.dmnd"
    diamond_file.write_text("diamond", encoding="utf-8")
    updated = add_reference_database(
        cfg,
        {
            "id": "diamond-file",
            "name": "DIAMOND file",
            "templateId": "diamond",
            "path": str(diamond_file),
        },
    )
    checked = check_reference_database(cfg, updated["id"])
    assert checked["status"] == "available"


def test_directory_database_templates_reject_file_paths(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    file_path = tmp_path / "hash.k2d"
    file_path.write_text("kraken", encoding="utf-8")

    saved = add_reference_database(
        cfg,
        {
            "id": "kraken-file",
            "name": "Kraken file",
            "templateId": "kraken2",
            "path": str(file_path),
        },
    )

    checked = check_reference_database(cfg, saved["id"])
    assert checked["status"] == "missing"
    assert "requires a directory" in checked["message"]


def test_declared_database_cannot_be_resolved_for_generated_workflow(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    database_dir = tmp_path / "taxonomy-db"
    database_dir.mkdir()
    add_reference_database(
        cfg,
        {
            "id": "taxonomy-db",
            "name": "Taxonomy DB",
            "templateId": "custom",
            "type": "taxonomy",
            "path": str(database_dir),
            "status": "declared",
        },
    )
    try:
        resolve_run_databases(cfg, {"databases": [{"id": "taxonomy-db", "role": "taxonomy"}]})
    except ValueError as exc:
        assert "DATABASE_UNAVAILABLE" in str(exc)
    else:
        raise AssertionError("declared database should not be usable without validation")


def test_available_database_without_template_cannot_be_resolved_for_generated_workflow(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    database_dir = tmp_path / "template-free-db"
    database_dir.mkdir()
    add_reference_database(
        cfg,
        {
            "id": "template-free-db",
            "name": "Template-free DB",
            "type": "taxonomy",
            "path": str(database_dir),
            "status": "available",
        },
    )

    try:
        resolve_run_databases(cfg, {"databases": [{"id": "template-free-db", "role": "taxonomy"}]})
    except ValueError as exc:
        assert "DATABASE_TEMPLATE_REQUIRED" in str(exc)
    else:
        raise AssertionError("database without template should not be usable by generated workflows")


def test_custom_database_template_uses_declared_expected_files(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    database_dir = tmp_path / "custom-db"
    database_dir.mkdir()
    (database_dir / "README.txt").write_text("custom", encoding="utf-8")

    saved = add_reference_database(
        cfg,
        {
            "id": "custom-db",
            "name": "Custom DB",
            "templateId": "custom",
            "path": str(database_dir),
            "metadata": {"expectedFiles": ["manifest.json"]},
        },
    )
    missing = check_reference_database(cfg, saved["id"])
    assert missing["status"] == "missing"
    assert "manifest.json" in missing["message"]

    (database_dir / "manifest.json").write_text("{}", encoding="utf-8")
    checked = check_reference_database(cfg, saved["id"])
    assert checked["status"] == "available"


def test_generated_workflow_writes_database_config_and_path_token(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    database_dir = tmp_path / "taxonomy-db"
    database_dir.mkdir()
    (database_dir / "manifest.txt").write_text("taxonomy", encoding="utf-8")
    add_reference_database(
        cfg,
        {
            "id": "taxonomy-db",
            "name": "Taxonomy DB",
            "templateId": "custom",
            "type": "taxonomy",
            "version": "v1",
            "path": str(database_dir),
            "status": "available",
        },
    )
    upsert_ready_tool(
        cfg,
        {
            "id": "conda-forge::coreutils-db",
            "name": "coreutils",
            "source": "conda-forge",
            "sourceLabel": "conda-forge",
            "version": "9.5",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "printf '%s\\n' {config.taxonomy:q} > {output.tool_output:q}",
                "inputs": [{"name": "primary", "type": "file", "required": True}],
                "outputs": [{"name": "tool_output", "path": "database-path.txt", "kind": "log", "mimeType": "text/plain"}],
                "params": {},
                "resources": {
                    "threads": {"default": 1},
                    "mem_mb": {"default": 128},
                    "taxonomy": {"type": "database", "configKey": "taxonomy"},
                },
                "log": "logs/coreutils-db.log",
            },
        },
    )
    upload = persist_upload(
        cfg,
        filename="reads.txt",
        content_base64="QUJDREVGCg==",
        mime_type="text/plain",
    )

    class Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    monkeypatch.setattr("apps.remote_runner.executor.subprocess.run", lambda *_args, **_kwargs: Result())
    monkeypatch.setattr("apps.remote_runner.executor._collect_artifacts", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("apps.remote_runner.executor.update_run_state", lambda *args, **kwargs: None)
    monkeypatch.setattr("apps.remote_runner.executor.append_log_lines", lambda *args, **kwargs: None)

    run_spec = generated_workflow_run_spec(
        "conda-forge::coreutils-db",
        project_id="proj_demo",
        resource_bindings={"taxonomy": {"databaseId": "taxonomy-db"}},
    )
    run_spec["inputs"] = [{"uploadId": upload["uploadId"], "filename": "reads.txt", "role": "input"}]

    run_snakemake_execution(
        cfg,
        run_id="run_database_config",
        request_id="req_database_config",
        run_spec=run_spec,
    )

    work_dir = Path(cfg.work_dir) / "run_database_config"
    run_config = json.loads((work_dir / "run-config.json").read_text(encoding="utf-8"))
    snakefile = (work_dir / "workflow" / "Snakefile").read_text(encoding="utf-8")

    resource = run_config["resources"]["taxonomy"]
    assert run_config["databases"]["taxonomy"] == str(database_dir)
    assert run_config["resourceConfig"]["taxonomy"] == str(database_dir)
    assert resource["path"] == str(database_dir)
    assert resource["inputPath"] == str(database_dir)
    assert resource["entryPath"] == str(database_dir)
    assert resource["pathMode"] == "directory"
    assert str(database_dir) not in snakefile
    assert "{config[databases][taxonomy]:q}" in snakefile
    assert "{config.taxonomy:q}" not in snakefile


def test_every_database_template_can_be_checked_and_injected_into_generated_workflow(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    upload = persist_upload(
        cfg,
        filename="reads.txt",
        content_base64="QUJDREVGCg==",
        mime_type="text/plain",
    )

    class Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    monkeypatch.setattr("apps.remote_runner.executor.subprocess.run", lambda *_args, **_kwargs: Result())
    monkeypatch.setattr("apps.remote_runner.executor._collect_artifacts", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("apps.remote_runner.executor.update_run_state", lambda *args, **kwargs: None)
    monkeypatch.setattr("apps.remote_runner.executor.append_log_lines", lambda *args, **kwargs: None)

    for template_id, template in DATABASE_TEMPLATES.items():
        _target, selected_path = _materialize_template_selection(tmp_path / "template-fixtures", template_id)
        database_id = f"{template_id}-fixture"
        role = "db"
        add_reference_database(
            cfg,
            {
                "id": database_id,
                "name": f"{template_id} fixture",
                "templateId": template_id,
                "path": str(selected_path),
                "status": "declared",
                "metadata": {"templateId": template_id},
            },
        )
        checked = check_reference_database(cfg, database_id)
        assert checked["status"] == "available", f"{template_id} should validate with selected directory {selected_path}"
        resolved_path = checked["metadata"].get("resolvedPath") or {}
        expected_path = _expected_template_entry_path(template, resolved_path, selected_path)

        tool_id = f"conda-forge::coreutils-{template_id}"
        upsert_ready_tool(
            cfg,
            {
                "id": tool_id,
                "name": "coreutils",
                "source": "conda-forge",
                "sourceLabel": "conda-forge",
                "version": "9.5",
                "packageSpec": "conda-forge::coreutils=9.5",
                "targetPlatform": "linux-64",
                "targetPlatformSupported": True,
                "ruleTemplate": {
                    "commandTemplate": f"printf '%s\\n' {{config.{role}:q}} > {{output.tool_output:q}}",
                    "inputs": [{"name": "primary", "type": "file", "required": True}],
                    "outputs": [{"name": "tool_output", "path": f"{template_id}-database-path.txt", "kind": "log", "mimeType": "text/plain"}],
                    "params": {},
                    "resources": {
                        "threads": {"default": 1},
                        "mem_mb": {"default": 128},
                        role: {
                            "type": "database",
                            "configKey": role,
                            "acceptedTemplates": [template_id],
                        }
                    },
                    "log": f"logs/coreutils-{template_id}.log",
                },
            },
        )

        run_id = f"run_{template_id}_database_path"
        run_spec = generated_workflow_run_spec(
            tool_id,
            project_id="proj_template_matrix",
            resource_bindings={role: {"databaseId": database_id}},
        )
        run_spec["inputs"] = [{"uploadId": upload["uploadId"], "filename": "reads.txt", "role": "input"}]

        run_snakemake_execution(
            cfg,
            run_id=run_id,
            request_id=f"req_{template_id}",
            run_spec=run_spec,
        )

        work_dir = Path(cfg.work_dir) / run_id
        run_config = json.loads((work_dir / "run-config.json").read_text(encoding="utf-8"))
        snakefile = (work_dir / "workflow" / "Snakefile").read_text(encoding="utf-8")
        resource = run_config["resources"][role]
        assert run_config["resourceConfig"][role] == run_config["databases"][role]
        assert resource["path"] == expected_path
        assert resource["inputPath"] == str(selected_path)
        assert resource["entryPath"] == expected_path
        assert resource["pathMode"] == template["pathKind"]
        if template["pathKind"] == "composite":
            assert resource["resolved"]
            assert run_config["databases"][role]
        else:
            assert run_config["databases"][role] == expected_path
            assert expected_path not in snakefile
        assert f"{{config[databases][{role}]:q}}" in snakefile
        assert f"{{config.{role}:q}}" not in snakefile


def test_remote_runner_manager_database_catalog_routes(monkeypatch) -> None:
    manager = RemoteRunnerManager()
    calls: list[tuple[str, str, Any]] = []
    client_timeouts: list[int | None] = []

    class FakeClient:
        def get_json(self, path: str) -> dict[str, Any]:
            calls.append(("GET", path, None))
            return {"data": {"items": [{"id": "db1"}]}}

        def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
            calls.append(("POST", path, payload))
            return {"data": {"id": "db1", **payload}}

        def delete_json(self, path: str) -> dict[str, Any]:
            calls.append(("DELETE", path, None))
            return {"data": {"id": "db1", "deleted": True}}

    def fake_get_client(**kwargs):
        client_timeouts.append(kwargs.get("timeout"))
        return FakeClient()

    monkeypatch.setattr(manager, "_get_client", fake_get_client)
    kwargs = {"server_id": "srv", "ssh_service": object(), "server_record": {}}

    assert manager.list_databases(**kwargs) == [{"id": "db1"}]
    assert manager.list_database_templates(**kwargs) == [{"id": "db1"}]
    assert manager.add_database(**kwargs, payload={"name": "db1"})["name"] == "db1"
    assert manager.check_database(**kwargs, database_id="db1")["id"] == "db1"
    assert manager.delete_database(**kwargs, database_id="db1")["deleted"] is True
    assert calls == [
        ("GET", "/api/v1/databases", None),
        ("GET", "/api/v1/database-templates", None),
        ("POST", "/api/v1/databases", {"name": "db1"}),
        ("POST", "/api/v1/databases/db1/check", {}),
        ("DELETE", "/api/v1/databases/db1", None),
    ]
    assert client_timeouts == [None, None, 2100, 2100, None]


def test_remote_runner_reuse_rejects_old_database_template_catalog() -> None:
    class FakeClient:
        def get_json(self, path: str) -> dict[str, Any]:
            assert path == "/api/v1/database-templates"
            return {"data": {"items": [{"id": "kraken2", "pathKind": "directory"}]}}

    try:
        RemoteRunnerManager._verify_database_template_catalog_for_reuse(FakeClient())
    except RemoteRunnerManagerError as exc:
        assert "missing category" in str(exc)
    else:
        raise AssertionError("old database template catalog should be rejected")


def test_remote_runner_reuse_accepts_database_template_catalog_contract() -> None:
    class FakeClient:
        def get_json(self, path: str) -> dict[str, Any]:
            assert path == "/api/v1/database-templates"
            return {
                "data": {
                    "items": [
                        {
                            "id": "kraken2",
                            "pathKind": "directory",
                            "category": "taxonomy",
                            "pathLabel": "数据库目录",
                            "runtimeValue": "selected_path",
                        }
                    ]
                }
            }

    RemoteRunnerManager._verify_database_template_catalog_for_reuse(FakeClient())


def test_remote_runner_reuse_rejects_prefix_template_without_pattern_sets() -> None:
    class FakeClient:
        def get_json(self, path: str) -> dict[str, Any]:
            assert path == "/api/v1/database-templates"
            return {
                "data": {
                    "items": [
                        {
                            "id": "blast",
                            "pathKind": "prefix",
                            "category": "alignment",
                            "pathLabel": "索引目录或索引文件",
                            "runtimeValue": "resolved_prefix",
                        }
                    ]
                }
            }

    try:
        RemoteRunnerManager._verify_database_template_catalog_for_reuse(FakeClient())
    except RemoteRunnerManagerError as exc:
        assert "missing prefixPatternSets" in str(exc)
    else:
        raise AssertionError("prefix template without prefixPatternSets should be rejected")


def test_remote_runner_database_validation_routes_run_in_threadpool() -> None:
    route_source = Path("apps/remote_runner/database_routes.py").read_text(encoding="utf-8")
    service_source = Path("apps/remote_runner/database_service.py").read_text(encoding="utf-8")

    assert "run_sync" not in route_source
    assert "from .route_utils import authorized_config, data_response, request_payload, run_sync" in service_source
    assert "await run_sync(add_verified_reference_database, cfg, request_payload(payload))" in service_source
    assert "await run_sync(check_reference_database, cfg, database_id)" in service_source
