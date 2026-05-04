from __future__ import annotations

import json
from pathlib import Path

from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from apps.remote_runner.databases import DATABASE_TEMPLATES, add_reference_database
from apps.remote_runner.executor import run_snakemake_execution
from apps.remote_runner.generated_workflow import GENERATED_TOOL_RUN_PIPELINE_ID
from apps.remote_runner.storage import persist_upload, upsert_tool
from apps.remote_runner.workflow_resources import build_workflow_resource_config


def _cfg(tmp_path: Path) -> RemoteRunnerConfig:
    return RemoteRunnerConfig(
        token="workflow-resource-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(Path.cwd() / "apps" / "remote_runner"),
        managed_conda_command=str(tmp_path / "workflow-env" / "bin" / "conda"),
        snakemake_command=str(tmp_path / "workflow-env" / "bin" / "snakemake"),
    )


def _patch_tool_probe_success(monkeypatch) -> None:
    from apps.remote_runner import database_validation

    monkeypatch.setattr(
        database_validation,
        "prepare_tool_probe_command",
        lambda cfg, template_id, template, command: command,
    )
    monkeypatch.setattr(
        database_validation,
        "run_tool_probe",
        lambda command, *, timeout: database_validation.ToolProbeResult(
            ok=True,
            command=command,
            stdout="probe ok",
            stderr="",
            returncode=0,
        ),
    )


def test_workflow_resource_binding_injects_entry_path_by_config_key(tmp_path: Path, monkeypatch) -> None:
    _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    blast_dir = tmp_path / "blast"
    blast_dir.mkdir()
    for suffix in (".nhr", ".nin", ".nsq"):
        (blast_dir / f"nt{suffix}").write_text("index", encoding="utf-8")
    add_reference_database(
        cfg,
        {
            "id": "db_ncbi_nt",
            "name": "NCBI nt",
            "templateId": "blast",
            "path": str(blast_dir),
        },
    )

    result = build_workflow_resource_config(
        cfg,
        workflow_resource_spec={
            "blast_nt_db": {
                "label": "BLAST nt database",
                "required": True,
                "acceptedTemplates": ["blast"],
                "configKey": "blast_nt_db",
            }
        },
        bindings={"blast_nt_db": "db_ncbi_nt"},
    )

    assert result["config"]["blast_nt_db"] == str(blast_dir / "nt")
    assert result["resources"]["blast_nt_db"]["databaseId"] == "db_ncbi_nt"
    assert result["resources"]["blast_nt_db"]["templateId"] == "blast"
    assert result["resources"]["blast_nt_db"]["path"] == str(blast_dir / "nt")
    assert result["resources"]["blast_nt_db"]["resolved"] == {"default": str(blast_dir / "nt")}
    assert result["resources"]["blast_nt_db"]["input"] == {"kind": "single", "path": str(blast_dir)}
    assert result["resources"]["blast_nt_db"]["inputPath"] == str(blast_dir)
    assert result["resources"]["blast_nt_db"]["entryPath"] == str(blast_dir / "nt")
    assert result["resources"]["blast_nt_db"]["pathMode"] == "prefix"


def test_workflow_resource_binding_injects_composite_resolved_object(tmp_path: Path, monkeypatch) -> None:
    _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    nucleotide = tmp_path / "humann" / "chocophlan"
    protein = tmp_path / "humann" / "uniref"
    mapping = tmp_path / "humann" / "utility_mapping"
    for path in (nucleotide, protein, mapping):
        path.mkdir(parents=True)

    monkeypatch.setitem(
        DATABASE_TEMPLATES,
        "humann_composite_test",
        {
            "type": "functional_profile",
            "category": "annotation",
            "label": "HUMAnN composite",
            "icon": "taxonomy",
            "pathKind": "composite",
            "pathLabel": "HUMAnN 复合数据库",
            "runtimeValue": "resolved_entries",
            "description": "HUMAnN composite test",
            "pathHint": "",
            "fields": {
                "nucleotide": {"label": "ChocoPhlAn", "pathKind": "directory", "required": True},
                "protein": {"label": "UniRef", "pathKind": "directory", "required": True},
                "utility_mapping": {"label": "utility mapping", "pathKind": "directory", "required": True},
            },
        },
    )
    add_reference_database(
        cfg,
        {
            "id": "db_humann",
            "name": "HUMAnN",
            "templateId": "humann_composite_test",
            "path": str(nucleotide.parent),
            "metadata": {
                "input": {
                    "kind": "multi",
                    "fields": {
                        "nucleotide": str(nucleotide),
                        "protein": str(protein),
                        "utility_mapping": str(mapping),
                    },
                }
            },
        },
    )

    result = build_workflow_resource_config(
        cfg,
        workflow_resource_spec={
            "humann_db": {
                "required": True,
                "acceptedTemplates": ["humann_composite_test"],
                "configKey": "humann",
            }
        },
        bindings={"humann_db": "db_humann"},
    )

    assert result["config"]["humann"] == {
        "nucleotide": str(nucleotide),
        "protein": str(protein),
        "utility_mapping": str(mapping),
    }
    assert result["resources"]["humann_db"]["input"]["kind"] == "multi"
    assert result["resources"]["humann_db"]["resolved"] == result["config"]["humann"]
    assert result["resources"]["humann_db"]["pathMode"] == "composite"


