"""Bio Tool Pack v1 manifest loading and validation."""

from __future__ import annotations

from copy import deepcopy
from pathlib import PurePosixPath
from typing import Any

from .tool_profile_model import ToolProfile
from .tool_profile_identity import profile_tool_name
from .tool_profile_semantics import enrich_rule_template_semantics


CONTRACT_VERSION = "bio-tool-pack-v1"
EDAM_GENERIC_DATA = "http://edamontology.org/data_0006"
EDAM_BIGWIG = "http://edamontology.org/format_3006"
EDAM_GFF = "http://edamontology.org/format_1975"
EDAM_JSON = "http://edamontology.org/format_3464"
EDAM_TSV = "http://edamontology.org/format_3475"
EDAM_GENERIC_FORMAT = "http://edamontology.org/format_1915"

_TOP_LEVEL_KEYS = {
    "contractVersion",
    "packId",
    "version",
    "name",
    "source",
    "license",
    "citations",
    "sourceRefs",
    "profiles",
}
_PROFILE_KEYS = {
    "profileId",
    "version",
    "toolNames",
    "packageName",
    "packageSource",
    "packageVersion",
    "preferredWrapperPaths",
    "workflowStage",
    "operation",
    "ruleTemplate",
    "reportSchemas",
    "sourceRefs",
}


class BioToolPackManifestError(ValueError):
    """Raised when a Bio Tool Pack manifest cannot be accepted."""


def load_bio_tool_pack_manifest(manifest: dict[str, Any]) -> tuple[ToolProfile, ...]:
    """Validate a Bio Tool Pack manifest and return immutable tool profiles."""

    _validate_keys(manifest, _TOP_LEVEL_KEYS, "BIO_TOOL_PACK_FIELD_UNKNOWN")
    pack_id = _required_text(manifest.get("packId"), "BIO_TOOL_PACK_ID_REQUIRED")
    version = int(_required_text(manifest.get("version"), "BIO_TOOL_PACK_VERSION_REQUIRED"))
    source = _required_text(manifest.get("source"), "BIO_TOOL_PACK_SOURCE_REQUIRED")
    license_name = _required_text(manifest.get("license"), "BIO_TOOL_PACK_LICENSE_REQUIRED")
    citations = _required_strings(manifest.get("citations"), "BIO_TOOL_PACK_CITATIONS_REQUIRED")
    profiles = manifest.get("profiles")
    if manifest.get("contractVersion") != CONTRACT_VERSION:
        raise BioToolPackManifestError("BIO_TOOL_PACK_CONTRACT_VERSION_UNSUPPORTED")
    if not isinstance(profiles, list) or not profiles:
        raise BioToolPackManifestError("BIO_TOOL_PACK_PROFILES_REQUIRED")

    loaded: list[ToolProfile] = []
    seen_profile_ids: set[str] = set()
    for raw_profile in profiles:
        if not isinstance(raw_profile, dict):
            raise BioToolPackManifestError("BIO_TOOL_PACK_PROFILE_INVALID")
        _validate_keys(raw_profile, _PROFILE_KEYS, "BIO_TOOL_PACK_PROFILE_FIELD_UNKNOWN")
        profile_id = _required_text(raw_profile.get("profileId"), "BIO_TOOL_PACK_PROFILE_ID_REQUIRED")
        if profile_id in seen_profile_ids:
            raise BioToolPackManifestError("BIO_TOOL_PACK_PROFILE_DUPLICATE")
        seen_profile_ids.add(profile_id)
        profile_version = int(_required_text(raw_profile.get("version"), "BIO_TOOL_PACK_PROFILE_VERSION_REQUIRED"))
        tool_names = tuple(_required_strings(raw_profile.get("toolNames"), "BIO_TOOL_PACK_TOOL_NAMES_REQUIRED"))
        package_name = _required_text(raw_profile.get("packageName"), "BIO_TOOL_PACK_PROFILE_PACKAGE_NAME_REQUIRED")
        package_source = _required_text(raw_profile.get("packageSource"), "BIO_TOOL_PACK_PROFILE_PACKAGE_SOURCE_REQUIRED")
        package_version = _required_text(raw_profile.get("packageVersion"), "BIO_TOOL_PACK_PROFILE_PACKAGE_VERSION_REQUIRED")
        rule_template = _validated_rule_template(raw_profile.get("ruleTemplate"), package_source=package_source)
        report_schemas = tuple(_validated_report_schemas(raw_profile.get("reportSchemas"), rule_template))
        loaded.append(
            ToolProfile(
                profile_id=profile_id,
                version=profile_version,
                tool_names=tool_names,
                rule_template=rule_template,
                preferred_wrapper_paths=tuple(_strings(raw_profile.get("preferredWrapperPaths"))),
                package_name=package_name,
                package_source=package_source,
                package_version=package_version,
                pack_id=pack_id,
                workflow_stage=str(raw_profile.get("workflowStage") or _infer_workflow_stage(rule_template)).strip(),
                operation=str(raw_profile.get("operation") or _infer_operation(profile_id, rule_template)).strip(),
                license=license_name,
                citations=tuple(citations),
                source_refs=tuple(_source_refs(source, manifest, raw_profile)),
                report_schemas=report_schemas,
            )
        )
    _validate_profile_tool_id_uniqueness(loaded, "BIO_TOOL_PACK_PROFILE_TOOL_ID_DUPLICATE")
    _ = version
    return tuple(loaded)


