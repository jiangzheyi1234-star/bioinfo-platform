from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import remote_pipeline_database_binding_smoke


def test_database_bound_pipeline_payload_uses_resource_bindings_not_legacy_databases() -> None:
    payload = remote_pipeline_database_binding_smoke.build_run_submit_payload(
        request_id="req_database_binding",
        server_id="srv_real",
        project_id="proj_database_binding_smoke",
        pipeline_id="database-backed-analysis-v1",
        resource_key="reference_database",
        upload={"uploadId": "upl_reads", "filename": "reads.fastq"},
        database={"id": "db_ncbi_nt"},
    )

    assert payload["serverId"] == "srv_real"
    assert payload["requestId"] == "req_database_binding"
    assert payload["runSpec"]["pipelineId"] == "database-backed-analysis-v1"
    assert payload["runSpec"]["inputs"] == [
        {"uploadId": "upl_reads", "filename": "reads.fastq", "role": "reads"}
    ]
    assert payload["runSpec"]["resourceBindings"] == {
        "reference_database": {"databaseId": "db_ncbi_nt"}
    }
    assert "databases" not in payload["runSpec"]
    assert "tool" not in payload["runSpec"]
    assert "workflow" not in payload["runSpec"]


def test_database_selection_honors_resource_template_contract() -> None:
    selected = remote_pipeline_database_binding_smoke._select_database(
        [
            {"id": "db_unavailable", "status": "missing", "metadata": {"templateId": "blast"}},
            {"id": "db_kraken", "status": "available", "metadata": {"templateId": "kraken2"}},
            {"id": "db_blast", "status": "available", "metadata": {"templateId": "blast"}},
        ],
        "",
        {"acceptedTemplates": ["blast"]},
    )

    assert selected["id"] == "db_blast"


def test_explicit_database_id_must_still_match_resource_contract() -> None:
    selected = remote_pipeline_database_binding_smoke._select_database(
        [
            {"id": "db_kraken", "status": "available", "metadata": {"templateId": "kraken2"}},
        ],
        "db_kraken",
        {"acceptedTemplates": ["blast"]},
    )

    assert selected is None