def test_workflow_resource_binding_injects_builtin_humann_composite_object(tmp_path: Path, monkeypatch) -> None:
    _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    nucleotide = tmp_path / "humann" / "chocophlan"
    protein = tmp_path / "humann" / "uniref"
    mapping = tmp_path / "humann" / "utility_mapping"
    nucleotide.mkdir(parents=True)
    protein.mkdir()
    mapping.mkdir()
    (nucleotide / "genome.ffn.gz").write_text("nucleotide", encoding="utf-8")
    (protein / "uniref90.dmnd").write_text("protein", encoding="utf-8")
    (mapping / "map_uniref90_name.txt.gz").write_text("mapping", encoding="utf-8")
    add_reference_database(
        cfg,
        {
            "id": "db_humann_builtin",
            "name": "HUMAnN builtin",
            "templateId": "humann",
            "path": str(nucleotide.parent),
            "metadata": {
                "input": {
                    "kind": "multi",
                    "fields": {
                        "nucleotide": str(nucleotide),
                        "protein": str(protein),
                        "utility_mapping": str(mapping),
                    },
                }
            },
        },
    )

    result = build_workflow_resource_config(
        cfg,
        workflow_resource_spec={
            "humann_db": {
                "required": True,
                "acceptedTemplates": ["humann"],
                "configKey": "humann",
            }
        },
        bindings={"humann_db": "db_humann_builtin"},
    )

    assert result["config"]["humann"] == {
        "nucleotide": str(nucleotide),
        "protein": str(protein),
        "utility_mapping": str(mapping),
    }
    assert result["resources"]["humann_db"]["pathMode"] == "composite"
    assert result["resources"]["humann_db"]["resolved"] == result["config"]["humann"]


def test_workflow_resource_binding_rejects_wrong_template(tmp_path: Path, monkeypatch) -> None:
    _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    db_dir = tmp_path / "kraken2"
    db_dir.mkdir()
    for filename in ("hash.k2d", "opts.k2d", "taxo.k2d"):
        (db_dir / filename).write_text("index", encoding="utf-8")
    add_reference_database(
        cfg,
        {
            "id": "db_kraken2",
            "name": "Kraken2",
            "templateId": "kraken2",
            "path": str(db_dir),
        },
    )

    try:
        build_workflow_resource_config(
            cfg,
            workflow_resource_spec={
                "blast_nt_db": {
                    "required": True,
                    "acceptedTemplates": ["blast"],
                    "configKey": "blast_nt_db",
                }
            },
            bindings={"blast_nt_db": "db_kraken2"},
        )
    except ValueError as exc:
        assert "WORKFLOW_RESOURCE_TEMPLATE_UNSUPPORTED" in str(exc)
    else:
        raise AssertionError("wrong database template should be rejected")


