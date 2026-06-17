"""Evidence scoring helpers for Bio Agent Tool Catalog acceptance."""

from __future__ import annotations

from typing import Any

from apps.api.tool_profile_external_refs import profile_snakemake_wrappers
from apps.api.tool_profile_model import ToolProfile
from apps.api.tool_profile_semantics import enrich_rule_template_semantics
from apps.api.tool_resource_requirements import (
    required_resource_summary as _required_resource_summary,
)


def validation_evidence(
    *, profile: ToolProfile, prepare_payload: dict[str, Any]
) -> dict[str, Any]:
    wrappers = profile_snakemake_wrappers(profile)
    semantic = _semantic_port_summary(prepare_payload)
    return {
        "snakemakeWrapperCount": len(wrappers),
        "snakemakeWrapperPaths": [
            str(item.get("wrapperPath") or "")
            for item in wrappers
            if str(item.get("wrapperPath") or "")
        ],
        **_wrapper_contract_hint_summary(wrappers),
        **semantic,
        **_required_resource_summary(prepare_payload),
        **_smoke_fixture_quality_summary(prepare_payload),
    }


def catalog_validation_evidence(
    *, item: dict[str, Any], prepare_payload: dict[str, Any]
) -> dict[str, Any]:
    wrapper_paths: list[str] = []
    wrappers = item.get("snakemakeWrappers")
    if isinstance(wrappers, list):
        wrapper_paths.extend(
            str(wrapper.get("wrapperPath") or "").strip()
            for wrapper in wrappers
            if isinstance(wrapper, dict)
            and str(wrapper.get("wrapperPath") or "").strip()
        )
    wrapper_path = str(item.get("wrapperPath") or "").strip()
    if wrapper_path:
        wrapper_paths.append(wrapper_path)
    wrapper_count = _count_value(item.get("snakemakeWrapperCount"))
    if wrapper_count <= 0:
        wrapper_count = len(wrapper_paths)
    return {
        "snakemakeWrapperCount": wrapper_count,
        "snakemakeWrapperPaths": _unique_strings(wrapper_paths),
        "wrapperContractHintCount": _count_value(item.get("wrapperContractHintCount")),
        "wrapperContractHintFields": _string_list(
            item.get("wrapperContractHintFields")
        ),
        "wrapperCondaDependencies": _string_list(item.get("wrapperCondaDependencies")),
        **_semantic_port_summary(prepare_payload),
        **_required_resource_summary(prepare_payload),
        **_smoke_fixture_quality_summary(prepare_payload),
    }


def validation_priority(
    *, evidence: dict[str, Any], prepare_payload: dict[str, Any]
) -> dict[str, Any]:
    score = 0
    reasons: list[str] = []
    if _count_value(evidence.get("snakemakeWrapperCount")) > 0:
        score += 40
        reasons.append("snakemake-wrapper-evidence")
    if evidence.get("semanticPortFields"):
        score += 30
        reasons.append("edam-port-semantics")
    rule_draft = (
        prepare_payload.get("ruleSpecDraft")
        if isinstance(prepare_payload.get("ruleSpecDraft"), dict)
        else {}
    )
    if rule_draft.get("requiresUserCompletion") is False:
        score += 20
        reasons.append("ready-prepare-payload")
    if _semantic_format_count(evidence) >= 2:
        score += 10
        reasons.append("multi-port-format-coverage")
    if evidence.get("requiredResourceKeys"):
        reasons.append("required-resources-pending")
    elif evidence.get("smokeFixtureQuality") == "materialized":
        score += 15
        reasons.append("self-contained-smoke")
    elif evidence.get("smokeFixtureQuality") == "placeholder":
        reasons.append("smoke-fixture-placeholder")
    else:
        reasons.append("smoke-fixture-missing")
    return {"score": score, "reasons": reasons}


def _wrapper_contract_hint_summary(wrappers: list[dict[str, Any]]) -> dict[str, Any]:
    hint_count = 0
    fields: set[str] = set()
    dependencies: set[str] = set()
    for wrapper in wrappers:
        hints = (
            wrapper.get("wrapperContractHints") if isinstance(wrapper, dict) else None
        )
        if not isinstance(hints, dict) or not hints:
            continue
        hint_count += 1
        fields.update(_contract_hint_fields(hints))
        dependencies.update(_contract_hint_conda_dependencies(hints))
    return {
        "wrapperContractHintCount": hint_count,
        "wrapperContractHintFields": sorted(fields),
        "wrapperCondaDependencies": sorted(dependencies),
    }


