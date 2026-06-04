from __future__ import annotations

import apps.remote_runner.tools_errors as tool_errors
from pathlib import Path

from apps.api.route_errors import runtime_service_status_code


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


def test_tool_registry_status_codes_live_on_domain_errors() -> None:
    root = Path(__file__).resolve().parents[1]
    errors_source = (root / "apps" / "remote_runner" / "tools_errors.py").read_text(encoding="utf-8")
    remote_errors = (root / "apps" / "remote_runner" / "route_errors.py").read_text(encoding="utf-8")
    local_errors = (root / "apps" / "api" / "route_errors.py").read_text(encoding="utf-8")

    assert hasattr(tool_errors, "ToolNotFoundError")
    assert hasattr(tool_errors, "ToolProductionConflictError")
    assert tool_errors.ToolRegistryError("TOOL_ID_REQUIRED").status_code == 400
    assert tool_errors.ToolNotFoundError("TOOL_NOT_FOUND").status_code == 404
    for error_code in PRODUCTION_CONFLICT_ERRORS:
        assert tool_errors.ToolProductionConflictError(error_code).status_code == 409
    assert tool_errors.ToolRegistryError("TOOL_PRODUCTION_EVIDENCE_RUN_ID_REQUIRED").status_code == 400

    assert "class ToolProductionConflictError(ToolRegistryError)" in errors_source
    assert "tool_route_status" not in remote_errors
    assert "tool_production_status_code" not in remote_errors
    assert "tool_route_status" not in local_errors
    assert "tool_production_status_code" not in local_errors
    assert "normalized.startswith(\"TOOL_PRODUCTION_\")" not in local_errors
    assert "return _detail_response(exc.status_code, str(exc))" in remote_errors

    assert runtime_service_status_code("runner http error 409: TOOL_PRODUCTION_REQUIRES_WORKFLOW_READY") == 409
    assert runtime_service_status_code("runner http error 404: TOOL_NOT_FOUND") == 404
    assert runtime_service_status_code("TOOL_PRODUCTION_EVIDENCE_RUN_ID_REQUIRED") == 400
