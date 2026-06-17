import pytest

from scripts.finalize_gtdbtk_p0_8c_validation import audit_capability_graph_completion


def _complete_graph() -> dict[str, object]:
    profile_ids = [f"tool-{index}" for index in range(122)] + ["gtdbtk-classify"]
    return {
        "profileCount": 123,
        "agentSelectableTools": [{"profileId": profile_id} for profile_id in profile_ids],
        "agentSelectableProfileIds": profile_ids,
        "capabilityBundles": [{"profileId": profile_id} for profile_id in profile_ids],
        "validationQueue": {"items": []},
    }


def test_audit_capability_graph_completion_accepts_123_ready_tools() -> None:
    audit = audit_capability_graph_completion(_complete_graph())

    assert audit["ok"] is True
    assert audit["profileCount"] == 123
    assert audit["agentSelectableCount"] == 123
    assert audit["capabilityBundleCount"] == 123
    assert audit["gtdbtkAgentSelectable"] is True


def test_audit_capability_graph_completion_rejects_missing_gtdbtk_selectable() -> None:
    graph = _complete_graph()
    graph["agentSelectableProfileIds"] = [f"tool-{index}" for index in range(123)]

    with pytest.raises(SystemExit) as exc_info:
        audit_capability_graph_completion(graph)

    assert "gtdbtk-classify is not agent selectable" in str(exc_info.value)


def test_audit_capability_graph_completion_rejects_remaining_validation_queue() -> None:
    graph = _complete_graph()
    graph["validationQueue"] = {
        "items": [
            {
                "profileId": "gtdbtk-classify",
                "candidateId": "h2ometa-tool-profile::gtdbtk-classify",
            }
        ]
    }

    with pytest.raises(SystemExit) as exc_info:
        audit_capability_graph_completion(graph)

    message = str(exc_info.value)
    assert "validationRemaining=1 expected=0" in message
    assert "gtdbtk-classify is still in validation queue" in message
