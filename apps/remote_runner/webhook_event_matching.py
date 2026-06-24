from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
from typing import Any


@dataclass(frozen=True)
class WebhookTriggerEventMatchPolicy:
    provider: str
    event_types: tuple[str, ...]
    actions: tuple[str, ...]
    schema_version: str = "webhook-trigger-event-match-policy.v1"

    def safe_details(self) -> dict[str, object]:
        return {
            "schemaVersion": self.schema_version,
            "provider": self.provider,
            "eventTypes": list(self.event_types),
            "actions": list(self.actions),
        }


@dataclass(frozen=True)
class WebhookTriggerEventMatch:
    policy: WebhookTriggerEventMatchPolicy
    source: str
    event_type: str
    action: str | None

    def safe_details(self) -> dict[str, object]:
        return {
            **self.policy.safe_details(),
            "source": self.source,
            "eventType": self.event_type,
            **({"action": self.action} if self.action else {}),
        }


class WebhookTriggerEventMatchError(ValueError):
    def __init__(self, code: str, *, safe_details: Mapping[str, object] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.safe_details = dict(safe_details or {})


def resolve_webhook_trigger_event_match_policy(trigger_spec: Mapping[str, Any]) -> WebhookTriggerEventMatchPolicy:
    if not isinstance(trigger_spec, Mapping):
        _raise("WORKFLOW_TRIGGER_WEBHOOK_TRIGGER_SPEC_REQUIRED", field="triggerSpec")
    provider = _required_label(trigger_spec.get("provider"), field="provider")
    event_match = trigger_spec.get("eventMatch")
    if not isinstance(event_match, Mapping):
        _raise("WORKFLOW_TRIGGER_WEBHOOK_EVENT_MATCH_REQUIRED", field="eventMatch")
    return WebhookTriggerEventMatchPolicy(
        provider=provider,
        event_types=_required_label_list(event_match, field="eventMatch.eventTypes"),
        actions=_optional_label_list(event_match, field="eventMatch.actions"),
    )


def require_webhook_trigger_event_match(
    trigger_spec: Mapping[str, Any],
    *,
    source: object,
    event_type: object,
    payload: Mapping[str, Any],
) -> WebhookTriggerEventMatch:
    policy = resolve_webhook_trigger_event_match_policy(trigger_spec)
    normalized_source = _required_label(source, field="source")
    normalized_event_type = _required_label(event_type, field="eventType")
    if normalized_source != policy.provider:
        _raise(
            "WORKFLOW_TRIGGER_WEBHOOK_SOURCE_MISMATCH",
            provider=policy.provider,
            source=normalized_source,
        )
    if policy.event_types and normalized_event_type not in policy.event_types:
        _raise(
            "WORKFLOW_TRIGGER_WEBHOOK_EVENT_TYPE_UNSUPPORTED",
            provider=policy.provider,
            event_type=normalized_event_type,
            allowed_event_types=policy.event_types,
        )
    action = _payload_action(payload)
    if policy.actions:
        if action is None:
            _raise(
                "WORKFLOW_TRIGGER_WEBHOOK_ACTION_REQUIRED",
                provider=policy.provider,
                event_type=normalized_event_type,
                allowed_actions=policy.actions,
            )
        if action not in policy.actions:
            _raise(
                "WORKFLOW_TRIGGER_WEBHOOK_ACTION_UNSUPPORTED",
                provider=policy.provider,
                event_type=normalized_event_type,
                allowed_actions=policy.actions,
                received_action=action,
            )
    return WebhookTriggerEventMatch(
        policy=policy,
        source=normalized_source,
        event_type=normalized_event_type,
        action=action,
    )


def _required_label_list(mapping: Mapping[str, Any], *, field: str) -> tuple[str, ...]:
    raw = mapping.get(field.rsplit(".", 1)[-1])
    if not isinstance(raw, list) or not raw:
        _raise(f"WORKFLOW_TRIGGER_WEBHOOK_{_field_code(field)}_MALFORMED", field=field)
    labels = tuple(_required_label(item, field=f"{field}[]") for item in raw)
    if len(set(labels)) != len(labels):
        _raise(f"WORKFLOW_TRIGGER_WEBHOOK_{_field_code(field)}_DUPLICATE", field=field)
    return labels


def _optional_label_list(mapping: Mapping[str, Any], *, field: str) -> tuple[str, ...]:
    leaf = field.rsplit(".", 1)[-1]
    if leaf not in mapping:
        return ()
    return _required_label_list(mapping, field=field)


def _payload_action(payload: Mapping[str, Any]) -> str | None:
    if not isinstance(payload, Mapping) or "action" not in payload:
        return None
    value = payload.get("action")
    if value is None:
        return None
    return _required_label(value, field="payload.action")


def _required_label(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        _raise("WORKFLOW_TRIGGER_WEBHOOK_LABEL_MALFORMED", field=field)
    normalized = value.strip().lower()
    if not normalized:
        _raise("WORKFLOW_TRIGGER_WEBHOOK_LABEL_MALFORMED", field=field)
    if len(normalized) > 128:
        _raise("WORKFLOW_TRIGGER_WEBHOOK_LABEL_TOO_LONG", field=field)
    return normalized


def _field_code(field: str) -> str:
    chars: list[str] = []
    for character in field:
        if character.isalnum():
            if character.isupper() and chars:
                chars.append("_")
            chars.append(character.upper())
        else:
            chars.append("_")
    return "_".join(part for part in "".join(chars).split("_") if part)


def _label_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _raise(
    code: str,
    *,
    field: str | None = None,
    provider: str | None = None,
    source: str | None = None,
    event_type: str | None = None,
    allowed_event_types: tuple[str, ...] | None = None,
    allowed_actions: tuple[str, ...] | None = None,
    received_action: str | None = None,
) -> None:
    details: dict[str, object] = {}
    if field:
        details["field"] = field
    if provider:
        details["provider"] = provider
    if source:
        details["source"] = source
    if event_type:
        details["eventType"] = event_type
    if allowed_event_types:
        details["allowedEventTypes"] = list(allowed_event_types)
    if allowed_actions:
        details["allowedActions"] = list(allowed_actions)
    if received_action:
        details["receivedActionHash"] = _label_hash(received_action)
        details["receivedActionLength"] = len(received_action)
    raise WebhookTriggerEventMatchError(code, safe_details=details)
