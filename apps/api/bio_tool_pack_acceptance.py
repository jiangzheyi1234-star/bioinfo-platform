"""Reliability acceptance matrix for Bio Tool Pack profiles."""

from __future__ import annotations

from typing import Any

from .bio_tool_pack_manifest import complete_rule_template_semantics
from .tool_profile_model import ToolProfile


def reliability_acceptance_matrix(profiles: tuple[ToolProfile, ...] | None = None) -> dict[str, Any]:
    selected_profiles = profiles if profiles is not None else _default_profiles()
    rows = [_profile_row(profile) for profile in selected_profiles]
    passed = sum(1 for row in rows if row["status"] == "pass")
    return {
        "contractVersion": "reliability-acceptance-matrix-v1",
        "rows": rows,
        "summary": {
            "total": len(rows),
            "passed": passed,
            "failed": len(rows) - passed,
        },
    }


def _profile_row(profile: ToolProfile) -> dict[str, Any]:
    checks = {
        "manifestValid": bool(profile.pack_id and profile.profile_id and profile.tool_names),
        "sourceDeclared": bool(profile.source_refs),
        "licenseDeclared": bool(profile.license),
        "citationsDeclared": bool(profile.citations),
        "packageIdentityLocked": bool(profile.package_source and profile.package_name and profile.package_version),
        "ruleRenderable": _rule_renderable(profile.rule_template),
        "environmentLocked": _environment_locked(profile.rule_template, profile.package_source),
        "smokeFixturePresent": _smoke_fixture_present(profile.rule_template),
        "semanticPortsDeclared": _semantic_ports_declared(profile.rule_template),
        "reportSchemaBound": _report_schema_bound(profile),
    }
    blocker_codes = [_blocker_code(name) for name, ok in checks.items() if not ok]
    return {
        "profileId": profile.profile_id,
        "packId": profile.pack_id,
        "workflowStage": profile.workflow_stage,
        "operation": profile.operation,
        "status": "pass" if not blocker_codes else "fail",
        "checks": checks,
        "blockerCodes": blocker_codes,
    }


def _rule_renderable(template: dict[str, Any]) -> bool:
    action_count = sum(1 for key in ("commandTemplate", "wrapper", "script", "module") if template.get(key))
    return (
        action_count == 1
        and bool(template.get("inputs"))
        and bool(template.get("outputs"))
        and isinstance(template.get("params"), dict)
        and isinstance(template.get("resources"), dict)
        and bool(str(template.get("log") or "").strip())
    )


def _environment_locked(template: dict[str, Any], package_source: str) -> bool:
    conda = ((template.get("environment") or {}).get("conda") or {})
    channels = [str(item).strip() for item in conda.get("channels") or [] if str(item).strip()]
    dependencies = [str(item).strip() for item in conda.get("dependencies") or [] if str(item).strip()]
    source = str(package_source or "").strip()
    if not source or source not in channels or "conda-forge" not in channels:
        return False
    return (
        ("bioconda" not in channels or channels.index("conda-forge") < channels.index("bioconda"))
        and bool(dependencies)
    )


def _smoke_fixture_present(template: dict[str, Any]) -> bool:
    smoke = template.get("smokeTest") if isinstance(template.get("smokeTest"), dict) else {}
    smoke_inputs = smoke.get("inputs") if isinstance(smoke.get("inputs"), dict) else {}
    required_inputs = [
        str(item.get("name") or "").strip()
        for item in template.get("inputs") or []
        if isinstance(item, dict) and item.get("required", True)
    ]
    return bool(smoke_inputs) and all(name in smoke_inputs for name in required_inputs)


def _semantic_ports_declared(template: dict[str, Any]) -> bool:
    complete_template = complete_rule_template_semantics(template)
    ports = [
        item
        for key in ("inputs", "outputs")
        for item in complete_template.get(key) or []
        if isinstance(item, dict)
    ]
    return bool(ports) and all(
        all(str(item.get(key) or "").strip() for key in ("name", "type", "kind", "mimeType", "data", "format"))
        for item in ports
    )


def _report_schema_bound(profile: ToolProfile) -> bool:
    output_names = {
        str(item.get("name") or "").strip()
        for item in profile.rule_template.get("outputs") or []
        if isinstance(item, dict)
    }
    schema_ports = {
        str(item.get("sourcePort") or "").strip()
        for item in profile.report_schemas
        if isinstance(item, dict)
    }
    return bool(schema_ports) and schema_ports.issubset(output_names)


def _blocker_code(name: str) -> str:
    normalized = "".join(f"_{char}" if char.isupper() else char for char in name).upper().lstrip("_")
    return f"BIO_TOOL_PACK_{normalized}_BLOCKED"


def _default_profiles() -> tuple[ToolProfile, ...]:
    from .tool_profile_sources import all_tool_profiles

    return all_tool_profiles()
