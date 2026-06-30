"""Markdown downloads for First Successful Run evidence."""

from __future__ import annotations

from typing import Any


def first_run_validation_card_markdown(card: dict[str, Any]) -> str:
    checks = _items(card.get("checks"))
    passed_checks = sum(1 for item in checks if item.get("status") == "passed")
    software = _mapping(card.get("softwareEnvironment"))
    runtime = _mapping(software.get("runtime"))
    workflow = _mapping(card.get("workflowRevision"))
    package = _mapping(card.get("resultPackage"))
    sample_data = _mapping(card.get("sampleData"))
    report = _mapping(card.get("reportInterpretation"))
    sample_items = _items(sample_data.get("items"))
    key_results = _items(card.get("keyResults"))
    metrics = _items(report.get("metrics"))
    return "\n".join(
        [
            "# H2OMeta First Successful Run Validation Card",
            "",
            f"Generated: {_value(card.get('generatedAt'))}",
            f"Scenario: {_value(_scenario_label(card))}",
            f"Dataset: {_value(_mapping(card.get('scenario')).get('dataset') or 'QIIME 2 Moving Pictures tutorial')}",
            f"Run: {_value(_mapping(card.get('run')).get('runId'))} ({_value(_mapping(card.get('run')).get('status'))})",
            f"WorkflowRevision: {_value(workflow.get('workflowRevisionId') or software.get('workflowRevisionId'))}",
            f"Software: {_value(_runtime_label(runtime))}",
            f"Result package: {_value(package.get('packageExportId'))}",
            f"Package SHA-256: {_value(package.get('sha256'))}",
            f"Manifest SHA-256: {_value(package.get('manifestSha256'))}",
            f"Checks: {passed_checks}/{len(checks)} passed",
            "",
            "## Customer Proof",
            "",
            *_customer_proof(card),
            "",
            "## Summary",
            "",
            _value(report.get("summary")),
            "",
            "## Official Sample Inputs",
            "",
            _table(
                ["Role", "Filename", "Status", "Cache", "Download", "SHA-256"],
                [
                    [
                        item.get("role"),
                        item.get("filename"),
                        item.get("integrityStatus"),
                        _mapping(item.get("prepProof")).get("cacheStatus"),
                        _mapping(item.get("prepProof")).get("downloadStatus"),
                        item.get("sha256"),
                    ]
                    for item in sample_items
                ],
                empty="No sample input evidence recorded.",
            ),
            "",
            "## Key Results",
            "",
            _table(
                ["Result", "Kind", "Size", "SHA-256"],
                [
                    [
                        item.get("displayName") or item.get("artifactKey") or item.get("artifactId"),
                        item.get("kind"),
                        item.get("sizeBytes"),
                        item.get("sha256"),
                    ]
                    for item in key_results
                ],
                empty="No key results recorded.",
            ),
            "",
            "## Metrics",
            "",
            _table(
                ["Metric", "Value", "Source"],
                [[item.get("label") or item.get("metricId"), item.get("displayValue") or item.get("value"), item.get("source")] for item in metrics],
                empty="No report metrics recorded.",
            ),
            "",
            "## Validation Checks",
            "",
            _table(
                ["Code", "Status", "Detail"],
                [[item.get("code"), item.get("status"), item.get("detail")] for item in checks],
                empty="No validation checks recorded.",
            ),
            "",
            "## Pilot Handoff",
            "",
            _pilot_handoff_section(_mapping(card.get("pilotHandoff"))),
            "",
            "## Redaction",
            "",
            f"Policy: {_value(_mapping(report.get('redaction')).get('policy') or 'metrics-only')}",
            f"Raw paths exposed: {_yes_no(_mapping(report.get('redaction')).get('rawPathsExposed') is True)}",
            f"Storage URIs exposed: {_yes_no(_mapping(report.get('redaction')).get('storageUrisExposed') is True)}",
        ]
    )


