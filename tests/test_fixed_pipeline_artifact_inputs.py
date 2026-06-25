from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.remote_runner.artifact_ledger_storage import list_lineage_edges_for_run, list_run_artifact_edges
from apps.remote_runner.executor import run_snakemake_execution
from apps.remote_runner.pipeline import PipelineRegistryError, get_pipeline, list_pipelines, validate_run_spec_for_pipeline
from apps.remote_runner.storage import persist_artifact
from tests.helpers.reference_database import make_configured_remote_runner


FIXED_ARTIFACT_INPUT_PIPELINES = {
    "branch-merge-analysis-v1": "input_table",
    "database-backed-analysis-v1": "reads",
    "file-summary-standard-v1": "reads",
    "file-summary-v1": "reads",
    "linear-qc-report-v1": "reads",
    "moving-pictures-16s-rulegraph-v1": "metadata",
}


def test_fixed_pipeline_input_schemas_accept_explicit_artifact_references(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    pipelines = {item.pipeline_id: item for item in list_pipelines(cfg)}

    for pipeline_id, default_role in FIXED_ARTIFACT_INPUT_PIPELINES.items():
        pipeline = pipelines[pipeline_id]
        validate_run_spec_for_pipeline(
            pipeline,
            {
                "pipelineId": pipeline_id,
                "projectId": "proj_demo",
                "inputs": [
                    {
                        "artifactId": "art_source",
                        "filename": "input.txt",
                        "role": default_role,
                    }
                    for _ in range(_min_inputs(pipeline.input_schema))
                ],
            },
        )
        validate_run_spec_for_pipeline(
            pipeline,
            {
                "pipelineId": pipeline_id,
                "projectId": "proj_demo",
                "inputs": [
                    {
                        "artifactBlobId": "ablob_source",
                        "materializationId": "amat_source",
                        "sourceArtifactId": "art_source",
                        "filename": "input.txt",
                        "role": default_role,
                    }
                    for _ in range(_min_inputs(pipeline.input_schema))
                ],
            },
        )


def test_fixed_pipeline_input_schemas_reject_mixed_or_implicit_sources(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    pipeline = get_pipeline(cfg, "file-summary-standard-v1")

    invalid_inputs = [
        {"uploadId": "upl_reads", "artifactId": "art_reads", "filename": "reads.txt", "role": "reads"},
        {"artifactBlobId": "ablob_reads", "filename": "reads.txt", "role": "reads"},
        {"filename": "reads.txt", "role": "reads"},
        {
            "artifactId": "art_reads",
            "filename": "reads.txt",
            "role": "reads",
            "storageUri": "file:///C:/secret/reads.txt",
        },
    ]

    for input_item in invalid_inputs:
        with pytest.raises(PipelineRegistryError, match="INPUT_SCHEMA_INVALID"):
            validate_run_spec_for_pipeline(
                pipeline,
                {
                    "pipelineId": "file-summary-standard-v1",
                    "projectId": "proj_demo",
                    "inputs": [input_item],
                },
            )


def test_file_summary_standard_pipeline_restores_artifact_input(tmp_path: Path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    source_path = Path(cfg.results_dir) / "run_source_artifact" / "reads.txt"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("sample\n", encoding="utf-8")
    source_artifact = persist_artifact(
        cfg,
        run_id="run_source_artifact",
        kind="reads",
        path=source_path,
        mime_type="text/plain",
        artifact_key="reads",
    )
    run_spec = {
        "pipelineId": "file-summary-standard-v1",
        "projectId": "proj_demo",
        "inputs": [
            {
                "artifactId": source_artifact["artifactId"],
                "filename": "reads.txt",
                "role": "reads",
            }
        ],
        "params": {"include_content_hash": "true"},
    }
    validate_run_spec_for_pipeline(get_pipeline(cfg, "file-summary-standard-v1"), run_spec)

    calls: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(cmd, **_kwargs):
        calls.append(cmd)
        return Result()

    monkeypatch.setattr("apps.remote_runner.executor.subprocess.run", fake_run)
    monkeypatch.setattr("apps.remote_runner.executor._collect_artifacts", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("apps.remote_runner.executor.update_run_state", lambda *args, **kwargs: None)
    monkeypatch.setattr("apps.remote_runner.executor.append_log_lines", lambda *args, **kwargs: None)

    run_snakemake_execution(
        cfg,
        run_id="run_fixed_artifact_input",
        request_id="req_fixed_artifact_input",
        run_spec=run_spec,
    )

    work_dir = Path(cfg.work_dir) / "run_fixed_artifact_input"
    run_config = json.loads((work_dir / "run-config.json").read_text(encoding="utf-8"))
    run_edges = list_run_artifact_edges(cfg, "run_fixed_artifact_input")
    lineage_edges = list_lineage_edges_for_run(cfg, "run_fixed_artifact_input")

    assert len(calls) == 2
    assert run_config["pipeline_id"] == "file-summary-standard-v1"
    assert run_config["inputs"][0]["sourceType"] == "artifact"
    assert run_config["inputs"][0]["artifactId"] == source_artifact["artifactId"]
    assert run_config["inputs"][0]["artifactBlobId"] == source_artifact["artifactBlobId"]
    assert run_config["inputs"][0]["sourceMaterializationId"] == source_artifact["materializationId"]
    assert run_config["inputs"][0]["path"] == str(work_dir / "inputs" / "001-reads.txt")
    assert Path(run_config["inputs"][0]["path"]).read_text(encoding="utf-8") == "sample\n"
    assert run_edges[0]["role"] == "input"
    assert run_edges[0]["portName"] == "reads"
    assert lineage_edges[0]["predicate"] == "prov:used"
    assert lineage_edges[0]["payload"]["sourceType"] == "artifact"
    assert lineage_edges[0]["payload"]["artifactId"] == source_artifact["artifactId"]
    assert "uploadId" not in lineage_edges[0]["payload"]


def _min_inputs(schema: dict[str, object]) -> int:
    return max(1, int(schema.get("minItems") or 1))
