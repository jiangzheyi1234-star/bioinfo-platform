from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SMOKE_SCRIPTS_DIR = REPO_ROOT / "skills" / "h2ometa-remote-smoke-test" / "scripts"
if str(SMOKE_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SMOKE_SCRIPTS_DIR))

import remote_database_smoke
import remote_all_databases_snakemake_smoke
import remote_generated_linear_workflow_smoke
import remote_generated_tool_smoke
import remote_real_database_acceptance


def test_generated_tool_submit_payload_includes_local_api_server_id() -> None:
    payload = remote_generated_tool_smoke.build_run_submit_payload(
        request_id="req_generated",
        server_id="srv_real",
        project_id="proj_smoke",
        upload={"uploadId": "upl_letters", "filename": "letters.txt"},
        tool={"id": "conda-forge::coreutils-generated-smoke"},
    )

    assert payload["serverId"] == "srv_real"
    assert payload["requestId"] == "req_generated"
    assert payload["runSpec"]["pipelineId"] == "generated-tool-run-v1"
    assert payload["runSpec"]["inputs"] == [
        {"uploadId": "upl_letters", "filename": "letters.txt", "role": "input"}
    ]
    assert payload["runSpec"]["tool"] == {"id": "conda-forge::coreutils-generated-smoke"}


def test_generated_tool_smoke_registers_verifiable_tool_contract() -> None:
    payload = remote_generated_tool_smoke.build_coreutils_tool_payload("conda-forge::coreutils-generated-smoke")
    rule = payload["ruleTemplate"]

    assert rule["environment"]["conda"]["channels"] == ["conda-forge", "bioconda"]
    assert rule["environment"]["conda"]["dependencies"] == ["conda-forge::coreutils=9.5"]
    assert rule["params"] == {}
    assert rule["resources"]["mem_mb"]["default"] == 128
    assert rule["log"]
    assert rule["smokeTest"]["inputs"]["primary"]["content"]


def test_generated_linear_submit_payload_includes_local_api_server_id() -> None:
    payload = remote_generated_linear_workflow_smoke.build_run_submit_payload(
        request_id="req_linear",
        server_id="srv_real",
        project_id="proj_smoke",
        upload={"uploadId": "upl_letters", "filename": "letters.txt"},
        count_tool={"id": "conda-forge::coreutils-count-smoke"},
        copy_tool={"id": "conda-forge::coreutils-copy-smoke"},
    )

    assert payload["serverId"] == "srv_real"
    assert payload["runSpec"]["workflow"]["steps"] == [
        {"id": "count_bytes", "tool": {"id": "conda-forge::coreutils-count-smoke"}},
        {"id": "copy_summary", "tool": {"id": "conda-forge::coreutils-copy-smoke"}},
    ]


def test_generated_linear_smoke_registers_verifiable_tool_contracts() -> None:
    count_payload = remote_generated_linear_workflow_smoke.build_coreutils_tool_payload(
        tool_id="conda-forge::coreutils-count-smoke",
        command="wc -c {input.primary:q} > {output.count:q}",
        output_name="count",
        output_path="wc-count.txt",
    )
    copy_payload = remote_generated_linear_workflow_smoke.build_coreutils_tool_payload(
        tool_id="conda-forge::coreutils-copy-smoke",
        command="cp {input.primary:q} {output.final:q}",
        output_name="final",
        output_path="final-count.txt",
    )

    assert count_payload["ruleTemplate"]["environment"]["conda"]["dependencies"] == ["conda-forge::coreutils=9.5"]
    assert count_payload["ruleTemplate"]["resources"]["mem_mb"]["default"] == 128
    assert count_payload["ruleTemplate"]["log"]
    assert copy_payload["ruleTemplate"]["smokeTest"]["inputs"]["primary"]["content"]


def test_database_submit_payload_includes_local_api_server_id() -> None:
    payload = remote_database_smoke.build_run_submit_payload(
        request_id="req_database",
        server_id="srv_real",
        project_id="proj_smoke",
        upload={"uploadId": "upl_reads", "filename": "reads.txt"},
        database={"id": "taxonomy-db-custom-smoke"},
        tool={"id": "conda-forge::coreutils-database-smoke"},
    )

    assert payload["serverId"] == "srv_real"
    assert payload["runSpec"]["resourceBindings"] == {"taxonomy": {"databaseId": "taxonomy-db-custom-smoke"}}
    assert payload["runSpec"]["tool"] == {"id": "conda-forge::coreutils-database-smoke"}


