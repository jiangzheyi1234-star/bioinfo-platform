from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.remote_runner.config import ensure_runtime_layout
from apps.remote_runner.databases import DATABASE_TEMPLATES, add_reference_database
from apps.remote_runner.executor import run_snakemake_execution
from apps.remote_runner.generated_workflow import GENERATED_TOOL_RUN_PIPELINE_ID
from apps.remote_runner.storage import persist_upload, upsert_tool
from apps.remote_runner.workflow_resources import build_workflow_resource_config
from tests.helpers.reference_database import (
    assert_resolution_contract,
    iter_workflow_resource_contract_cases,
    make_blast_prefix_database as _make_blast_prefix_database,
    make_configured_remote_runner,
    make_kraken2_database as _make_kraken2_database,
    patch_tool_probe_success as _patch_tool_probe_success,
)


def _cfg(tmp_path: Path):
    return make_configured_remote_runner(tmp_path, token="workflow-resource-token")


@pytest.mark.parametrize(
    "case_id",
    [
        "directory-kraken2",
        "prefix-blast",
        "primary-with-sidecars-bwa",
        "composite-humann",
    ],
    ids=[
        "directory-kraken2",
        "prefix-blast",
        "primary-with-sidecars-bwa",
        "composite-humann",
    ],
)
def test_workflow_resource_binding_matches_shared_contract_matrix(tmp_path: Path, monkeypatch, case_id: str) -> None:
    _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    case_root = tmp_path / case_id
    cases = {case.case_id: case for case in iter_workflow_resource_contract_cases(case_root)}
    case = cases[case_id]

    add_reference_database(
        cfg,
        {
            "id": case.database_id,
            "name": case.database_name,
            "templateId": case.template_id,
            "path": case.database_path,
        },
    )

    result = build_workflow_resource_config(
        cfg,
        workflow_resource_spec={
            case.resource_key: {
                "required": True,
                "acceptedTemplates": [case.template_id],
                "configKey": case.config_key,
            }
        },
        bindings={case.resource_key: case.database_id},
    )

    resource = result["resources"][case.resource_key]
    assert result["config"][case.config_key] == case.expected_config_value
    assert resource["databaseId"] == case.database_id
    assert resource["templateId"] == case.template_id
    assert resource["path"] == case.entry_path
    assert resource["input"] == case.expected_input
    assert resource["resolved"] == case.expected_resolved
    assert resource["pathMode"] == case.expected_path_mode
    assert_resolution_contract(
        resource,
        input_path=case.database_path,
        entry_path=case.entry_path,
        path_mode=case.expected_path_mode,
        input_value=case.expected_input,
        input_kind=case.expected_input_kind,
        require_metadata=False,
    )


def test_workflow_resource_binding_preserves_composite_metadata_and_custom_template(tmp_path: Path, monkeypatch) -> None:
    _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    nucleotide = tmp_path / "humann" / "chocophlan"
    protein = tmp_path / "humann" / "uniref"
    mapping = tmp_path / "humann" / "utility_mapping"
    for path in (nucleotide, protein, mapping):
        path.mkdir(parents=True)
    (nucleotide / "genome.ffn.gz").write_text("nucleotide", encoding="utf-8")
    (protein / "uniref90.dmnd").write_text("protein", encoding="utf-8")
    (mapping / "map_uniref90_name.txt.gz").write_text("mapping", encoding="utf-8")

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

    expected_input = {
        "kind": "multi",
        "fields": {
            "nucleotide": str(nucleotide),
            "protein": str(protein),
            "utility_mapping": str(mapping),
        },
    }
    expected_resolved = expected_input["fields"]

    assert result["config"]["humann"] == expected_resolved
    assert result["resources"]["humann_db"]["input"] == expected_input
    assert result["resources"]["humann_db"]["resolved"] == expected_resolved
    assert result["resources"]["humann_db"]["pathMode"] == "composite"
    assert_resolution_contract(
        result["resources"]["humann_db"],
        input_path=str(nucleotide.parent),
        entry_path="",
        path_mode="composite",
        input_value=expected_input,
        input_kind="multi",
        require_metadata=False,
    )


def test_workflow_resource_binding_rejects_wrong_template(tmp_path: Path, monkeypatch) -> None:
    _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    db_dir = _make_kraken2_database(tmp_path / "kraken2")
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
    blast_dir = _make_blast_prefix_database(tmp_path / "blast")
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
    assert_resolution_contract(
        run_config["resources"]["blast_nt_db"],
        input_path=blast_dir,
        entry_path=blast_dir / "nt",
        path_mode="prefix",
        input_value={"kind": "single", "path": str(blast_dir)},
        input_kind="single",
        require_metadata=False,
    )
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
    blast_dir = _make_blast_prefix_database(tmp_path / "blast")
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
    assert run_config["resources"]["blast_nt_db"]["resolved"] == {"default": str(blast_dir / "nt")}
    assert run_config["resources"]["blast_nt_db"]["input"] == {"kind": "single", "path": str(blast_dir)}
    assert_resolution_contract(
        run_config["resources"]["blast_nt_db"],
        input_path=blast_dir,
        entry_path=blast_dir / "nt",
        path_mode="prefix",
        input_value={"kind": "single", "path": str(blast_dir)},
        input_kind="single",
        require_metadata=False,
    )
