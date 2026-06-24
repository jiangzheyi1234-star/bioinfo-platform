from __future__ import annotations

import re
from dataclasses import dataclass


SECURITY_ANALYSIS_WORKFLOW = ".github/workflows/security-analysis.yml"
CODEQL_ACTION_SHA = "8aad20d150bbac5944a9f9d289da16a4b0d87c1e"
SCORECARD_ACTION_SHA = "4eaacf0543bb3f2c246792bd56e8cdeffafb205a"
USES_LINE_RE = re.compile(r"^\s*(?:-\s*)?uses:\s+([^\s#]+)", re.MULTILINE)


@dataclass(frozen=True)
class SecurityAnalysisFinding:
    code: str
    path: str
    line: int
    detail: str


def scan_security_analysis_workflow_contract(
    relative: str,
    source: str,
) -> list[SecurityAnalysisFinding]:
    if relative != SECURITY_ANALYSIS_WORKFLOW:
        return []

    findings: list[SecurityAnalysisFinding] = []
    required_snippets = (
        ('push:\n    branches:\n      - main', "security-analysis-trigger"),
        ("schedule:", "security-analysis-trigger"),
        ("workflow_dispatch:", "security-analysis-trigger"),
        (f"github/codeql-action/init@{CODEQL_ACTION_SHA}", "security-analysis-codeql-action"),
        (f"github/codeql-action/analyze@{CODEQL_ACTION_SHA}", "security-analysis-codeql-action"),
        (
            f"github/codeql-action/upload-sarif@{CODEQL_ACTION_SHA}",
            "security-analysis-scorecard-contract",
        ),
        (f"ossf/scorecard-action@{SCORECARD_ACTION_SHA}", "security-analysis-scorecard-action"),
        ("queries: +security-extended,security-and-quality", "security-analysis-codeql-contract"),
        ("- python", "security-analysis-codeql-contract"),
        ("- javascript-typescript", "security-analysis-codeql-contract"),
        ("results_file: results.sarif", "security-analysis-scorecard-contract"),
        ("results_format: sarif", "security-analysis-scorecard-contract"),
        ("publish_results: true", "security-analysis-scorecard-contract"),
        ("sarif_file: results.sarif", "security-analysis-scorecard-contract"),
    )
    for snippet, code in required_snippets:
        if snippet not in source:
            findings.append(
                SecurityAnalysisFinding(code, relative, 0, f"missing required snippet {snippet!r}")
            )

    if "pull_request:" in source or "merge_group:" in source:
        findings.append(
            SecurityAnalysisFinding(
                "security-analysis-untrusted-trigger",
                relative,
                0,
                "CodeQL/Scorecard uploads must stay out of pull_request and merge_group events",
            )
        )
    if re.search(r"^env:\s*(?:.*?)(?:#.*)?$", source, re.MULTILINE) or re.search(
        r"^defaults:\s*(?:.*?)(?:#.*)?$",
        source,
        re.MULTILINE,
    ):
        findings.append(
            SecurityAnalysisFinding(
                "security-analysis-workflow-restriction",
                relative,
                0,
                "Scorecard publish workflow must not use top-level env or defaults",
            )
        )
    if re.search(r"^\s+continue-on-error:\s*true\s*(?:#.*)?$", source, re.MULTILINE):
        findings.append(
            SecurityAnalysisFinding(
                "security-analysis-soft-fail",
                relative,
                0,
                "security analysis jobs must fail visibly instead of using continue-on-error",
            )
        )
    if source.count("id-token: write") != 1:
        findings.append(
            SecurityAnalysisFinding(
                "security-analysis-scorecard-permissions",
                relative,
                0,
                "only the Scorecard publishing job may request id-token: write",
            )
        )
    findings.extend(_scan_scorecard_publish_job_restrictions(relative, source))
    return findings


