from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import remote_pipeline_common  # noqa: E402
import remote_pipeline_smoke  # noqa: E402


def test_run_submit_payload_includes_required_server_id() -> None:
    payload = remote_pipeline_smoke.build_run_submit_payload(
        request_id="req_smoke",
        server_id="srv_real",
        project_id="proj_smoke",
        pipeline_id="file-summary-v1",
        upload={"uploadId": "upl_real", "filename": "sample.fastq"},
    )

    assert payload["serverId"] == "srv_real"
    assert payload["requestId"] == "req_smoke"
    assert payload["runSpec"]["projectId"] == "proj_smoke"
    assert payload["runSpec"]["pipelineId"] == "file-summary-v1"
    assert payload["runSpec"]["inputs"] == [
        {"uploadId": "upl_real", "filename": "sample.fastq", "role": "reads"}
    ]
    assert payload["runSpec"]["params"] == {"threads": 1}


def test_response_data_unwraps_single_layer_payload() -> None:
    assert remote_pipeline_smoke.response_data({"data": {"runId": "run_1", "status": "completed"}}) == {
        "runId": "run_1",
        "status": "completed",
    }


def test_response_data_unwraps_nested_local_api_payload() -> None:
    assert remote_pipeline_smoke.response_data({"data": {"data": {"runId": "run_1", "status": "completed"}}}) == {
        "runId": "run_1",
        "status": "completed",
    }


def test_result_id_for_run_selects_matching_run() -> None:
    assert (
        remote_pipeline_common.result_id_for_run(
            [
                {"runId": "run_other", "resultId": "res_other"},
                {"runId": "run_target", "resultId": "res_target"},
            ],
            "run_target",
        )
        == "res_target"
    )


def test_preview_table_requires_mapping_preview() -> None:
    assert remote_pipeline_common.preview_table({"preview": {"rows": [["a"]]}}) == {"rows": [["a"]]}
    assert remote_pipeline_common.preview_table({"preview": []}) == {}