def load_bio_tool_pack_manifests(manifests: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> tuple[ToolProfile, ...]:
    """Load multiple Bio Tool Packs into one candidate registry slice."""

    loaded: list[ToolProfile] = []
    seen_profile_ids: set[str] = set()
    for manifest in manifests:
        for profile in load_bio_tool_pack_manifest(manifest):
            if profile.profile_id in seen_profile_ids:
                raise BioToolPackManifestError("BIO_TOOL_PACK_MERGED_PROFILE_DUPLICATE")
            seen_profile_ids.add(profile.profile_id)
            loaded.append(profile)
    _validate_profile_tool_id_uniqueness(loaded, "BIO_TOOL_PACK_MERGED_PROFILE_TOOL_ID_DUPLICATE")
    return tuple(loaded)


def bio_tool_pack_manifest_from_profiles(
    profiles: tuple[ToolProfile, ...],
    *,
    pack_id: str,
    version: int,
    name: str,
    source: str,
    license: str,
    citations: tuple[str, ...],
) -> dict[str, Any]:
    """Build a strict manifest around curated in-repo profile definitions."""

    return {
        "contractVersion": CONTRACT_VERSION,
        "packId": pack_id,
        "version": version,
        "name": name,
        "source": source,
        "license": license,
        "citations": list(citations),
        "sourceRefs": [{"type": "repository", "url": source}],
        "profiles": [_manifest_profile(profile) for profile in profiles],
    }


def _manifest_profile(profile: ToolProfile) -> dict[str, Any]:
    rule_template = enrich_rule_template_semantics(profile.rule_template)
    return {
        "profileId": profile.profile_id,
        "version": profile.version,
        "toolNames": list(profile.tool_names),
        "packageName": profile.package_name,
        "packageSource": profile.package_source,
        "packageVersion": profile.package_version,
        "preferredWrapperPaths": list(profile.preferred_wrapper_paths),
        "workflowStage": profile.workflow_stage or _infer_workflow_stage(rule_template),
        "operation": profile.operation or _infer_operation(profile.profile_id, rule_template),
        "ruleTemplate": rule_template,
        "reportSchemas": _artifact_schemas(rule_template),
        "sourceRefs": list(profile.source_refs),
    }


def _validate_profile_tool_id_uniqueness(profiles: list[ToolProfile], code: str) -> None:
    seen: dict[str, str] = {}
    for profile in profiles:
        key = profile_tool_name(profile)
        if not key:
            raise BioToolPackManifestError("BIO_TOOL_PACK_PROFILE_TOOL_ID_REQUIRED")
        existing = seen.get(key)
        if existing is not None and existing != profile.profile_id:
            raise BioToolPackManifestError(f"{code}: {key}")
        seen[key] = profile.profile_id


def _validated_rule_template(value: Any, *, package_source: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BioToolPackManifestError("BIO_TOOL_PACK_RULE_TEMPLATE_REQUIRED")
    template = enrich_rule_template_semantics(deepcopy(value))
    complete_template = complete_rule_template_semantics(template)
    action_count = sum(1 for key in ("commandTemplate", "wrapper", "script", "module") if template.get(key))
    if action_count != 1:
        raise BioToolPackManifestError("BIO_TOOL_PACK_RULE_ACTION_REQUIRED")
    inputs = [item for item in template.get("inputs") or [] if isinstance(item, dict)]
    outputs = [item for item in template.get("outputs") or [] if isinstance(item, dict)]
    if not inputs:
        raise BioToolPackManifestError("BIO_TOOL_PACK_INPUTS_REQUIRED")
    if not outputs:
        raise BioToolPackManifestError("BIO_TOOL_PACK_OUTPUTS_REQUIRED")
    if not isinstance(template.get("params"), dict):
        raise BioToolPackManifestError("BIO_TOOL_PACK_PARAMS_REQUIRED")
    if not isinstance(template.get("resources"), dict):
        raise BioToolPackManifestError("BIO_TOOL_PACK_RESOURCES_REQUIRED")
    if not str(template.get("log") or "").strip():
        raise BioToolPackManifestError("BIO_TOOL_PACK_LOG_REQUIRED")
    _validate_environment(template, package_source=package_source)
    _validate_smoke_fixture(template, inputs)
    complete_ports = [
        item
        for key in ("inputs", "outputs")
        for item in complete_template.get(key) or []
        if isinstance(item, dict)
    ]
    _validate_semantic_ports(complete_ports)
    return template


def complete_rule_template_semantics(rule_template: dict[str, Any]) -> dict[str, Any]:
    complete = enrich_rule_template_semantics(deepcopy(rule_template))
    for key in ("inputs", "outputs"):
        ports = complete.get(key)
        if not isinstance(ports, list):
            continue
        complete[key] = [_complete_port(port) if isinstance(port, dict) else port for port in ports]
    return complete


def _complete_port(port: dict[str, Any]) -> dict[str, Any]:
    complete = dict(port)
    if not str(complete.get("type") or "").strip():
        complete["type"] = "file"
    if not str(complete.get("data") or "").strip():
        complete["data"] = EDAM_GENERIC_DATA
    if not str(complete.get("format") or "").strip():
        complete["format"] = _fallback_format(complete)
    return complete


def _fallback_format(port: dict[str, Any]) -> str:
    suffixes = {suffix.lower() for suffix in PurePosixPath(str(port.get("path") or port.get("filename") or "")).suffixes}
    mime_type = str(port.get("mimeType") or "").strip().lower()
    if ".json" in suffixes or mime_type == "application/json":
        return EDAM_JSON
    if ".tsv" in suffixes or ".tab" in suffixes or mime_type == "text/tab-separated-values":
        return EDAM_TSV
    if {".gff", ".gff3"} & suffixes:
        return EDAM_GFF
    if {".bw", ".bigwig"} & suffixes:
        return EDAM_BIGWIG
    return EDAM_GENERIC_FORMAT


def _validate_environment(template: dict[str, Any], *, package_source: str) -> None:
    conda = ((template.get("environment") or {}).get("conda") or {})
    channels = [str(item).strip() for item in conda.get("channels") or [] if str(item).strip()]
    dependencies = [str(item).strip() for item in conda.get("dependencies") or [] if str(item).strip()]
    source = str(package_source or "").strip()
    if not source or source not in channels:
        raise BioToolPackManifestError("BIO_TOOL_PACK_ENV_PACKAGE_SOURCE_CHANNEL_REQUIRED")
    if "conda-forge" not in channels:
        raise BioToolPackManifestError("BIO_TOOL_PACK_ENV_CHANNELS_REQUIRED")
    if "bioconda" in channels and channels.index("conda-forge") > channels.index("bioconda"):
        raise BioToolPackManifestError("BIO_TOOL_PACK_ENV_CHANNEL_ORDER_REQUIRED")
    if not dependencies:
        raise BioToolPackManifestError("BIO_TOOL_PACK_ENV_DEPENDENCIES_REQUIRED")


def _validate_smoke_fixture(template: dict[str, Any], inputs: list[dict[str, Any]]) -> None:
    smoke = template.get("smokeTest") if isinstance(template.get("smokeTest"), dict) else {}
    smoke_inputs = smoke.get("inputs") if isinstance(smoke.get("inputs"), dict) else {}
    if not smoke_inputs:
        raise BioToolPackManifestError("BIO_TOOL_PACK_SMOKE_FIXTURES_REQUIRED")
    for input_spec in inputs:
        if input_spec.get("required", True) and str(input_spec.get("name") or "") not in smoke_inputs:
            raise BioToolPackManifestError("BIO_TOOL_PACK_SMOKE_INPUT_MISSING")


def _validate_semantic_ports(ports: list[dict[str, Any]]) -> None:
    for port in ports:
        for key in ("name", "type", "kind", "mimeType", "data", "format"):
            if not str(port.get(key) or "").strip():
                raise BioToolPackManifestError(f"BIO_TOOL_PACK_PORT_{key.upper()}_REQUIRED")


def _validated_report_schemas(value: Any, rule_template: dict[str, Any]) -> list[dict[str, Any]]:
    schemas = value if isinstance(value, list) else []
    if not schemas:
        raise BioToolPackManifestError("BIO_TOOL_PACK_REPORT_SCHEMAS_REQUIRED")
    output_names = {
        str(item.get("name") or "").strip()
        for item in rule_template.get("outputs") or []
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    }
    validated: list[dict[str, Any]] = []
    for schema in schemas:
        if not isinstance(schema, dict):
            raise BioToolPackManifestError("BIO_TOOL_PACK_REPORT_SCHEMA_INVALID")
        source_port = _required_text(schema.get("sourcePort"), "BIO_TOOL_PACK_REPORT_SCHEMA_PORT_REQUIRED")
        if source_port not in output_names:
            raise BioToolPackManifestError("BIO_TOOL_PACK_REPORT_SCHEMA_PORT_UNKNOWN")
        validated.append(dict(schema))
    return validated


def _artifact_schemas(rule_template: dict[str, Any]) -> list[dict[str, Any]]:
    schemas: list[dict[str, Any]] = []
    for output in rule_template.get("outputs") or []:
        if not isinstance(output, dict):
            continue
        name = str(output.get("name") or "").strip()
        path = str(output.get("path") or "").strip()
        if not name or not path:
            continue
        schemas.append(
            {
                "key": name,
                "sourcePort": name,
                "kind": str(output.get("kind") or "artifact"),
                "mimeType": str(output.get("mimeType") or "application/octet-stream"),
                "name": PurePosixPath(path).name,
                "assertions": ["exists", "non-empty"],
            }
        )
    return schemas


def _source_refs(source: str, manifest: dict[str, Any], profile: dict[str, Any]) -> list[dict[str, Any]]:
    refs = [item for item in manifest.get("sourceRefs") or [] if isinstance(item, dict)]
    refs.extend(item for item in profile.get("sourceRefs") or [] if isinstance(item, dict))
    if not refs:
        refs.append({"type": "source", "url": source})
    return refs


def _infer_workflow_stage(rule_template: dict[str, Any]) -> str:
    kinds = {str(item.get("kind") or "") for key in ("inputs", "outputs") for item in rule_template.get(key) or [] if isinstance(item, dict)}
    if {"taxonomy_report", "taxonomy_abundance", "taxonomy_classification"} & kinds:
        return "taxonomy"
    if {"sequence_reads", "sequence_stats", "qc_report"} & kinds:
        return "read-qc"
    if {"assembly_contigs"} & kinds:
        return "assembly"
    if {"alignment_sam", "alignment_bam", "coverage_bigwig"} & kinds:
        return "alignment"
    if {"report", "report_archive"} & kinds:
        return "reporting"
    return "analysis"


def _infer_operation(profile_id: str, rule_template: dict[str, Any]) -> str:
    profile = profile_id.lower()
    for token, operation in (
        ("fastqc", "quality-control"),
        ("fastp", "read-preprocessing"),
        ("kraken", "taxonomic-classification"),
        ("bracken", "taxonomic-abundance-estimation"),
        ("multiqc", "quality-reporting"),
        ("assembly", "assembly"),
        ("align", "alignment"),
        ("quant", "quantification"),
    ):
        if token in profile:
            return operation
    return _infer_workflow_stage(rule_template)


def _validate_keys(value: dict[str, Any], allowed: set[str], code: str) -> None:
    extra = sorted(set(value) - allowed)
    if extra:
        raise BioToolPackManifestError(f"{code}: {extra[0]}")


def _required_strings(value: Any, code: str) -> list[str]:
    values = _strings(value)
    if not values:
        raise BioToolPackManifestError(code)
    return values


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    return [text for item in value if (text := str(item or "").strip())]


def _required_text(value: Any, code: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise BioToolPackManifestError(code)
    return text
