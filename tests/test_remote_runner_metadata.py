from __future__ import annotations

import json

from core.remote_runner.metadata import compact_preview_payload


def test_compact_preview_payload_tolerates_non_mapping_payloads() -> None:
    assert compact_preview_payload(None) == {"kind": "", "truncated": False}
    assert compact_preview_payload([]) == {"kind": "", "truncated": False}


def test_compact_preview_payload_limits_table_context_size() -> None:
    large_cell = "x" * 5000
    compact = compact_preview_payload(
        {
            "data": {
                "artifactId": "art_table",
                "preview": {
                    "kind": "table",
                    "columns": [f"column_{index}_{large_cell}" for index in range(40)],
                    "rows": [[f"row_{row}_{column}_{large_cell}" for column in range(40)] for row in range(20)],
                    "truncated": False,
                },
            }
        }
    )

    assert compact["artifactId"] == "art_table"
    assert compact["kind"] == "table"
    assert compact["truncated"] is True
    assert len(compact["columns"]) == 12
    assert len(compact["rows"]) == 5
    assert all(len(str(cell)) <= 128 for cell in compact["columns"])
    assert all(len(str(cell)) <= 128 for row in compact["rows"] for cell in row)
    assert len(json.dumps(compact, ensure_ascii=False)) < 12_000
