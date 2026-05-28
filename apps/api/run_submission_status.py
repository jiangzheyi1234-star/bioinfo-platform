from __future__ import annotations


def classify_run_submission_status(*, detail: str, fallback: int) -> int:
    lowered = detail.lower()
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