def scan_required_ci_security_analysis_contract(
    relative: str,
    source: str,
) -> list[SecurityAnalysisFinding]:
    if relative != ".github/workflows/ci.yml":
        return []
    findings: list[SecurityAnalysisFinding] = []
    if "github/codeql-action/" in source or "ossf/scorecard-action@" in source:
        findings.append(
            SecurityAnalysisFinding(
                "security-analysis-required-gate",
                relative,
                0,
                "CodeQL and Scorecard must stay in the independent Security Analysis workflow",
            )
        )
    optional_job_ref = r"(codeql|scorecard|security[_-]analysis)"
    if (
        re.search(rf"^\s+-\s*{optional_job_ref}\s*(?:#.*)?$", source, re.MULTILINE)
        or re.search(rf"^\s*needs:\s*{optional_job_ref}\s*(?:#.*)?$", source, re.MULTILINE)
        or re.search(
            rf"^\s*needs:\s*\[[^\]\n]*{optional_job_ref}[^\]\n]*\]\s*(?:#.*)?$",
            source,
            re.MULTILINE,
        )
    ):
        findings.append(
            SecurityAnalysisFinding(
                "security-analysis-required-gate",
                relative,
                0,
                "required / ci-green must not list optional CodeQL or Scorecard jobs",
            )
        )
    return findings


def _scan_scorecard_publish_job_restrictions(
    relative: str,
    source: str,
) -> list[SecurityAnalysisFinding]:
    lines = source.splitlines()
    block = _workflow_job_block(lines, "scorecard")
    if block is None:
        return [
            SecurityAnalysisFinding(
                "security-analysis-scorecard-contract",
                relative,
                0,
                "Security Analysis workflow must define a scorecard job",
            )
        ]

    findings: list[SecurityAnalysisFinding] = []
    start, end = block
    if "    runs-on: ubuntu-24.04" not in lines[start:end]:
        findings.append(
            SecurityAnalysisFinding(
                "security-analysis-scorecard-runner",
                relative,
                start + 1,
                "Scorecard publishing job must run on ubuntu-24.04",
            )
        )
    disallowed_job_keys = ("env", "defaults", "container", "services")
    for index in range(start + 1, end):
        line = lines[index]
        for key in disallowed_job_keys:
            if re.match(rf"^    {re.escape(key)}:\s*(?:.*?)(?:#.*)?$", line):
                findings.append(
                    SecurityAnalysisFinding(
                        "security-analysis-scorecard-job-restriction",
                        relative,
                        index + 1,
                        f"Scorecard publishing job must not declare job-level {key}",
                    )
                )
        if re.match(r"^\s+-\s*run:\s+", line) or re.match(r"^\s+run:\s+", line):
            findings.append(
                SecurityAnalysisFinding(
                    "security-analysis-scorecard-action-unapproved",
                    relative,
                    index + 1,
                    "Scorecard publishing job steps must use approved actions, not run scripts",
                )
            )

    allowed_actions = {
        "actions/checkout",
        "actions/upload-artifact",
        "github/codeql-action/upload-sarif",
        "ossf/scorecard-action",
        "step-security/harden-runner",
    }
    job_source = "\n".join(lines[start:end])
    for match in USES_LINE_RE.finditer(job_source):
        action_ref = match.group(1).strip().strip("'\"")
        action_name = action_ref.split("@", 1)[0]
        if action_name not in allowed_actions:
            findings.append(
                SecurityAnalysisFinding(
                    "security-analysis-scorecard-action-unapproved",
                    relative,
                    start + _line_number(job_source, match.start()),
                    f"Scorecard publishing job action {action_name} is not allowlisted",
                )
            )
    return findings


def _workflow_job_block(lines: list[str], job_id: str) -> tuple[int, int] | None:
    in_jobs = False
    start: int | None = None
    job_re = re.compile(rf"^  {re.escape(job_id)}:\s*(?:#.*)?$")
    next_job_re = re.compile(r"^  [A-Za-z0-9_-]+:\s*(?:#.*)?$")
    for index, line in enumerate(lines):
        if re.match(r"^jobs:\s*(?:#.*)?$", line):
            in_jobs = True
            continue
        if not in_jobs:
            continue
        if line.strip() and not line.startswith(" "):
            break
        if start is None:
            if job_re.match(line):
                start = index
            continue
        if index > start and next_job_re.match(line):
            return start, index
    if start is None:
        return None
    return start, len(lines)


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1
