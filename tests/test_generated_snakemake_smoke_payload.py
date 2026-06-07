from __future__ import annotations

import ast
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SMOKE_SCRIPTS_DIR = REPO_ROOT / "skills" / "h2ometa-remote-smoke-test" / "scripts"
if str(SMOKE_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SMOKE_SCRIPTS_DIR))

import remote_database_smoke  # noqa: E402
import remote_all_databases_snakemake_smoke  # noqa: E402
import remote_generated_linear_workflow_smoke  # noqa: E402
import remote_generated_tool_smoke  # noqa: E402
import remote_real_database_acceptance  # noqa: E402


def test_remote_smoke_upload_payloads_include_selected_server_id() -> None:
    from local_api_smoke_helpers import build_upload_submit_payload

    payload = build_upload_submit_payload(
        server_id="srv_real",
        filename="letters.txt",
        content_base64="QUJDREVGCg==",
        mime_type="text/plain",
    )

    assert payload == {
        "serverId": "srv_real",
        "filename": "letters.txt",
        "contentBase64": "QUJDREVGCg==",
        "mimeType": "text/plain",
    }
    for module in (
        remote_generated_tool_smoke,
        remote_generated_linear_workflow_smoke,
        remote_database_smoke,
        remote_all_databases_snakemake_smoke,
        remote_real_database_acceptance,
    ):
        calls = _upload_http_calls(module)
        assert calls, module.__name__
        for call in calls:
            payload = next((keyword.value for keyword in call.keywords if keyword.arg == "payload"), None)
            assert isinstance(payload, ast.Call)
            assert isinstance(payload.func, ast.Name)
            assert payload.func.id == "build_upload_submit_payload"
            server_id = next((keyword.value for keyword in payload.keywords if keyword.arg == "server_id"), None)
            assert isinstance(server_id, ast.Name)
            assert server_id.id == "server_id"


def test_remote_smoke_upload_call_detector_covers_keyword_and_constant_paths() -> None:
    calls = _upload_http_calls_from_source(
        """
UPLOADS_PATH = "/api/v1/uploads"
http_json("POST", api_base, path="/api/v1/uploads", payload={})
http_json("POST", api_base, UPLOADS_PATH, payload={})
"""
    )

    assert len(calls) == 2


def _plan(*, project_id: str = "proj_smoke", resource_bindings: dict | None = None) -> dict:
    return {
        "valid": True,
        "runSpec": {
            "projectId": project_id,
            "pipelineId": "generated-tool-run-v1",
            "workflowRevisionId": "wfrev_smoke",
            "workflow": {"contractVersion": "rule-contract-v1", "nodes": [], "edges": [], "outputs": []},
            "resourceBindings": resource_bindings or {},
            "workflowDesign": {"draftId": "wfd_smoke", "revision": 1},
        },
    }


def _upload_http_calls(module: object) -> list[ast.Call]:
    source = Path(module.__file__).read_text(encoding="utf-8")
    return _upload_http_calls_from_source(source)


def _upload_http_calls_from_source(source: str) -> list[ast.Call]:
    tree = ast.parse(source)
    constants = _string_constants(tree)
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _http_json_path(node, constants) == "/api/v1/uploads":
            calls.append(node)
    return calls


def _string_constants(tree: ast.AST) -> dict[str, str]:
    constants: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    constants[target.id] = node.value.value
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            value = node.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                constants[node.target.id] = value.value
    return constants


def _http_json_path(call: ast.Call, constants: dict[str, str]) -> str:
    if not isinstance(call.func, ast.Name) or call.func.id != "http_json":
        return ""
    if len(call.args) >= 3:
        path = _string_expr(call.args[2], constants)
        if path:
            return path
    keyword_path = next((keyword.value for keyword in call.keywords if keyword.arg == "path"), None)
    return _string_expr(keyword_path, constants) if keyword_path else ""


def _string_expr(node: ast.AST, constants: dict[str, str]) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id, "")
    return ""


def test_generated_tool_submit_payload_includes_local_api_server_id() -> None:
    payload = remote_generated_tool_smoke.build_run_submit_payload(
        request_id="req_generated",
        server_id="srv_real",
        upload={"uploadId": "upl_letters", "filename": "letters.txt"},
        plan=_plan(),
    )

    assert payload["serverId"] == "srv_real"
    assert payload["requestId"] == "req_generated"
    assert payload["runSpec"]["pipelineId"] == "generated-tool-run-v1"
    assert payload["runSpec"]["workflowRevisionId"] == "wfrev_smoke"
    assert payload["runSpec"]["inputs"] == [
        {"uploadId": "upl_letters", "filename": "letters.txt", "role": "input"}
    ]
    assert payload["runSpec"]["workflowDesign"] == {"draftId": "wfd_smoke", "revision": 1}
    assert "tool" not in payload["runSpec"]


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
        upload={"uploadId": "upl_letters", "filename": "letters.txt"},
        plan=_plan(),
    )

    assert payload["serverId"] == "srv_real"
    assert payload["runSpec"]["workflowRevisionId"] == "wfrev_smoke"
    assert payload["runSpec"]["workflowDesign"]["draftId"] == "wfd_smoke"
    assert "steps" not in payload["runSpec"]["workflow"]


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
        upload={"uploadId": "upl_reads", "filename": "reads.txt"},
        plan=_plan(resource_bindings={"taxonomy": {"databaseId": "taxonomy-db-custom-smoke"}}),
    )

    assert payload["serverId"] == "srv_real"
    assert payload["runSpec"]["workflowRevisionId"] == "wfrev_smoke"
    assert payload["runSpec"]["resourceBindings"] == {"taxonomy": {"databaseId": "taxonomy-db-custom-smoke"}}
    assert "tool" not in payload["runSpec"]


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
        plan=_plan(resource_bindings={"blast": {"databaseId": "blast-db", "templateId": "blast"}}),
    )

    assert payload["serverId"] == "srv_real"
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
        plan=_plan(
            project_id="proj_real_database_acceptance",
            resource_bindings={"blast": {"databaseId": "blast-db", "templateId": "blast"}},
        ),
    )

    assert payload["serverId"] == "srv_real"
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
