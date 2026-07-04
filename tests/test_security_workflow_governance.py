from __future__ import annotations

from pathlib import Path

from scripts import security_workflow_governance as workflow_governance
from scripts.security_governance_common import Finding


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_security_workflow_governance_rejects_unsafe_workflow_fixtures() -> None:
    unversioned_action = """
name: Unsafe
on:
  pull_request:
permissions:
  contents: read
jobs:
  test:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout
"""
    write_on_pr = """
name: Unsafe Write
on:
  pull_request:
permissions:
  contents: read
jobs:
  publish:
    runs-on: ubuntu-24.04
    permissions:
      contents: write
    steps:
      - run: echo unsafe
"""
    workflow_run = """
name: Unsafe Trigger
on:
  workflow_run:
    workflows: ["CI"]
    types: [completed]
permissions:
  contents: read
jobs:
  followup:
    runs-on: ubuntu-24.04
    steps:
      - run: echo unsafe
"""
    upload_artifact_missing_retention = """
name: Missing Retention
on:
  workflow_dispatch:
permissions:
  contents: read
jobs:
  collect:
    runs-on: ubuntu-24.04
    steps:
      - name: Upload logs
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02
        with:
          name: logs
          path: logs/
"""
    upload_artifact_long_retention = """
name: Long Retention
on:
  workflow_dispatch:
permissions:
  contents: read
jobs:
  collect:
    runs-on: ubuntu-24.04
    steps:
      - name: Upload logs
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02
        with:
          name: logs
          path: logs/
          retention-days: 14
"""
    upload_artifact_expression_retention = """
name: Dynamic Retention
on:
  workflow_dispatch:
permissions:
  contents: read
jobs:
  collect:
    runs-on: ubuntu-24.04
    steps:
      - name: Upload logs
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02
        with:
          name: logs
          path: logs/
          retention-days: ${{ inputs.retention_days }}
"""
    dependency_review_warn_only = """
name: Dependency Review
"on":
  pull_request:
permissions:
  contents: read
jobs:
  dependency_review:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/dependency-review-action@a1d282b36b6f3519aa1f3fc636f609c47dddb294
        with:
          fail-on-severity: high
          comment-summary-in-pr: on-failure
          warn-only: true
"""
    checkout_persist_credentials = """
name: Checkout Token
on:
  pull_request:
permissions:
  contents: read
jobs:
  test:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
"""
    checkout_persist_credentials_true = """
name: Checkout Token True
on:
  pull_request:
permissions:
  contents: read
jobs:
  test:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
        with:
          persist-credentials: true
"""
    checkout_persist_credentials_env_spoof = """
name: Checkout Token Env Spoof
on:
  pull_request:
permissions:
  contents: read
jobs:
  test:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
        env:
          persist-credentials: false
"""
    security_analysis_soft_fail = """
name: Security Analysis
"on":
  push:
    branches:
      - main
  schedule:
    - cron: "34 3 * * 2"
  workflow_dispatch:
permissions:
  contents: read
jobs:
  codeql:
    runs-on: ubuntu-24.04
    permissions:
      contents: read
      security-events: write
    steps:
      - uses: github/codeql-action/init@8aad20d150bbac5944a9f9d289da16a4b0d87c1e
      - uses: github/codeql-action/analyze@8aad20d150bbac5944a9f9d289da16a4b0d87c1e
        continue-on-error: true
  scorecard:
    runs-on: ubuntu-24.04
    permissions:
      contents: read
      id-token: write
      security-events: write
    steps:
      - uses: ossf/scorecard-action@4eaacf0543bb3f2c246792bd56e8cdeffafb205a
        with:
          results_file: results.sarif
          results_format: sarif
          publish_results: false
"""
    security_analysis_pr_upload = """
name: Security Analysis
"on":
  pull_request:
permissions:
  contents: read
jobs:
  scorecard:
    runs-on: ubuntu-24.04
    permissions:
      contents: read
      id-token: write
      security-events: write
    steps:
      - uses: ossf/scorecard-action@4eaacf0543bb3f2c246792bd56e8cdeffafb205a
        with:
          results_file: results.sarif
          results_format: sarif
          publish_results: true
"""
    security_analysis_disallowed_scorecard_job = """
name: Security Analysis
"on":
  push:
    branches:
      - main
  schedule:
    - cron: "34 3 * * 2"
  workflow_dispatch:
permissions:
  contents: read
jobs:
  codeql:
    runs-on: ubuntu-24.04
    permissions:
      contents: read
      security-events: write
    steps:
      - uses: github/codeql-action/init@8aad20d150bbac5944a9f9d289da16a4b0d87c1e
        with:
          languages: python
          queries: +security-extended,security-and-quality
      - uses: github/codeql-action/analyze@8aad20d150bbac5944a9f9d289da16a4b0d87c1e
  scorecard:
    runs-on: ubuntu-24.04
    env:
      SCORECARD_EXAMPLE: unsafe
    container: ubuntu:24.04
    permissions:
      contents: read
      id-token: write
      security-events: write
    steps:
      - uses: actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020
      - run: echo unsafe
      - uses: ossf/scorecard-action@4eaacf0543bb3f2c246792bd56e8cdeffafb205a
        with:
          results_file: results.sarif
          results_format: sarif
          publish_results: true
      - uses: github/codeql-action/upload-sarif@8aad20d150bbac5944a9f9d289da16a4b0d87c1e
        with:
          sarif_file: results.sarif
"""
    security_analysis_top_level_inline_env = """
name: Security Analysis
"on":
  push:
    branches:
      - main
  schedule:
    - cron: "34 3 * * 2"
  workflow_dispatch:
permissions:
  contents: read
env: {FOO: bar}
jobs:
  scorecard:
    runs-on: ubuntu-24.04
    permissions:
      contents: read
      id-token: write
      security-events: write
    steps:
      - uses: ossf/scorecard-action@4eaacf0543bb3f2c246792bd56e8cdeffafb205a
        with:
          results_file: results.sarif
          results_format: sarif
          publish_results: true
"""
    security_analysis_windows_scorecard = """
name: Security Analysis
"on":
  push:
    branches:
      - main
  schedule:
    - cron: "34 3 * * 2"
  workflow_dispatch:
permissions:
  contents: read
jobs:
  scorecard:
    runs-on: windows-2022
    permissions:
      contents: read
      id-token: write
      security-events: write
    steps:
      - uses: ossf/scorecard-action@4eaacf0543bb3f2c246792bd56e8cdeffafb205a
        with:
          results_file: results.sarif
          results_format: sarif
          publish_results: true
"""
    ci_with_required_scorecard = """
name: CI
"on":
  pull_request:
permissions:
  contents: read
jobs:
  scorecard:
    runs-on: ubuntu-24.04
    steps:
      - uses: ossf/scorecard-action@4eaacf0543bb3f2c246792bd56e8cdeffafb205a
  ci_green:
    needs: [scorecard]
    runs-on: ubuntu-24.04
    steps:
      - run: echo done
"""

    assert "unpinned-action" in _finding_codes(
        workflow_governance.scan_workflow_security_contract(".github/workflows/unsafe.yml", unversioned_action)
    )
    write_codes = _finding_codes(
        workflow_governance.scan_workflow_security_contract(".github/workflows/unsafe.yml", write_on_pr)
    )
    assert "workflow-permission-write-unapproved" in write_codes
    assert "workflow-write-permission-on-pr" in write_codes
    assert "dangerous-workflow-trigger" in _finding_codes(
        workflow_governance.scan_workflow_security_contract(".github/workflows/unsafe.yml", workflow_run)
    )
    assert "workflow-artifact-retention-missing" in _finding_codes(
        workflow_governance.scan_workflow_security_contract(
            ".github/workflows/unsafe.yml",
            upload_artifact_missing_retention,
        )
    )
    assert "workflow-artifact-retention-too-long" in _finding_codes(
        workflow_governance.scan_workflow_security_contract(
            ".github/workflows/unsafe.yml",
            upload_artifact_long_retention,
        )
    )
    assert "workflow-artifact-retention-invalid" in _finding_codes(
        workflow_governance.scan_workflow_security_contract(
            ".github/workflows/unsafe.yml",
            upload_artifact_expression_retention,
        )
    )
    dependency_review_codes = _finding_codes(
        workflow_governance.scan_workflow_security_contract(
            ".github/workflows/unsafe.yml",
            dependency_review_warn_only,
        )
    )
    assert "dependency-review-pr-only" in dependency_review_codes
    assert "dependency-review-severity" in dependency_review_codes
    assert "dependency-review-pr-comments" in dependency_review_codes
    assert "dependency-review-warn-only" in dependency_review_codes
    assert "workflow-checkout-persist-credentials" in _finding_codes(
        workflow_governance.scan_workflow_security_contract(
            ".github/workflows/unsafe.yml",
            checkout_persist_credentials,
        )
    )
    assert "workflow-checkout-persist-credentials" in _finding_codes(
        workflow_governance.scan_workflow_security_contract(
            ".github/workflows/unsafe.yml",
            checkout_persist_credentials_true,
        )
    )
    assert "workflow-checkout-persist-credentials" in _finding_codes(
        workflow_governance.scan_workflow_security_contract(
            ".github/workflows/unsafe.yml",
            checkout_persist_credentials_env_spoof,
        )
    )
    security_analysis_codes = _finding_codes(
        workflow_governance.scan_workflow_security_contract(
            ".github/workflows/security-analysis.yml",
            security_analysis_soft_fail,
        )
    )
    assert "security-analysis-soft-fail" in security_analysis_codes
    assert "security-analysis-scorecard-contract" in security_analysis_codes
    assert "security-analysis-codeql-contract" in security_analysis_codes
    assert "security-analysis-scorecard-contract" in _finding_codes(
        workflow_governance.scan_workflow_security_contract(
            ".github/workflows/security-analysis.yml",
            security_analysis_pr_upload,
        )
    )
    assert "security-analysis-untrusted-trigger" in _finding_codes(
        workflow_governance.scan_workflow_security_contract(
            ".github/workflows/security-analysis.yml",
            security_analysis_pr_upload,
        )
    )
    disallowed_scorecard_codes = _finding_codes(
        workflow_governance.scan_workflow_security_contract(
            ".github/workflows/security-analysis.yml",
            security_analysis_disallowed_scorecard_job,
        )
    )
    assert "security-analysis-scorecard-job-restriction" in disallowed_scorecard_codes
    assert "security-analysis-scorecard-action-unapproved" in disallowed_scorecard_codes
    assert any(
        finding.code == "security-analysis-scorecard-job-restriction"
        and "container" in finding.detail
        for finding in workflow_governance.scan_workflow_security_contract(
            ".github/workflows/security-analysis.yml",
            security_analysis_disallowed_scorecard_job,
        )
    )
    assert "security-analysis-workflow-restriction" in _finding_codes(
        workflow_governance.scan_workflow_security_contract(
            ".github/workflows/security-analysis.yml",
            security_analysis_top_level_inline_env,
        )
    )
    assert "security-analysis-scorecard-runner" in _finding_codes(
        workflow_governance.scan_workflow_security_contract(
            ".github/workflows/security-analysis.yml",
            security_analysis_windows_scorecard,
        )
    )
    assert "security-analysis-required-gate" in _finding_codes(
        workflow_governance.scan_workflow_security_contract(
            ".github/workflows/ci.yml",
            ci_with_required_scorecard,
        )
    )