def first_run_handoff_manifest_markdown(card: dict[str, Any]) -> str:
    checks = _items(card.get("checks"))
    passed_checks = sum(1 for item in checks if item.get("status") == "passed")
    package = _mapping(card.get("resultPackage"))
    handoff = _mapping(card.get("pilotHandoff"))
    bundle = _mapping(handoff.get("evidenceBundle"))
    evidence = _mapping(handoff.get("evidence"))
    backup = _mapping(handoff.get("backupRestore"))
    scenarios = _items(handoff.get("nextScenarios"))
    return "\n".join(
        [
            "# H2OMeta First Successful Run Pilot Handoff",
            "",
            f"Run: {_value(evidence.get('runId') or _mapping(card.get('run')).get('runId'))}",
            f"Result: {_value(evidence.get('resultId') or _mapping(card.get('result')).get('resultId'))}",
            f"WorkflowRevision: {_value(evidence.get('workflowRevisionId') or _mapping(card.get('workflowRevision')).get('workflowRevisionId'))}",
            f"Result package: {_value(evidence.get('packageExportId') or package.get('packageExportId'))}",
            f"Package SHA-256: {_value(evidence.get('packageSha256') or package.get('sha256'))}",
            f"Manifest SHA-256: {_value(evidence.get('manifestSha256') or package.get('manifestSha256'))}",
            f"Validation checks: {evidence.get('validationChecksPassed') or passed_checks}/{evidence.get('validationChecksTotal') or len(checks)} passed",
            "",
            "## Pilot Scope",
            "",
            f"Scope: {_value(handoff.get('scope'))}",
            f"Status: {_value(handoff.get('status'))}",
            f"Next action: {_value(_mapping(handoff.get('nextAction')).get('label') or _mapping(handoff.get('nextAction')).get('code'))}",
            f"Next action target: {_value(_mapping(handoff.get('nextAction')).get('target'))}",
            f"Exclusions: {_value(', '.join(str(item) for item in handoff.get('exclusions') or []))}",
            "",
            "## Evidence Bundle",
            "",
            f"Bundle: {_value(bundle.get('bundleId'))}",
            f"Status: {_value(bundle.get('status'))}",
            f"Purpose: {_value(bundle.get('purpose'))}",
            _table(
                ["Role", "Filename", "Source", "Href", "SHA-256", "Manifest SHA-256"],
                [
                    [
                        item.get("role"),
                        item.get("filename"),
                        item.get("source"),
                        item.get("href"),
                        item.get("sha256"),
                        item.get("manifestSha256"),
                    ]
                    for item in _items(bundle.get("requiredFiles"))
                ],
                empty="No evidence bundle files recorded.",
            ),
            "",
            "## Backup And Restore",
            "",
            f"Plan command: {_value(backup.get('planCommand'))}",
            f"Restore proof: {_value(backup.get('restoreProofCommand'))}",
            f"Runbook: {_value(backup.get('runbookPath'))}",
            f"Manual secret rebind required: {_yes_no(backup.get('requiresManualSecretRebind') is True)}",
            f"Automatic backup: {'not supported' if backup.get('noAutomaticBackup') is True else 'not recorded'}",
            f"Unsupported actions: {_value(', '.join(str(item) for item in backup.get('excludedActions') or []))}",
            "",
            "## Next Scenario Pilots",
            "",
            _table(
                ["Scenario", "Status", "Blocked checks", "DB packs", "Ready scan", "Registration prefill", "Missing DB pack templates"],
                [
                    [
                        item.get("name") or item.get("scenarioId"),
                        item.get("status"),
                        len(item.get("blockedChecks") or []),
                        _mapping(item.get("databasePackCoverage")).get("packCount"),
                        _mapping(_mapping(item.get("databaseInstallHandoff")).get("readyScan")).get("path"),
                        _mapping(_mapping(item.get("databaseInstallHandoff")).get("registration")).get("prefillSource"),
                        ", ".join(str(value) for value in _mapping(item.get("databasePackCoverage")).get("missingTemplates") or []),
                    ]
                    for item in scenarios
                ],
                empty="No next scenario pilots recorded.",
            ),
            "",
            "Tool promotion evidence: toolRevisionId, capability-bundle-v1, RuleSpec, environment-lock, smoke-fixture, expected-output-artifacts.",
            "",
            "## Validation Card",
            "",
            "Keep every required evidence bundle file together. Verify the result package SHA-256 and manifest SHA-256 before sharing or reusing lineage.",
        ]
    )


