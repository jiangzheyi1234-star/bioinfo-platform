from __future__ import annotations

from apps.api.run_submission_status import classify_run_submission_status


def test_readiness_failure_is_service_unavailable() -> None:
    assert (
        classify_run_submission_status(
            detail="Remote workflow runtime is unavailable: snakemake missing",
            fallback=400,
        )
        == 503
    )


def test_input_failure_keeps_fallback_status() -> None:
    assert classify_run_submission_status(detail="pipelineId is required", fallback=400) == 400
