from __future__ import annotations


def classify_run_submission_status(*, detail: str, fallback: int) -> int:
    lowered = detail.lower()
    if "workflow_tool_not_ready" in lowered or "workflow tool not ready" in lowered:
        return 409
    readiness_markers = (
        "not ready",
        "workflow runtime",
        "snakemake",
        "conda",
        "workflow profile",
        "pipeline registry",
        "canary",
        "prepare the remote workspace",
        "ssh is not connected",
        "ssh disconnected",
    )
    if any(marker in lowered for marker in readiness_markers):
        return 503
    return fallback
