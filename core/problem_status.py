from __future__ import annotations


VALIDATION_ERROR_PREFIXES = ("INPUT_", "TOOL_", "WORKFLOW_", "RESOURCE_")
CONFLICT_ERROR_PREFIXES = ("CAPABILITY_BUNDLE_NOT_SELECTABLE",)


def problem_value_error_status_code(detail: str) -> int:
    if detail.startswith(CONFLICT_ERROR_PREFIXES):
        return 409
    if detail.startswith(VALIDATION_ERROR_PREFIXES):
        return 422
    return 400
