"""EDAM semantic enrichment for curated tool profile rule ports."""

from __future__ import annotations

from copy import deepcopy
from pathlib import PurePosixPath
from typing import Any


EDAM_SEQUENCE = "http://edamontology.org/data_2044"
EDAM_SEQUENCE_ALIGNMENT = "http://edamontology.org/data_0863"
EDAM_SEQUENCE_ASSEMBLY = "http://edamontology.org/data_0925"
EDAM_GENE_REPORT = "http://edamontology.org/data_0916"

EDAM_FASTA = "http://edamontology.org/format_1929"
EDAM_FASTQ = "http://edamontology.org/format_1930"
EDAM_HTML = "http://edamontology.org/format_2331"
EDAM_BAM = "http://edamontology.org/format_2572"
EDAM_SAM = "http://edamontology.org/format_2573"
EDAM_BED = "http://edamontology.org/format_3003"
EDAM_VCF = "http://edamontology.org/format_3016"


def enrich_rule_template_semantics(rule_template: dict[str, Any]) -> dict[str, Any]:
    enriched = deepcopy(rule_template)
    for key in ("inputs", "outputs"):
        ports = enriched.get(key)
        if not isinstance(ports, list):
            continue
        enriched[key] = [_enrich_port(port) if isinstance(port, dict) else port for port in ports]
    return enriched


def _enrich_port(port: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(port)
    if not str(enriched.get("data") or enriched.get("edamData") or "").strip():
        data = _infer_data(enriched)
        if data:
            enriched["data"] = data
    if not str(enriched.get("format") or enriched.get("edamFormat") or "").strip():
        format_id = _infer_format(enriched)
        if format_id:
            enriched["format"] = format_id
    return enriched


def _infer_data(port: dict[str, Any]) -> str:
    kind = _clean(port.get("kind"))
    if kind in {"sequence_reads", "assembly_contigs"}:
        return EDAM_SEQUENCE if kind == "sequence_reads" else EDAM_SEQUENCE_ASSEMBLY
    if kind in {"alignment_sam", "alignment_bam"}:
        return EDAM_SEQUENCE_ALIGNMENT
    if kind in {"annotation_gff", "gene_counts"}:
        return EDAM_GENE_REPORT
    return ""


def _infer_format(port: dict[str, Any]) -> str:
    for suffix in _port_suffixes(port):
        if suffix in {".fastq", ".fq"}:
            return EDAM_FASTQ
        if suffix in {".fasta", ".fa", ".fna", ".faa"}:
            return EDAM_FASTA
        if suffix == ".sam":
            return EDAM_SAM
        if suffix == ".bam":
            return EDAM_BAM
        if suffix == ".vcf":
            return EDAM_VCF
        if suffix == ".bed":
            return EDAM_BED
        if suffix in {".html", ".htm"}:
            return EDAM_HTML

    kind = _clean(port.get("kind"))
    mime_type = _clean(port.get("mimeType"))
    if kind == "sequence_reads" and mime_type == "text/plain":
        return EDAM_FASTQ
    if kind == "assembly_contigs" and mime_type == "text/plain":
        return EDAM_FASTA
    if kind == "alignment_sam":
        return EDAM_SAM
    if kind == "alignment_bam":
        return EDAM_BAM
    if kind == "variants_vcf":
        return EDAM_VCF
    if kind == "intervals_bed":
        return EDAM_BED
    if mime_type == "text/html":
        return EDAM_HTML
    return ""


def _port_suffixes(port: dict[str, Any]) -> list[str]:
    suffixes: list[str] = []
    for key in ("path", "filename", "name"):
        text = _clean(port.get(key))
        if not text:
            continue
        path = PurePosixPath(text)
        suffixes.extend(suffix.lower() for suffix in path.suffixes)
        if "." in text:
            suffixes.append("." + text.rsplit(".", 1)[-1].lower())
    return suffixes


def _clean(value: Any) -> str:
    return str(value or "").strip()
