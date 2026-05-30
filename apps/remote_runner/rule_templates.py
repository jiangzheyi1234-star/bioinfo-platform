from __future__ import annotations

from typing import Any


def rule_template_candidates(tool: dict[str, Any], tool_request: dict[str, Any]) -> list[dict[str, Any]]:
    return [entry["template"] for entry in rule_template_candidate_entries(tool, tool_request)]


def rule_template_candidate_entries(tool: dict[str, Any], tool_request: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    # The request may carry a UI snapshot of the RuleSpec for audit/debug display,
    # but executable workflow contracts must come from the registered tool record.
    for owner in [tool]:
        draft = owner.get("ruleSpecDraft")
        rule_spec_draft = draft if isinstance(draft, dict) else {}
        template = owner.get("ruleTemplate")
        if isinstance(template, dict) and has_rule_action(template):
            candidates.append({"template": template, "ruleSpecDraft": rule_spec_draft})
    return candidates


def has_rule_action(template: dict[str, Any]) -> bool:
    return bool(
        str(template.get("commandTemplate") or "").strip()
        or str(template.get("wrapper") or "").strip()
        or str(template.get("script") or "").strip()
        or (isinstance(template.get("module"), dict) and template["module"])
    )
