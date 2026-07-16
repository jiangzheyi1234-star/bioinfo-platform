from __future__ import annotations

from copy import deepcopy

import pytest

from core.contracts.execution_activity import summarize_execution_activity


def test_legacy_diagnostics_without_tool_prepare_activity_remain_readable() -> None:
    activity = summarize_execution_activity(
        _diagnostics(include_tool_prepare=False),
        make_error=ValueError,
    )

    assert activity["queuedToolPrepareJobCount"] == 0
    assert activity["runningToolPrepareJobCount"] == 0
    assert activity["activeToolPrepareClaimCount"] == 0


def test_ledger_backed_tool_prepare_activity_is_accepted() -> None:
    activity = summarize_execution_activity(
        _diagnostics(),
        make_error=ValueError,
    )

    assert activity["queuedToolPrepareJobCount"] == 1
    assert activity["runningToolPrepareJobCount"] == 2
    assert activity["activeToolPrepareClaimCount"] == 3


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("queued", "1"),
        ("running", True),
        ("activeClaims", -1),
        ("openAttemptCount", None),
        ("projectionMismatchCount", "0"),
    ],
)
def test_malformed_tool_prepare_counts_fail_closed(key: str, value: object) -> None:
    diagnostics = _diagnostics()
    diagnostics["toolPrepareJobs"][key] = value

    with pytest.raises(ValueError, match="toolPrepareJobs"):
        summarize_execution_activity(diagnostics, make_error=ValueError)


def test_present_tool_prepare_activity_requires_legacy_counts() -> None:
    diagnostics = _diagnostics()
    diagnostics["toolPrepareJobs"].pop("activeClaims")

    with pytest.raises(ValueError, match="activeClaims"):
        summarize_execution_activity(diagnostics, make_error=ValueError)


def test_empty_tool_prepare_activity_fails_closed() -> None:
    diagnostics = _diagnostics()
    diagnostics["toolPrepareJobs"] = {}

    with pytest.raises(ValueError, match="toolPrepareJobs.queued"):
        summarize_execution_activity(diagnostics, make_error=ValueError)


def test_partial_or_inconsistent_ledger_counts_fail_closed() -> None:
    partial = _diagnostics()
    partial["toolPrepareJobs"].pop("projectionMismatchCount")
    inconsistent = _diagnostics()
    inconsistent["toolPrepareJobs"]["openAttemptCount"] = 4

    with pytest.raises(ValueError, match="ledger counts are incomplete"):
        summarize_execution_activity(partial, make_error=ValueError)
    with pytest.raises(ValueError, match="open attempt counts are inconsistent"):
        summarize_execution_activity(inconsistent, make_error=ValueError)


def test_projection_violation_count_must_match_safe_details() -> None:
    diagnostics = _diagnostics()
    diagnostics["toolPrepareJobs"]["projectionMismatchCount"] = 1

    with pytest.raises(ValueError, match="projection violations are inconsistent"):
        summarize_execution_activity(diagnostics, make_error=ValueError)


def test_unknown_tool_prepare_activity_schema_fails_closed() -> None:
    diagnostics = _diagnostics()
    diagnostics["toolPrepareJobs"]["schemaVersion"] = "tool-prepare-activity.v999"

    with pytest.raises(ValueError, match="schemaVersion is invalid"):
        summarize_execution_activity(diagnostics, make_error=ValueError)


def _diagnostics(*, include_tool_prepare: bool = True) -> dict[str, object]:
    payload: dict[str, object] = {
        "schemaVersion": "execution-diagnostics.v1",
        "ok": True,
        "activeLeases": [],
        "allocatedResources": [],
        "resourceWaits": [],
        "workerHealth": {
            "claimedJobs": 0,
            "summary": {"runningSlots": 0},
            "workers": [],
        },
        "queueMetrics": {"queuedJobs": 0, "queueDepth": 0, "claimedJobs": 0},
        "invariants": {"ok": True},
    }
    if include_tool_prepare:
        payload["toolPrepareJobs"] = deepcopy(
            {
                "schemaVersion": "tool-prepare-activity.v1",
                "queued": 1,
                "running": 2,
                "active": 3,
                "activeClaims": 3,
                "activeAttemptCount": 2,
                "recoveryRequiredAttemptCount": 1,
                "expiredActiveAttemptCount": 1,
                "openAttemptCount": 3,
                "jobClaimProjectionCount": 3,
                "projectionMismatchCount": 0,
                "projectionViolations": [],
            }
        )
    return payload
