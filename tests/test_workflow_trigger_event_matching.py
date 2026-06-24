from __future__ import annotations

import pytest

from apps.remote_runner.webhook_event_matching import (
    WebhookTriggerEventMatchError,
    require_webhook_trigger_event_match,
    resolve_webhook_trigger_event_match_policy,
)


def test_webhook_event_match_policy_resolves_safe_exact_allowlists() -> None:
    policy = resolve_webhook_trigger_event_match_policy(
        {
            "provider": " GitHub ",
            "eventMatch": {
                "eventTypes": ["Push"],
                "actions": ["Opened"],
            },
        }
    )

    assert policy.provider == "github"
    assert policy.event_types == ("push",)
    assert policy.actions == ("opened",)
    assert policy.safe_details() == {
        "schemaVersion": "webhook-trigger-event-match-policy.v1",
        "provider": "github",
        "eventTypes": ["push"],
        "actions": ["opened"],
    }


def test_webhook_event_match_accepts_matching_source_event_type_and_action() -> None:
    match = require_webhook_trigger_event_match(
        {
            "provider": "github",
            "eventMatch": {
                "eventTypes": ["pull_request"],
                "actions": ["opened"],
            },
        },
        source="GitHub",
        event_type="Pull_Request",
        payload={"action": "Opened", "secret": "payload-secret"},
    )

    assert match.source == "github"
    assert match.event_type == "pull_request"
    assert match.action == "opened"
    assert match.safe_details()["provider"] == "github"
    assert "payload-secret" not in repr(match)


def test_webhook_event_match_rejects_source_mismatch_without_payload_leak() -> None:
    error = _assert_error(
        {
            "provider": "github",
            "eventMatch": {"eventTypes": ["push"]},
        },
        source="slack",
        event_type="push",
        payload={"token": "payload-secret"},
        code="WORKFLOW_TRIGGER_WEBHOOK_SOURCE_MISMATCH",
    )

    assert error.safe_details["provider"] == "github"
    assert error.safe_details["source"] == "slack"
    assert "payload-secret" not in repr(error.safe_details)


def test_webhook_event_match_rejects_event_type_and_action_mismatch_safely() -> None:
    event_error = _assert_error(
        {
            "provider": "github",
            "eventMatch": {"eventTypes": ["push"]},
        },
        source="github",
        event_type="pull_request",
        payload={"action": "opened"},
        code="WORKFLOW_TRIGGER_WEBHOOK_EVENT_TYPE_UNSUPPORTED",
    )
    action_error = _assert_error(
        {
            "provider": "github",
            "eventMatch": {"eventTypes": ["pull_request"], "actions": ["closed"]},
        },
        source="github",
        event_type="pull_request",
        payload={"action": "opened", "token": "payload-secret"},
        code="WORKFLOW_TRIGGER_WEBHOOK_ACTION_UNSUPPORTED",
    )

    assert event_error.safe_details["allowedEventTypes"] == ["push"]
    assert action_error.safe_details["allowedActions"] == ["closed"]
    assert "receivedActionHash" in action_error.safe_details
    assert "opened" not in repr(action_error.safe_details)
    assert "payload-secret" not in repr(action_error.safe_details)


@pytest.mark.parametrize(
    ("trigger_spec", "code"),
    [
        ({}, "WORKFLOW_TRIGGER_WEBHOOK_LABEL_MALFORMED"),
        ({"provider": "github"}, "WORKFLOW_TRIGGER_WEBHOOK_EVENT_MATCH_REQUIRED"),
        ({"provider": "github", "eventMatch": {}}, "WORKFLOW_TRIGGER_WEBHOOK_EVENT_MATCH_EVENT_TYPES_MALFORMED"),
        (
            {"provider": "github", "eventMatch": {"eventTypes": ["push", "push"]}},
            "WORKFLOW_TRIGGER_WEBHOOK_EVENT_MATCH_EVENT_TYPES_DUPLICATE",
        ),
        (
            {"provider": "github", "eventMatch": {"eventTypes": ["push"], "actions": []}},
            "WORKFLOW_TRIGGER_WEBHOOK_EVENT_MATCH_ACTIONS_MALFORMED",
        ),
    ],
)
def test_webhook_event_match_policy_rejects_malformed_contract(
    trigger_spec: dict[str, object],
    code: str,
) -> None:
    with pytest.raises(WebhookTriggerEventMatchError, match=code):
        resolve_webhook_trigger_event_match_policy(trigger_spec)


def test_webhook_event_match_requires_action_when_allowlist_is_configured() -> None:
    _assert_error(
        {
            "provider": "github",
            "eventMatch": {"eventTypes": ["pull_request"], "actions": ["opened"]},
        },
        source="github",
        event_type="pull_request",
        payload={},
        code="WORKFLOW_TRIGGER_WEBHOOK_ACTION_REQUIRED",
    )


def _assert_error(
    trigger_spec: dict[str, object],
    *,
    source: str,
    event_type: str,
    payload: dict[str, object],
    code: str,
) -> WebhookTriggerEventMatchError:
    with pytest.raises(WebhookTriggerEventMatchError, match=code) as exc_info:
        require_webhook_trigger_event_match(
            trigger_spec,
            source=source,
            event_type=event_type,
            payload=payload,
        )
    assert exc_info.value.code == code
    assert str(exc_info.value) == code
    return exc_info.value
