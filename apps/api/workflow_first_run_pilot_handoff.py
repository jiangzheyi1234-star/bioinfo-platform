"""Single-user pilot handoff payload for the First Successful Run."""

from __future__ import annotations

from typing import Any

from apps.api.workflow_scenario_pack_service import list_workflow_scenario_packs


FIRST_RUN_PILOT_HANDOFF_SCHEMA_VERSION = "h2ometa.first-run.single-user-lab-pilot-handoff.v1"
FIRST_RUN_BACKUP_RESTORE_HANDOFF_SCHEMA_VERSION = "h2ometa.first-run.backup-restore-handoff.v1"
FIRST_RUN_EVIDENCE_BUNDLE_SCHEMA_VERSION = "h2ometa.first-run.evidence-bundle.v1"
FIRST_RUN_NEXT_SCENARIO_DATABASE_INSTALL_HANDOFF_SCHEMA_VERSION = (
    "h2ometa.first-run.next-scenario-database-install-handoff.v1"
)


def build_first_run_pilot_handoff(card: dict[str, Any]) -> dict[str, Any]:
    checks = card.get("checks") if isinstance(card.get("checks"), list) else []
    package = card.get("resultPackage") if isinstance(card.get("resultPackage"), dict) else {}
    run = card.get("run") if isinstance(card.get("run"), dict) else {}
    result = card.get("result") if isinstance(card.get("result"), dict) else {}
    workflow_revision = card.get("workflowRevision") if isinstance(card.get("workflowRevision"), dict) else {}
    passed_checks = sum(1 for item in checks if isinstance(item, dict) and item.get("status") == "passed")
    evidence = {
        "runId": run.get("runId"),
        "resultId": result.get("resultId"),
        "workflowRevisionId": workflow_revision.get("workflowRevisionId"),
        "packageExportId": package.get("packageExportId"),
        "packageSha256": package.get("sha256"),
        "manifestSha256": package.get("manifestSha256"),
        "validationChecksPassed": passed_checks,
        "validationChecksTotal": len(checks),
    }
    return {
        "schemaVersion": FIRST_RUN_PILOT_HANDOFF_SCHEMA_VERSION,
        "scope": "single-user-lab",
        "status": "ready",
        "evidence": evidence,
        "evidenceBundle": _evidence_bundle(card, evidence=evidence, package=package),
        "backupRestore": _backup_restore_handoff(),
        "nextScenarios": _next_scenario_handoffs(),
        "nextAction": {
            "code": "RUN_OWN_SMALL_SAMPLE",
            "label": "用自己的小样本跑一次",
            "target": "/workflows",
        },
        "exclusions": ["public-multi-user", "rbac", "kubernetes", "automatic-database-install"],
    }


def _evidence_bundle(
    card: dict[str, Any],
    *,
    evidence: dict[str, Any],
    package: dict[str, Any],
) -> dict[str, Any]:
    run_id = str(evidence.get("runId") or "").strip()
    result_id = str(evidence.get("resultId") or "").strip()
    base_name = result_id or run_id
    report = card.get("reportInterpretation") if isinstance(card.get("reportInterpretation"), dict) else {}
    redaction = report.get("redaction") if isinstance(report.get("redaction"), dict) else {}
    return {
        "schemaVersion": FIRST_RUN_EVIDENCE_BUNDLE_SCHEMA_VERSION,
        "status": "ready",
        "bundleId": f"{base_name}.first-run-evidence",
        "purpose": "portable-first-successful-run-proof",
        "requiredFiles": [
            {
                "role": "result-package",
                "filename": _package_filename(package, base_name),
                "source": "result-package-export-download",
                "packageExportId": evidence.get("packageExportId"),
                "sha256": evidence.get("packageSha256"),
                "manifestSha256": evidence.get("manifestSha256"),
                "artifactPayloadMode": package.get("artifactPayloadMode"),
                "includeArtifacts": package.get("includeArtifacts"),
            },
            {
                "role": "validation-card-json",
                "filename": f"{base_name}.validation-card.json",
                "source": "first-run-validation-card-api",
                "schemaVersion": "h2ometa.first-run.validation-card.v1",
            },
            {
                "role": "validation-card-markdown",
                "filename": f"{base_name}.validation-card.md",
                "source": "first-run-validation-card-markdown",
                "schemaVersion": "h2ometa.first-run.validation-card.v1",
            },
            {
                "role": "pilot-handoff",
                "filename": f"{base_name}.pilot-handoff.md",
                "source": "first-run-pilot-handoff-markdown",
                "schemaVersion": FIRST_RUN_PILOT_HANDOFF_SCHEMA_VERSION,
            },
        ],
        "integrity": evidence,
        "redaction": {
            "rawPathsExposed": redaction.get("rawPathsExposed") is True,
            "storageUrisExposed": redaction.get("storageUrisExposed") is True,
            "previewRowsEmbedded": redaction.get("previewRowsEmbedded") is True,
            "policy": str(redaction.get("policy") or "metrics-only"),
        },
        "standards": {
            "workflowRunCrate": "https://www.researchobject.org/workflow-run-crate/",
            "w3cProv": "https://www.w3.org/TR/prov-o/",
        },
        "consumerChecklist": [
            "keep-result-package-validation-card-and-handoff-together",
            "verify-package-sha256-before-sharing",
            "verify-manifest-sha256-before-reusing-lineage",
        ],
    }


