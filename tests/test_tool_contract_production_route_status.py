from __future__ import annotations

from pathlib import Path


PRODUCTION_CONFLICT_ERRORS = (
    "TOOL_PRODUCTION_REQUIRES_OUTPUT_VALIDATION",
    "TOOL_PRODUCTION_REQUIRES_WORKFLOW_READY",
    "TOOL_PRODUCTION_EVIDENCE_RUN_NOT_FOUND",
    "TOOL_PRODUCTION_EVIDENCE_RUN_NOT_COMPLETED",
    "TOOL_PRODUCTION_EVIDENCE_PIPELINE_MISMATCH",
    "TOOL_PRODUCTION_EVIDENCE_TOOL_MISMATCH",
    "TOOL_PRODUCTION_EVIDENCE_ARTIFACT_REQUIRED",
    "TOOL_PRODUCTION_EVIDENCE_ARTIFACT_NOT_FOUND",
    "TOOL_PRODUCTION_EVIDENCE_ARTIFACT_EMPTY",
    "TOOL_PRODUCTION_EVIDENCE_DATABASE_MISMATCH",
    "TOOL_PRODUCTION_EVIDENCE_DATABASE_UNAVAILABLE",
)


def test_production_route_maps_workflow_ready_gate_to_conflict_status() -> None:
    root = Path(__file__).resolve().parents[1]
    remote_main = (root / "apps" / "remote_runner" / "main.py").read_text(encoding="utf-8")
    local_route = (root / "apps" / "api" / "tool_contract_routes.py").read_text(encoding="utf-8")

    for error_code in PRODUCTION_CONFLICT_ERRORS:
        assert f'"{error_code}"' in remote_main
        assert f'"{error_code}"' in local_route
    assert "status_code = 409" in remote_main
    assert "status_code = 409" in local_route