def _customer_proof(card: dict[str, Any]) -> list[str]:
    software = _mapping(card.get("softwareEnvironment"))
    package = _mapping(card.get("resultPackage"))
    sample_data = _mapping(card.get("sampleData"))
    report = _mapping(card.get("reportInterpretation"))
    full_package = package.get("artifactPayloadMode") == "full" or package.get("includeArtifacts") is True
    return [
        f"- Official inputs: {_value('verified' if sample_data.get('status') == 'verified' else 'waiting for checksum evidence')}",
        f"- Software environment: {_value(_runtime_label(_mapping(software.get('runtime'))) if software.get('status') == 'verified' else 'waiting for environment evidence')}",
        "- Database: no external reference database is required for this Moving Pictures first run",
        f"- Key results: {_value('interpreted' if report.get('status') == 'ready' else 'waiting for report interpretation')}",
        f"- Result package: {_value('full package with SHA-256 ' + str(package.get('sha256')) if full_package and package.get('sha256') and package.get('manifestSha256') else 'waiting for full package hash')}",
        f"- Evidence bundle: {_value('ready' if _mapping(_mapping(card.get('pilotHandoff')).get('evidenceBundle')).get('status') == 'ready' else 'waiting for evidence bundle manifest')}",
    ]


def _pilot_handoff_section(handoff: dict[str, Any]) -> str:
    bundle = _mapping(handoff.get("evidenceBundle"))
    backup = _mapping(handoff.get("backupRestore"))
    scenarios = _items(handoff.get("nextScenarios"))
    return "\n".join(
        [
            f"Scope: {_value(handoff.get('scope'))}",
            f"Status: {_value(handoff.get('status'))}",
            f"Evidence bundle: {_value(bundle.get('bundleId'))} ({len(bundle.get('requiredFiles') or [])} files)",
            f"Backup plan: {_value(backup.get('planCommand'))}",
            f"Restore proof: {_value(backup.get('restoreProofCommand'))}",
            "",
            _table(
                ["Scenario", "Status", "Blocked checks", "DB packs", "Ready scan", "Registration prefill", "Missing DB pack templates"],
                [
                    [
                        item.get("name") or item.get("scenarioId"),
                        item.get("status"),
                        len(item.get("blockedChecks") or []),
                        _mapping(item.get("databasePackCoverage")).get("packCount"),
                        _mapping(_mapping(item.get("databaseInstallHandoff")).get("readyScan")).get("path"),
                        _mapping(_mapping(item.get("databaseInstallHandoff")).get("registration")).get("prefillSource"),
                        ", ".join(str(value) for value in _mapping(item.get("databasePackCoverage")).get("missingTemplates") or []),
                    ]
                    for item in scenarios
                ],
                empty="No next scenario handoff recorded.",
            ),
            "",
            "Tool promotion evidence: toolRevisionId, capability-bundle-v1, RuleSpec, environment-lock, smoke-fixture, expected-output-artifacts.",
        ]
    )


def _scenario_label(card: dict[str, Any]) -> str:
    scenario = _mapping(card.get("scenario"))
    return str(scenario.get("pipelineName") or scenario.get("scenarioId") or "Moving Pictures 16S")


def _runtime_label(runtime: dict[str, Any]) -> str:
    return " / ".join(str(item) for item in (runtime.get("engine"), runtime.get("platform"), runtime.get("pipelineVersion")) if item)


def _table(headers: list[str], rows: list[list[Any]], *, empty: str) -> str:
    if not rows:
        return empty
    return "\n".join(
        [
            "| " + " | ".join(_cell(item) for item in headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
            *("| " + " | ".join(_cell(item) for item in row) + " |" for row in rows),
        ]
    )


def _cell(value: Any) -> str:
    return _value(value).replace("|", "\\|").replace("\n", " ")


def _value(value: Any) -> str:
    text = str(value or "").strip()
    return text or "-"


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _items(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []
