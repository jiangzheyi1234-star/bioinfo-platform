from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SMOKE_SCRIPTS_DIR = REPO_ROOT / "skills" / "h2ometa-remote-smoke-test" / "scripts"
if str(SMOKE_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SMOKE_SCRIPTS_DIR))

import remote_database_smoke
import remote_generated_linear_workflow_smoke
import remote_generated_tool_smoke


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
