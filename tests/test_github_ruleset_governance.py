from __future__ import annotations

import copy
import json
from pathlib import Path

from scripts.github_ruleset_governance import (
    GITHUB_MAIN_BRANCH_RULESET,
    scan_github_main_branch_ruleset_contract,
)


ROOT = Path(__file__).resolve().parents[1]


def _source() -> str:
    return (ROOT / GITHUB_MAIN_BRANCH_RULESET).read_text(encoding="utf-8")


def _finding_codes(source: str) -> set[str]:
    findings = scan_github_main_branch_ruleset_contract(GITHUB_MAIN_BRANCH_RULESET, source)
    return {finding.code for finding in findings}


def test_github_main_branch_ruleset_policy_matches_contract() -> None:
    source = _source()
    payload = json.loads(source)

    assert scan_github_main_branch_ruleset_contract(GITHUB_MAIN_BRANCH_RULESET, source) == []
    assert payload["policy_schema_version"] == 1
    assert payload["github_api_version"] == "2026-03-10"
    assert payload["remote_application"] == "manual-only"
    assert payload["ruleset"]["conditions"]["ref_name"]["include"] == ["refs/heads/main"]


def test_github_main_branch_ruleset_policy_rejects_softened_gates() -> None:
    payload = json.loads(_source())
    ruleset = payload["ruleset"]

    weakened = copy.deepcopy(payload)
    weakened["ruleset"]["bypass_actors"] = [{"actor_type": "RepositoryRole", "actor_id": 5}]
    assert "github-ruleset-top-level" in _finding_codes(json.dumps(weakened))

    optional_security_required = copy.deepcopy(payload)
    optional_security_required["ruleset"]["rules"].append({"type": "code_scanning"})
    assert "github-ruleset-optional-security-required" in _finding_codes(json.dumps(optional_security_required))

    unstable_checks = copy.deepcopy(payload)
    status_rule = next(rule for rule in unstable_checks["ruleset"]["rules"] if rule["type"] == "required_status_checks")
    status_rule["parameters"]["strict_required_status_checks_policy"] = False
    status_rule["parameters"]["required_status_checks"].append({"context": "security / scorecard"})
    assert "github-ruleset-status-checks" in _finding_codes(json.dumps(unstable_checks))

    direct_to_main = copy.deepcopy(payload)
    direct_to_main["ruleset"]["rules"] = [rule for rule in ruleset["rules"] if rule["type"] != "pull_request"]
    assert "github-ruleset-rule-missing" in _finding_codes(json.dumps(direct_to_main))
