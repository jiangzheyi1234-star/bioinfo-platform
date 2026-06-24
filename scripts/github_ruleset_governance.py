from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


GITHUB_MAIN_BRANCH_RULESET = ".github/rulesets/main-branch-ruleset.target.json"
REQUIRED_STATUS_CHECKS = ("required / ci-green",)
REQUIRED_RULE_TYPES = (
    "deletion",
    "non_fast_forward",
    "pull_request",
    "required_linear_history",
    "required_status_checks",
)
OPTIONAL_SECURITY_RULE_TYPES = {"code_scanning", "workflows"}


@dataclass(frozen=True)
class GithubRulesetFinding:
    code: str
    path: str
    line: int
    detail: str


def scan_github_main_branch_ruleset_contract(
    relative: str,
    source: str,
) -> list[GithubRulesetFinding]:
    if relative != GITHUB_MAIN_BRANCH_RULESET:
        return []
    if not source.strip():
        return [_finding("github-ruleset-missing", relative, "main branch ruleset policy is missing")]
    try:
        payload = json.loads(source)
    except json.JSONDecodeError as exc:
        return [_finding("github-ruleset-json", relative, f"ruleset policy is not valid JSON: {exc.msg}")]

    findings: list[GithubRulesetFinding] = []
    _require_equal(findings, relative, payload, "policy_schema_version", 1)
    _require_equal(findings, relative, payload, "github_api_version", "2026-03-10")
    _require_equal(findings, relative, payload, "remote_application", "manual-only")
    ruleset = payload.get("ruleset") if isinstance(payload.get("ruleset"), dict) else {}
    _require_equal(findings, relative, ruleset, "name", "h2ometa-main-branch-ruleset-v1")
    _require_equal(findings, relative, ruleset, "target", "branch")
    _require_equal(findings, relative, ruleset, "enforcement", "active")
    _require_equal(findings, relative, ruleset, "bypass_actors", [])

    ref_name = _nested_dict(ruleset, "conditions", "ref_name")
    if "refs/heads/main" not in _as_string_list(ref_name.get("include")):
        findings.append(_finding("github-ruleset-ref-target", relative, "ruleset must include refs/heads/main"))
    if ref_name.get("exclude") != []:
        findings.append(_finding("github-ruleset-ref-target", relative, "ruleset must not exclude main refs"))

    rules = _rules_by_type(ruleset.get("rules"))
    for rule_type in REQUIRED_RULE_TYPES:
        if rule_type not in rules:
            findings.append(_finding("github-ruleset-rule-missing", relative, f"ruleset missing {rule_type}"))
    for rule_type in OPTIONAL_SECURITY_RULE_TYPES:
        if rule_type in rules:
            findings.append(
                _finding(
                    "github-ruleset-optional-security-required",
                    relative,
                    "CodeQL/Scorecard-derived rules must stay optional until repository feature availability is proven",
                )
            )

    findings.extend(_scan_pull_request_rule(relative, rules.get("pull_request", {})))
    findings.extend(_scan_required_status_checks_rule(relative, rules.get("required_status_checks", {})))
    return findings


def _scan_pull_request_rule(relative: str, rule: dict[str, Any]) -> list[GithubRulesetFinding]:
    parameters = rule.get("parameters", {}) if isinstance(rule, dict) else {}
    findings: list[GithubRulesetFinding] = []
    for key in (
        "dismiss_stale_reviews_on_push",
        "require_code_owner_review",
        "require_last_push_approval",
        "required_review_thread_resolution",
    ):
        if parameters.get(key) is not True:
            findings.append(_finding("github-ruleset-pr-review", relative, f"pull_request must set {key}: true"))
    if parameters.get("required_approving_review_count", 0) < 1:
        findings.append(_finding("github-ruleset-pr-review", relative, "pull_request must require at least one approval"))
    if set(_as_string_list(parameters.get("allowed_merge_methods"))) != {"squash", "rebase"}:
        findings.append(_finding("github-ruleset-linear-history", relative, "only squash and rebase merges are allowed"))
    return findings


def _scan_required_status_checks_rule(relative: str, rule: dict[str, Any]) -> list[GithubRulesetFinding]:
    parameters = rule.get("parameters", {}) if isinstance(rule, dict) else {}
    findings: list[GithubRulesetFinding] = []
    if parameters.get("strict_required_status_checks_policy") is not True:
        findings.append(_finding("github-ruleset-status-checks", relative, "required checks must use latest base code"))
    if parameters.get("do_not_enforce_on_create") is not False:
        findings.append(_finding("github-ruleset-status-checks", relative, "required checks must be enforced on creation"))
    contexts = {
        item.get("context")
        for item in parameters.get("required_status_checks", [])
        if isinstance(item, dict)
    }
    if contexts != set(REQUIRED_STATUS_CHECKS):
        findings.append(
            _finding(
                "github-ruleset-status-checks",
                relative,
                "ruleset must require only the stable aggregate required / ci-green status check",
            )
        )
    return findings


def _require_equal(
    findings: list[GithubRulesetFinding],
    relative: str,
    payload: dict[str, Any],
    key: str,
    expected: Any,
) -> None:
    if payload.get(key) != expected:
        findings.append(_finding("github-ruleset-top-level", relative, f"ruleset {key} must be {expected!r}"))


def _nested_dict(payload: dict[str, Any], *keys: str) -> dict[str, Any]:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return current if isinstance(current, dict) else {}


def _rules_by_type(rules: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(rules, list):
        return {}
    return {rule.get("type"): rule for rule in rules if isinstance(rule, dict) and isinstance(rule.get("type"), str)}


def _as_string_list(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _finding(code: str, path: str, detail: str) -> GithubRulesetFinding:
    return GithubRulesetFinding(code, path, 0, detail)
