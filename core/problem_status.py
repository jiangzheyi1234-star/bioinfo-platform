from __future__ import annotations


VALIDATION_ERROR_PREFIXES = ("INPUT_", "TOOL_", "WORKFLOW_", "RESOURCE_")


def problem_value_error_status_code(detail: str) -> int:
    if detail.startswith(VALIDATION_ERROR_PREFIXES):
        return 422
    return 400