def test_generated_workflow_uses_resource_binding_config_and_tokens(tmp_path: Path, monkeypatch) -> None:
    _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    blast_dir = tmp_path / "blast"
    blast_dir.mkdir()
    for suffix in (".nhr", ".nin", ".nsq"):
        (blast_dir / f"nt{suffix}").write_text("index", encoding="utf-8")
    add_reference_database(
        cfg,
        {
            "id": "db_ncbi_nt",
            "name": "NCBI nt",
            "templateId": "blast",
            "path": str(blast_dir),
        },
    )
    upsert_tool(
        cfg,
        {
            "id": "bioconda::blastn-demo",
            "name": "blastn",
            "source": "bioconda",
            "sourceLabel": "bioconda",
            "version": "2.16",
            "packageSpec": "bioconda::blast=2.16",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "printf '%s\\n' {config.blast_nt_db:q} > {output.tool_output:q}",
                "inputs": [{"name": "primary", "type": "file", "required": True}],
                "outputs": [{"name": "tool_output", "path": "blast-db.txt"}],
                "resources": {
                    "blast_nt_db": {
                        "label": "BLAST nt database",
                        "required": True,
                        "acceptedTemplates": ["blast"],
                        "configKey": "blast_nt_db",
                    }
                },
            },
        },
    )
    upload = persist_upload(cfg, filename="query.fa", content_base64="PlEKQUNHVAo=", mime_type="text/plain")

    class Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    monkeypatch.setattr("apps.remote_runner.executor.subprocess.run", lambda *_args, **_kwargs: Result())
    monkeypatch.setattr("apps.remote_runner.executor._collect_artifacts", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("apps.remote_runner.executor.update_run_state", lambda *args, **kwargs: None)
    monkeypatch.setattr("apps.remote_runner.executor.append_log_lines", lambda *args, **kwargs: None)

    run_snakemake_execution(
        cfg,
        run_id="run_resource_binding",
        request_id="req_resource_binding",
        run_spec={
            "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
            "projectId": "proj_demo",
            "inputs": [{"uploadId": upload["uploadId"], "filename": "query.fa", "role": "input"}],
            "resourceBindings": {"blast_nt_db": "db_ncbi_nt"},
            "tool": {"id": "bioconda::blastn-demo"},
        },
    )

    work_dir = Path(cfg.work_dir) / "run_resource_binding"
    run_config = json.loads((work_dir / "run-config.json").read_text(encoding="utf-8"))
    snakefile = (work_dir / "Snakefile").read_text(encoding="utf-8")

    assert run_config["databases"]["blast_nt_db"] == str(blast_dir / "nt")
    assert "databaseAssets" not in run_config
    assert run_config["resourceConfig"]["blast_nt_db"] == str(blast_dir / "nt")
    assert run_config["resources"]["blast_nt_db"]["path"] == str(blast_dir / "nt")
    assert run_config["resources"]["blast_nt_db"]["resolved"] == {"default": str(blast_dir / "nt")}
    assert run_config["resources"]["blast_nt_db"]["input"] == {"kind": "single", "path": str(blast_dir)}
    assert run_config["resources"]["blast_nt_db"]["inputPath"] == str(blast_dir)
    assert run_config["resources"]["blast_nt_db"]["entryPath"] == str(blast_dir / "nt")
    assert run_config["resources"]["blast_nt_db"]["pathMode"] == "prefix"
    assert str(blast_dir / "nt") not in snakefile
    assert "{config[databases][blast_nt_db]:q}" in snakefile
    assert "{config[resourceConfig][blast_nt_db]:q}" not in snakefile
    assert "{config.blast_nt_db:q}" not in snakefile


def test_static_pipeline_writes_resource_config_from_manifest(tmp_path: Path, monkeypatch) -> None:
    _patch_tool_probe_success(monkeypatch)
    release_dir = tmp_path / "release"
    pipeline_dir = release_dir / "pipelines" / "static-resource-v1"
    pipeline_dir.mkdir(parents=True)
    (pipeline_dir / "Snakefile").write_text('configfile: "run-config.json"\n', encoding="utf-8")
    (pipeline_dir / "pipeline.json").write_text(
        json.dumps(
            {
                "pipelineId": "static-resource-v1",
                "name": "Static Resource",
                "version": "1.0.0",
                "snakefile": "Snakefile",
                "enabled": True,
                "inputsSchema": {"type": "array", "minItems": 1},
                "resources": {
                    "blast_nt_db": {
                        "required": True,
                        "acceptedTemplates": ["blast"],
                        "configKey": "blast_nt_db",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    cfg = _cfg(tmp_path)
    cfg.release_dir = str(release_dir)
    ensure_runtime_layout(cfg)
    blast_dir = tmp_path / "blast"
    blast_dir.mkdir()
    for suffix in (".nhr", ".nin", ".nsq"):
        (blast_dir / f"nt{suffix}").write_text("index", encoding="utf-8")
    add_reference_database(cfg, {"id": "db_ncbi_nt", "name": "NCBI nt", "templateId": "blast", "path": str(blast_dir)})
    upload = persist_upload(cfg, filename="query.fa", content_base64="PlEKQUNHVAo=", mime_type="text/plain")

    class Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    monkeypatch.setattr("apps.remote_runner.executor.subprocess.run", lambda *_args, **_kwargs: Result())
    monkeypatch.setattr("apps.remote_runner.executor._collect_artifacts", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("apps.remote_runner.executor.update_run_state", lambda *args, **kwargs: None)
    monkeypatch.setattr("apps.remote_runner.executor.append_log_lines", lambda *args, **kwargs: None)

    run_snakemake_execution(
        cfg,
        run_id="run_static_resource",
        request_id="req_static_resource",
        run_spec={
            "pipelineId": "static-resource-v1",
            "projectId": "proj_demo",
            "inputs": [{"uploadId": upload["uploadId"], "filename": "query.fa", "role": "input"}],
            "resourceBindings": {"blast_nt_db": "db_ncbi_nt"},
        },
    )

    run_config = json.loads((Path(cfg.work_dir) / "run_static_resource" / "run-config.json").read_text(encoding="utf-8"))
    assert run_config["databases"]["blast_nt_db"] == str(blast_dir / "nt")
    assert "databaseAssets" not in run_config
    assert run_config["resourceConfig"]["blast_nt_db"] == str(blast_dir / "nt")
    assert run_config["resources"]["blast_nt_db"]["inputPath"] == str(blast_dir)
    assert run_config["resources"]["blast_nt_db"]["entryPath"] == str(blast_dir / "nt")