def test_security_workflow_governance_accepts_release_permission_allowlist() -> None:
    workflow = _source(".github/workflows/release-remote-runner-artifacts.yml")

    findings = workflow_governance.scan_workflow_security_contract(
        ".github/workflows/release-remote-runner-artifacts.yml",
        workflow,
    )

    assert [finding.format() for finding in findings] == []


def test_security_workflow_governance_accepts_dependency_review_pr_gate() -> None:
    workflow = """
name: Dependency Review
"on":
  pull_request:
permissions:
  contents: read
jobs:
  dependency_review:
    name: security / dependency-review
    if: ${{ github.event_name == 'pull_request' }}
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
        with:
          persist-credentials: false
      - uses: actions/dependency-review-action@a1d282b36b6f3519aa1f3fc636f609c47dddb294
        with:
          fail-on-severity: moderate
          comment-summary-in-pr: never
"""

    findings = workflow_governance.scan_workflow_security_contract(
        ".github/workflows/dependency-review.yml",
        workflow,
    )

    assert [finding.format() for finding in findings] == []


def test_security_workflow_governance_accepts_security_analysis_workflow() -> None:
    workflow = _source(".github/workflows/security-analysis.yml")

    findings = workflow_governance.scan_workflow_security_contract(
        ".github/workflows/security-analysis.yml",
        workflow,
    )

    assert [finding.format() for finding in findings] == []


def _finding_codes(findings: list[Finding]) -> set[str]:
    return {finding.code for finding in findings}
