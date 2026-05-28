from __future__ import annotations

from typing import Any


def rule_template_candidates(tool: dict[str, Any], tool_request: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for owner in [tool, tool_request]:
        template = owner.get("ruleTemplate")
        if isinstance(template, dict) and has_rule_action(template):
            candidates.append(template)
        draft = owner.get("ruleSpecDraft")
        if isinstance(draft, dict):
            draft_template = draft.get("ruleTemplate")
            if isinstance(draft_template, dict) and has_rule_action(draft_template):
                candidates.append(draft_template)
    return candidates


def has_rule_action(template: dict[str, Any]) -> bool:
    return bool(str(template.get("commandTemplate") or "").strip() or str(template.get("wrapper") or "").strip())