def test_database_smoke_registers_tool_with_smoke_resource_binding() -> None:
    payload = remote_database_smoke.build_database_tool_payload(
        tool_id="conda-forge::coreutils-database-smoke",
        database_id="taxonomy-db-custom-smoke",
    )
    rule = payload["ruleTemplate"]

    assert rule["environment"]["conda"]["dependencies"] == ["conda-forge::coreutils=9.5"]
    assert rule["resources"]["mem_mb"]["default"] == 128
    assert rule["log"]
    assert rule["smokeTest"]["resourceBindings"] == {"taxonomy": {"databaseId": "taxonomy-db-custom-smoke"}}


def test_all_database_smoke_registers_resource_bound_tool_contract() -> None:
    payload = remote_all_databases_snakemake_smoke.build_database_tool_payload(
        tool_id="conda-forge::coreutils-db-path-smoke-blast-1",
        role="blast",
        database={"id": "blast-db", "metadata": {"templateId": "blast"}},
        output_name="database-blast-path.txt",
    )
    rule = payload["ruleTemplate"]

    assert rule["commandTemplate"] == "printf '%s\\n' {config.blast:q} > {output.database_path:q}"
    assert rule["resources"]["blast"]["configKey"] == "blast"
    assert rule["resources"]["mem_mb"]["default"] == 128
    assert rule["log"]
    assert rule["environment"]["conda"]["channels"] == ["conda-forge", "bioconda"]
    assert rule["smokeTest"]["resourceBindings"] == {"blast": {"databaseId": "blast-db", "templateId": "blast"}}


def test_all_database_smoke_submit_payload_uses_resource_bindings() -> None:
    payload = remote_all_databases_snakemake_smoke.build_run_submit_payload(
        request_id="req_all_db",
        server_id="srv_real",
        upload={"uploadId": "upl_db", "filename": "db-smoke-blast.txt"},
        database={"id": "blast-db", "metadata": {"templateId": "blast"}},
        role="blast",
        tool={"id": "conda-forge::coreutils-db-path-smoke-blast-1"},
    )

    assert "databases" not in payload["runSpec"]
    assert payload["runSpec"]["resourceBindings"] == {"blast": {"databaseId": "blast-db", "templateId": "blast"}}


def test_real_database_acceptance_registers_resource_bound_tool_contract() -> None:
    payload = remote_real_database_acceptance.build_database_tool_payload(
        tool_id="conda-forge::coreutils-real-db-acceptance-blast-1",
        role="blast",
        database={"id": "blast-db", "metadata": {"templateId": "blast"}},
        output_name="real-database-blast-path.txt",
    )
    rule = payload["ruleTemplate"]

    assert rule["commandTemplate"] == "printf '%s\\n' {config.blast:q} > {output.database_path:q}"
    assert rule["resources"]["blast"]["acceptedTemplates"] == ["blast"]
    assert rule["resources"]["mem_mb"]["default"] == 128
    assert rule["log"]
    assert rule["smokeTest"]["resourceBindings"] == {"blast": {"databaseId": "blast-db", "templateId": "blast"}}


def test_real_database_acceptance_submit_payload_uses_resource_bindings() -> None:
    payload = remote_real_database_acceptance.build_run_submit_payload(
        request_id="req_real_db",
        server_id="srv_real",
        upload={"uploadId": "upl_real", "filename": "real-db-acceptance-blast.txt"},
        database={"id": "blast-db", "metadata": {"templateId": "blast"}},
        role="blast",
        tool={"id": "conda-forge::coreutils-real-db-acceptance-blast-1"},
    )

    assert "databases" not in payload["runSpec"]
    assert payload["runSpec"]["resourceBindings"] == {"blast": {"databaseId": "blast-db", "templateId": "blast"}}


def test_real_database_acceptance_records_production_evidence() -> None:
    payload = remote_real_database_acceptance.build_production_acceptance_payload(
        run_id="run_real_db",
        database={"id": "blast-db"},
        role="blast",
        template_id="blast",
        artifact_name="real-database-blast-path.txt",
    )
    source = Path(remote_real_database_acceptance.__file__).read_text(encoding="utf-8")

    assert payload["runId"] == "run_real_db"
    assert payload["evidenceType"] == "real-database-acceptance"
    assert payload["databaseId"] == "blast-db"
    assert payload["templateId"] == "blast"
    assert payload["role"] == "blast"
    assert payload["artifactName"] == "real-database-blast-path.txt"
    assert "blast-db" in payload["message"]
    assert "real database acceptance" in payload["message"]
    assert "/production" in source
    assert "keep_production_tools" in source
