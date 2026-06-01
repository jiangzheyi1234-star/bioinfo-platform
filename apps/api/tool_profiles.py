"""H2OMeta tool profile overlays for discovered conda tools."""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any


PROFILE_CONTRACT_SOURCE = "h2ometa-tool-profile-registry"
PROFILE_WRAPPER_REPOSITORY = "snakemake/snakemake-wrappers"


@dataclass(frozen=True)
class ToolProfile:
    profile_id: str
    version: int
    tool_names: tuple[str, ...]
    rule_template: dict[str, Any]
    preferred_wrapper_paths: tuple[str, ...] = ()


def resolve_tool_profile(tool: dict[str, Any], *, wrappers: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    profile = _profile_for_tool(tool.get("name"))
    if profile is None:
        return None

    package_spec = _clean(tool.get("packageSpec")) or _package_spec_from_identity(tool)
    matched_wrapper = _matched_wrapper(profile, wrappers or [])
    lock: dict[str, Any] = {
        "type": "h2ometa-tool-profile",
        "profileId": profile.profile_id,
        "profileVersion": profile.version,
        "packageSpec": package_spec,
        "version": _package_version(package_spec) or _clean(tool.get("latestVersion") or tool.get("version")),
        "source": _clean(tool.get("source")) or "bioconda",
    }
    profile_wrapper = _profile_wrapper_lock(profile)
    if profile_wrapper:
        lock.update(profile_wrapper)
    if matched_wrapper:
        lock["matchedWrapper"] = {
            "wrapperRepository": _clean(matched_wrapper.get("wrapperRepository")),
            "wrapperRef": _clean(matched_wrapper.get("wrapperRef")),
            "wrapperPath": _clean(matched_wrapper.get("wrapperPath")),
            "wrapperIdentifier": _clean(matched_wrapper.get("wrapperIdentifier")),
        }

    notes = [
        "H2OMeta profile supplied inputs, outputs, params, runtime, environment, resources, and smoke fixtures.",
        "Database requirements are declared through RuleSpec.resources and resolved through workflow resourceBindings.",
    ]
    if matched_wrapper:
        notes.append("A matching Snakemake wrapper was found and recorded for provenance.")

    return {
        "source": "h2ometa-tool-profile",
        "contractSource": PROFILE_CONTRACT_SOURCE,
        "status": "ready-for-validation",
        "requiresUserCompletion": False,
        "lock": lock,
        "ruleTemplate": _profile_rule_template(profile, package_spec),
        "notes": notes,
    }


def known_tool_profile_ids() -> list[str]:
    return sorted(profile.profile_id for profile in TOOL_PROFILES)


def _profile_rule_template(profile: ToolProfile, package_spec: str) -> dict[str, Any]:
    template = deepcopy(profile.rule_template)
    conda = template.setdefault("environment", {}).setdefault("conda", {})
    dependencies = conda.get("dependencies")
    if isinstance(dependencies, list):
        conda["dependencies"] = [
            package_spec if str(dependency).strip() == "{packageSpec}" else dependency
            for dependency in dependencies
        ]
    elif package_spec:
        conda["dependencies"] = [package_spec]
    return template


TOOL_PROFILES: tuple[ToolProfile, ...] = (
    ToolProfile(
        profile_id="bracken",
        version=1,
        tool_names=("bracken",),
        preferred_wrapper_paths=("bio/bracken/bracken",),
        rule_template={
            "commandTemplate": (
                "bracken -d {config.bracken_db:q} "
                "-i {input.kraken_report:q} "
                "-o {output.abundance:q} "
                "-r {params.read_length} "
                "-l {params.level}"
            ),
            "inputs": [
                {
                    "name": "kraken_report",
                    "type": "file",
                    "kind": "taxonomy_report",
                    "mimeType": "text/plain",
                    "required": True,
                }
            ],
            "outputs": [
                {
                    "name": "abundance",
                    "path": "results/bracken-abundance.tsv",
                    "kind": "taxonomy_abundance",
                    "mimeType": "text/tab-separated-values",
                }
            ],
            "params": {
                "read_length": {
                    "type": "integer",
                    "title": "Read length",
                    "default": 100,
                    "minimum": 1,
                },
                "level": {
                    "type": "string",
                    "title": "Taxonomic level",
                    "default": "S",
                    "enum": ["D", "P", "C", "O", "F", "G", "S"],
                },
            },
            "resources": {
                "threads": {"default": 1},
                "mem_mb": {"default": 1024},
                "bracken_db": {
                    "type": "database",
                    "required": True,
                    "acceptedTemplates": ["bracken"],
                    "configKey": "bracken_db",
                },
            },
            "environment": {
                "conda": {
                    "channels": ["conda-forge", "bioconda"],
                    "dependencies": ["{packageSpec}"],
                }
            },
            "log": "logs/bracken.log",
            "smokeTest": {
                "inputs": {
                    "kraken_report": {
                        "filename": "kraken.report",
                        "content": "100.00\t1\t1\tR\t1\troot\n",
                        "mimeType": "text/plain",
                    }
                },
                "params": {"read_length": 100, "level": "S"},
                "timeoutSeconds": 300,
            },
        },
    ),
    ToolProfile(
        profile_id="fastp",
        version=1,
        tool_names=("fastp",),
        preferred_wrapper_paths=("bio/fastp",),
        rule_template={
            "wrapper": "v9.8.0/bio/fastp",
            "inputs": [
                {
                    "name": "sample",
                    "type": "file",
                    "kind": "sequence_reads",
                    "mimeType": "text/plain",
                    "required": True,
                    "multiple": True,
                }
            ],
            "outputs": [
                {
                    "name": "trimmed",
                    "path": "results/fastp-cleaned.fastq",
                    "kind": "sequence_reads",
                    "mimeType": "text/plain",
                },
                {
                    "name": "html",
                    "path": "results/fastp.html",
                    "kind": "report",
                    "mimeType": "text/html",
                },
                {
                    "name": "json",
                    "path": "results/fastp.json",
                    "kind": "report",
                    "mimeType": "application/json",
                },
            ],
            "params": {
                "extra": {"type": "string", "title": "Extra fastp arguments", "default": ""},
                "adapters": {"type": "string", "title": "Adapter arguments", "default": ""},
            },
            "resources": {"threads": {"default": 2}, "mem_mb": {"default": 2048}},
            "environment": {
                "conda": {
                    "channels": ["conda-forge", "bioconda"],
                    "dependencies": ["{packageSpec}"],
                }
            },
            "log": "logs/fastp.log",
            "smokeTest": {
                "inputs": {
                    "sample": {
                        "filename": "reads.fastq",
                        "content": "@smoke\nACGTACGT\n+\nFFFFFFFF\n",
                        "mimeType": "text/plain",
                    }
                },
                "timeoutSeconds": 300,
            },
        },
    ),
    ToolProfile(
        profile_id="fastqc",
        version=1,
        tool_names=("fastqc",),
        preferred_wrapper_paths=("bio/fastqc",),
        rule_template={
            "wrapper": "v9.8.0/bio/fastqc",
            "inputs": [
                {
                    "name": "reads",
                    "type": "file",
                    "kind": "sequence_reads",
                    "mimeType": "text/plain",
                    "required": True,
                }
            ],
            "outputs": [
                {
                    "name": "html",
                    "path": "results/reads_fastqc.html",
                    "kind": "report",
                    "mimeType": "text/html",
                },
                {
                    "name": "zip",
                    "path": "results/reads_fastqc.zip",
                    "kind": "report_archive",
                    "mimeType": "application/zip",
                },
            ],
            "params": {},
            "resources": {"threads": {"default": 2}, "mem_mb": {"default": 2048}},
            "environment": {
                "conda": {
                    "channels": ["conda-forge", "bioconda"],
                    "dependencies": ["{packageSpec}"],
                }
            },
            "log": "logs/fastqc.log",
            "smokeTest": {
                "inputs": {
                    "reads": {
                        "filename": "reads.fastq",
                        "content": "@smoke\nACGTACGT\n+\nFFFFFFFF\n",
                        "mimeType": "text/plain",
                    }
                },
                "timeoutSeconds": 300,
            },
        },
    ),
    ToolProfile(
        profile_id="kraken2",
        version=1,
        tool_names=("kraken2",),
        preferred_wrapper_paths=("bio/kraken2",),
        rule_template={
            "commandTemplate": (
                "kraken2 --db {config.kraken2_db:q} "
                "--threads {threads} "
                "--confidence {params.confidence} "
                "--report {output.report:q} "
                "--output {output.classification:q} "
                "{input.reads:q}"
            ),
            "inputs": [
                {
                    "name": "reads",
                    "type": "file",
                    "kind": "sequence_reads",
                    "mimeType": "text/plain",
                    "required": True,
                }
            ],
            "outputs": [
                {
                    "name": "report",
                    "path": "results/kraken2.report",
                    "kind": "taxonomy_report",
                    "mimeType": "text/plain",
                },
                {
                    "name": "classification",
                    "path": "results/kraken2.classification.txt",
                    "kind": "taxonomy_classification",
                    "mimeType": "text/plain",
                },
            ],
            "params": {
                "confidence": {
                    "type": "number",
                    "title": "Confidence",
                    "default": 0.0,
                    "minimum": 0.0,
                    "maximum": 1.0,
                }
            },
            "resources": {
                "threads": {"default": 2},
                "mem_mb": {"default": 4096},
                "kraken2_db": {
                    "type": "database",
                    "required": True,
                    "acceptedTemplates": ["kraken2"],
                    "configKey": "kraken2_db",
                },
            },
            "environment": {
                "conda": {
                    "channels": ["conda-forge", "bioconda"],
                    "dependencies": ["{packageSpec}"],
                }
            },
            "log": "logs/kraken2.log",
            "smokeTest": {
                "inputs": {
                    "reads": {
                        "filename": "reads.fastq",
                        "content": "@smoke\nACGTACGT\n+\nFFFFFFFF\n",
                        "mimeType": "text/plain",
                    }
                },
                "params": {"confidence": 0.0},
                "timeoutSeconds": 300,
            },
        },
    ),
    ToolProfile(
        profile_id="multiqc",
        version=1,
        tool_names=("multiqc",),
        preferred_wrapper_paths=("bio/multiqc",),
        rule_template={
            "wrapper": "v9.8.0/bio/multiqc",
            "inputs": [
                {
                    "name": "fastqc_data",
                    "type": "file",
                    "kind": "qc_report",
                    "mimeType": "text/plain",
                    "required": True,
                }
            ],
            "outputs": [
                {
                    "name": "report",
                    "path": "results/multiqc.html",
                    "kind": "report",
                    "mimeType": "text/html",
                }
            ],
            "params": {},
            "resources": {"threads": {"default": 1}, "mem_mb": {"default": 1024}},
            "environment": {
                "conda": {
                    "channels": ["conda-forge", "bioconda"],
                    "dependencies": ["{packageSpec}"],
                }
            },
            "log": "logs/multiqc.log",
            "smokeTest": {
                "inputs": {
                    "fastqc_data": {
                        "filename": "fastqc_data.txt",
                        "content": (
                            "##FastQC\t0.12.1\n"
                            ">>Basic Statistics\tpass\n"
                            "#Measure\tValue\n"
                            "Filename\treads.fastq\n"
                            "File type\tConventional base calls\n"
                            "Encoding\tSanger / Illumina 1.9\n"
                            "Total Sequences\t1\n"
                            "Sequences flagged as poor quality\t0\n"
                            "Sequence length\t8\n"
                            "%GC\t50\n"
                            ">>END_MODULE\n"
                        ),
                        "mimeType": "text/plain",
                    }
                },
                "timeoutSeconds": 300,
            },
        },
    ),
)

def _matched_wrapper(profile: ToolProfile, wrappers: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not wrappers:
        return None
    preferred = set(profile.preferred_wrapper_paths)
    for wrapper in wrappers:
        if _clean(wrapper.get("wrapperPath")) in preferred:
            return wrapper
    return wrappers[0]


def _profile_wrapper_lock(profile: ToolProfile) -> dict[str, str]:
    wrapper = _clean(profile.rule_template.get("wrapper"))
    if not wrapper:
        return {}
    wrapper_ref, wrapper_path = _split_wrapper_identifier(wrapper)
    if not wrapper_ref or not wrapper_path:
        return {}
    return {
        "wrapperRepository": PROFILE_WRAPPER_REPOSITORY,
        "wrapperRef": wrapper_ref,
        "wrapperPath": wrapper_path,
        "wrapperIdentifier": wrapper,
    }


def _split_wrapper_identifier(wrapper: str) -> tuple[str, str]:
    parts = [part for part in _clean(wrapper).split("/") if part]
    if len(parts) < 2:
        return "", ""
    return parts[0], "/".join(parts[1:])


def _package_spec_from_identity(tool: dict[str, Any]) -> str:
    source = _clean(tool.get("source")) or "bioconda"
    name = _clean(tool.get("name")) or "tool"
    version = _clean(tool.get("latestVersion") or tool.get("version"))
    return f"{source}::{name}={version}" if version else f"{source}::{name}"


def _package_version(package_spec: str) -> str:
    package = _clean(package_spec).rsplit("::", 1)[-1]
    if not package or any(operator in package for operator in (">", "<", "*")):
        return ""
    for operator in ("==", "="):
        if operator in package:
            return package.split(operator, 1)[1].split("=", 1)[0].strip()
    return ""


def _normalize_tool_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9.+-]+", "-", _clean(value).lower()).strip("-")


def _clean(value: Any) -> str:
    return str(value or "").strip()


_PROFILE_BY_TOOL_NAME: dict[str, ToolProfile] | None = None


def _profile_for_tool(name: Any) -> ToolProfile | None:
    return _profile_by_tool_name().get(_normalize_tool_name(name))


def _profile_by_tool_name() -> dict[str, ToolProfile]:
    global _PROFILE_BY_TOOL_NAME
    if _PROFILE_BY_TOOL_NAME is None:
        _PROFILE_BY_TOOL_NAME = {
            _normalize_tool_name(tool_name): profile
            for profile in TOOL_PROFILES
            for tool_name in profile.tool_names
        }
    return _PROFILE_BY_TOOL_NAME