def _package_filename(package: dict[str, Any], base_name: str) -> str:
    download = package.get("download") if isinstance(package.get("download"), dict) else {}
    filename = str(download.get("filename") or "").strip()
    if filename:
        return filename
    return f"{base_name}.zip"


def _backup_restore_handoff() -> dict[str, Any]:
    return {
        "schemaVersion": FIRST_RUN_BACKUP_RESTORE_HANDOFF_SCHEMA_VERSION,
        "mode": "read-only-plan",
        "planCommand": (
            "scripts\\single_user_pilot_backup_plan.ps1 "
            "-RemoteRunnerSharedRoot \"<remote-shared-root>\" -RequireExistingState"
        ),
        "restoreProofCommand": "scripts\\first_run_pilot_check.ps1 -RunFirstSuccessfulRun -RequireFinalizationReady",
        "runbookPath": "docs/single-user-pilot-backup-restore.md",
        "requiresIsolatedRestore": True,
        "requiresManualSecretRebind": True,
        "noAutomaticBackup": True,
        "excludedActions": ["hot-sqlite-copy", "secret-archive", "cache-as-durable-state"],
    }


def _next_scenario_handoffs() -> list[dict[str, Any]]:
    packs = list_workflow_scenario_packs()["data"]["items"]
    handoffs = []
    for pack in packs:
        if str(pack.get("scenarioId") or "") == "moving-pictures-16s":
            continue
        handoffs.append(_next_scenario_handoff(pack))
    return handoffs


def _next_scenario_handoff(pack: dict[str, Any]) -> dict[str, Any]:
    database_handoff = pack.get("databaseHandoff") if isinstance(pack.get("databaseHandoff"), dict) else {}
    return {
        "scenarioId": str(pack.get("scenarioId") or ""),
        "name": str(pack.get("name") or ""),
        "status": str(pack.get("status") or ""),
        "target": "/workflows",
        "blockedChecks": [
            {
                "code": str(item.get("code") or ""),
                "requirement": str(item.get("requirement") or ""),
                "target": _action_target(pack, str(item.get("code") or "")),
            }
            for item in pack.get("readinessChecks") or []
            if isinstance(item, dict) and item.get("status") != "passed"
        ][:3],
        "databasePackCoverage": {
            "packCount": len(database_handoff.get("packOptions") or []),
            "missingTemplates": list(database_handoff.get("missingPackTemplates") or []),
        },
        "databaseInstallHandoff": _next_scenario_database_install_handoff(database_handoff),
    }


def _next_scenario_database_install_handoff(database_handoff: dict[str, Any]) -> dict[str, Any]:
    ready_scan = database_handoff.get("readyScan") if isinstance(database_handoff.get("readyScan"), dict) else {}
    registration = database_handoff.get("registration") if isinstance(database_handoff.get("registration"), dict) else {}
    return {
        "schemaVersion": FIRST_RUN_NEXT_SCENARIO_DATABASE_INSTALL_HANDOFF_SCHEMA_VERSION,
        "mode": str(database_handoff.get("mode") or ""),
        "status": str(database_handoff.get("status") or ""),
        "noAutomaticExecution": database_handoff.get("noAutomaticExecution") is True,
        "readyScan": {
            "schemaVersion": str(ready_scan.get("schemaVersion") or ""),
            "method": str(ready_scan.get("method") or ""),
            "path": str(ready_scan.get("path") or ""),
            "requestFields": list(ready_scan.get("requestFields") or []),
            "acceptedStatus": str(ready_scan.get("acceptedStatus") or ""),
            "mutatesRegistry": ready_scan.get("mutatesRegistry") is True,
            "requiresOperatorReadyPath": ready_scan.get("requiresOperatorReadyPath") is True,
            "auditAction": str(ready_scan.get("auditAction") or ""),
        },
        "registration": {
            "method": str(registration.get("method") or ""),
            "path": str(registration.get("path") or ""),
            "requiresReadyScan": registration.get("requiresReadyScan") is True,
            "prefillSource": str(registration.get("prefillSource") or ""),
            "prefillFields": list(registration.get("prefillFields") or []),
            "acceptedStatus": str(registration.get("acceptedStatus") or ""),
        },
        "checklist": _database_install_checklist(database_handoff),
        "packOptions": _database_install_pack_options(database_handoff),
        "evidencePolicy": dict(database_handoff.get("evidencePolicy") or {}),
        "excludedActions": list(database_handoff.get("excludedActions") or []),
    }


def _database_install_checklist(database_handoff: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "code": str(item.get("code") or ""),
            "label": str(item.get("label") or ""),
            "status": str(item.get("status") or ""),
            "target": str(item.get("target") or ""),
            "evidence": str(item.get("evidence") or ""),
        }
        for item in database_handoff.get("checklist") or []
        if isinstance(item, dict)
    ]


def _database_install_pack_options(database_handoff: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "packId": str(item.get("packId") or ""),
            "templateId": str(item.get("templateId") or ""),
            "checksum": str(item.get("checksum") or ""),
            "sourceUrl": str(item.get("sourceUrl") or ""),
            "readyDirHint": str(item.get("readyDirHint") or ""),
            "registrationScriptPath": str(item.get("registrationScriptPath") or ""),
            "installedLayer": str(item.get("installedLayer") or ""),
        }
        for item in database_handoff.get("packOptions") or []
        if isinstance(item, dict)
    ]


def _action_target(pack: dict[str, Any], code: str) -> str:
    for action in pack.get("nextActions") or []:
        if isinstance(action, dict) and action.get("code") == code:
            return str(action.get("target") or "")
    return ""
