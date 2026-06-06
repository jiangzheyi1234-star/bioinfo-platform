from __future__ import annotations

from pathlib import Path

from apps.remote_runner.config import ensure_runtime_layout
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.tool_platform_storage import (
    list_tool_runtime_profiles,
    list_tool_validation_results,
    search_tool_index,
)
from apps.remote_runner.tool_prepare_job_storage import (
    complete_tool_prepare_job,
    create_tool_prepare_job,
    fail_tool_prepare_job,
)
from apps.remote_runner.tools import add_registered_tool
from tests.test_tool_contract_pipeline import _cfg


def _tool_payload(name: str, *, summary: str = "") -> dict[str, object]:
    return {
        "id": f"bioconda::{name.lower()}",
        "name": name,
        "source": "bioconda",
        "version": "1.0",
        "packageSpec": f"bioconda::{name.lower()}=1.0",
        "summary": summary or f"{name} summary",
        "targetPlatform": "linux-64",
        "targetPlatformSupported": True,
        "platforms": ["linux-64"],
    }


def test_tool_index_materializes_registered_tools_as_paginated_read_model(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    add_registered_tool(cfg, _tool_payload("FastQC", summary="Read quality control"))
    add_registered_tool(cfg, _tool_payload("MultiQC", summary="Aggregate quality control reports"))

    page = search_tool_index(cfg, query="quality", limit=1, offset=0)
    next_page = search_tool_index(cfg, query="quality", limit=1, offset=1)

    assert page["total"] == 2
    assert page["limit"] == 1
    assert page["offset"] == 0
    assert len(page["items"]) == 1
    assert next_page["total"] == 2
    assert len(next_page["items"]) == 1
    assert page["items"][0]["toolId"] != next_page["items"][0]["toolId"]
    assert set(page["facets"]["sources"]) == {"bioconda"}
    assert "ruleTemplate" not in page["items"][0]
    assert "toolContract" not in page["items"][0]
    state_page = search_tool_index(cfg, state=page["items"][0]["facets"]["state"], limit=10, offset=0)
    assert state_page["total"] == 2

    with get_connection(cfg) as connection:
        row_count = connection.execute("SELECT COUNT(*) AS count FROM tool_index").fetchone()["count"]
    assert row_count == 2


def test_tool_validation_results_are_durable_and_update_tool_index_summary(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    add_registered_tool(cfg, _tool_payload("FastQC"))
    job = create_tool_prepare_job(
        cfg,
        {
            **_tool_payload("FastQC"),
            "validationTarget": "workflow-ready",
        },
    )

    failed = fail_tool_prepare_job(
        cfg,
        job["jobId"],
        code="SNAKEMAKE_DRY_RUN_FAILED",
        message="Snakemake dry-run failed.",
    )
    results = list_tool_validation_results(cfg, tool_id="bioconda::fastqc")
    page = search_tool_index(cfg, query="fastqc", limit=10, offset=0)

    assert failed["status"] == "failed"
    assert len(results) == 1
    assert results[0]["jobId"] == job["jobId"]
    assert results[0]["toolId"] == "bioconda::fastqc"
    assert results[0]["stage"] == "failed"
    assert results[0]["status"] == "failed"
    assert results[0]["failureCode"] == "SNAKEMAKE_DRY_RUN_FAILED"
    assert page["items"][0]["validationSummary"]["latestStatus"] == "failed"
    assert page["items"][0]["validationSummary"]["latestResultId"] == results[0]["validationResultId"]


def test_tool_validation_result_reuses_runtime_profile_for_same_revision_and_lock(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    add_registered_tool(cfg, _tool_payload("FastQC"))
    runtime_profile = {
        "platform": "linux-64",
        "engine": "snakemake",
        "environmentLock": {
            "manager": "conda",
            "packageSpec": "bioconda::fastqc=1.0",
            "solver": "mamba",
        },
        "resourceProfile": {"threads": 2, "memMb": 1024},
        "securityPolicy": {"network": "disabled"},
    }
    first = create_tool_prepare_job(
        cfg,
        {
            **_tool_payload("FastQC"),
            "validationTarget": "workflow-ready",
            "runtimeProfile": runtime_profile,
        },
    )
    second = create_tool_prepare_job(
        cfg,
        {
            **_tool_payload("FastQC"),
            "validationTarget": "production-evidence",
            "runtimeProfile": runtime_profile,
        },
    )

    complete_tool_prepare_job(
        cfg,
        first["jobId"],
        {
            "id": "bioconda::fastqc",
            "toolRevisionId": "bioconda::fastqc#rev1",
            "message": "Tool revision published.",
        },
    )
    complete_tool_prepare_job(
        cfg,
        second["jobId"],
        {
            "id": "bioconda::fastqc",
            "toolRevisionId": "bioconda::fastqc#rev1",
            "message": "Tool revision published.",
        },
    )

    results = list_tool_validation_results(cfg, tool_id="bioconda::fastqc")
    profiles = list_tool_runtime_profiles(cfg, tool_revision_id="bioconda::fastqc#rev1")

    assert len(results) == 2
    assert len(profiles) == 1
    assert {result["runtimeProfileId"] for result in results} == {profiles[0]["runtimeProfileId"]}
    assert profiles[0]["platform"] == "linux-64"
    assert profiles[0]["engine"] == "snakemake"
    assert profiles[0]["environmentLock"]["packageSpec"] == "bioconda::fastqc=1.0"
    assert profiles[0]["resourceProfile"] == {"memMb": 1024, "threads": 2}
    assert profiles[0]["securityPolicy"] == {"network": "disabled"}
