from __future__ import annotations

from scripts.score_remote_agent_lifecycle import build_scorecard


def test_remote_agent_scorecard_passes_current_lifecycle_contract() -> None:
    scorecard = build_scorecard()

    assert scorecard["schemaVersion"] == "h2ometa-remote-agent-scorecard.v1"
    assert scorecard["score"] == scorecard["maxScore"]
    assert scorecard["percent"] == 100.0
    assert all(item["passed"] for item in scorecard["criteria"])


def test_remote_agent_scorecard_includes_required_domains() -> None:
    scorecard = build_scorecard()
    keys = {item["key"] for item in scorecard["criteria"]}

    assert {
        "release_traceability",
        "immutable_remote_layout",
        "idempotent_ssh_bootstrap",
        "managed_service_supervision",
        "readiness_gate",
        "bootstrap_canary",
        "rollback_activation",
        "operator_diagnostics",
        "remote_acceptance_tests",
        "documented_lifecycle_states",
    } <= keys