def _contract_hint_fields(hints: dict[str, Any]) -> set[str]:
    return {
        key
        for key in (
            "name",
            "description",
            "url",
            "authors",
            "input",
            "output",
            "params",
            "notes",
            "environment",
        )
        if hints.get(key)
    }


def _contract_hint_conda_dependencies(hints: dict[str, Any]) -> set[str]:
    environment = (
        hints.get("environment") if isinstance(hints.get("environment"), dict) else {}
    )
    conda = (
        environment.get("conda") if isinstance(environment.get("conda"), dict) else {}
    )
    dependencies = (
        conda.get("dependencies") if isinstance(conda.get("dependencies"), list) else []
    )
    return {
        str(dependency).strip()
        for dependency in dependencies
        if str(dependency or "").strip()
    }


def _semantic_port_summary(prepare_payload: dict[str, Any]) -> dict[str, Any]:
    template = (
        prepare_payload.get("ruleTemplate")
        if isinstance(prepare_payload.get("ruleTemplate"), dict)
        else {}
    )
    enriched = enrich_rule_template_semantics(template)
    fields: set[str] = set()
    data_terms: set[str] = set()
    format_terms: set[str] = set()
    for section in ("inputs", "outputs"):
        for port in enriched.get(section) or []:
            if not isinstance(port, dict):
                continue
            data = str(port.get("data") or port.get("edamData") or "").strip()
            format_id = str(port.get("format") or port.get("edamFormat") or "").strip()
            if data:
                fields.add("data")
                data_terms.add(data)
            if format_id:
                fields.add("format")
                format_terms.add(format_id)
    return {
        "semanticPortFields": sorted(fields),
        "semanticData": sorted(data_terms),
        "semanticFormats": sorted(format_terms),
    }


def _semantic_format_count(evidence: dict[str, Any]) -> int:
    formats = evidence.get("semanticFormats")
    return len(formats) if isinstance(formats, list) else 0


def _smoke_fixture_quality_summary(prepare_payload: dict[str, Any]) -> dict[str, Any]:
    template = (
        prepare_payload.get("ruleTemplate")
        if isinstance(prepare_payload.get("ruleTemplate"), dict)
        else {}
    )
    smoke_test = (
        template.get("smokeTest") if isinstance(template.get("smokeTest"), dict) else {}
    )
    inputs = _smoke_fixture_inputs(smoke_test.get("inputs"))
    if not inputs:
        return {
            "smokeFixtureQuality": "missing",
            "smokeFixtureIssues": ["missing-smoke-inputs"],
        }

    issues: list[str] = []
    materialized_count = 0
    for index, (input_name, raw_input) in enumerate(inputs):
        if not isinstance(raw_input, dict):
            issues.append(f"input-{index}:invalid-smoke-input")
            continue
        content = str(raw_input.get("content") or "")
        filename = str(
            raw_input.get("filename")
            or raw_input.get("name")
            or input_name
            or f"input-{index}"
        ).strip()
        mime_type = (
            str(raw_input.get("mimeType") or raw_input.get("mime") or "")
            .strip()
            .lower()
        )
        if _looks_like_placeholder_fixture(
            content=content, filename=filename, mime_type=mime_type
        ):
            issues.append(f"{filename}:placeholder-content")
            continue
        if content:
            materialized_count += 1

    if issues:
        return {"smokeFixtureQuality": "placeholder", "smokeFixtureIssues": issues}
    if materialized_count == 0:
        return {
            "smokeFixtureQuality": "missing",
            "smokeFixtureIssues": ["missing-smoke-input-content"],
        }
    return {"smokeFixtureQuality": "materialized", "smokeFixtureIssues": []}


def _smoke_fixture_inputs(value: Any) -> list[tuple[str, Any]]:
    if isinstance(value, dict):
        return [(str(key or "").strip(), item) for key, item in value.items()]
    if isinstance(value, list):
        return [("", item) for item in value]
    return []


def _looks_like_placeholder_fixture(
    *, content: str, filename: str, mime_type: str
) -> bool:
    searchable = f"{filename}\n{mime_type}\n{content}".lower()
    return "placeholder" in searchable


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return _unique_strings(
        str(item).strip() for item in value if str(item or "").strip()
    )


def _unique_strings(values: Any) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        unique.append(text)
    return unique


def _count_value(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0
