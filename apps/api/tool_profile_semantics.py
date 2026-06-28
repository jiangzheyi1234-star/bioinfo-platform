"""Curated EDAM semantic fields for in-repo tool profile ports."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


EDAM_GENERIC_DATA = "http://edamontology.org/data_0006"
EDAM_SEQUENCE = "http://edamontology.org/data_2044"
EDAM_SEQUENCE_ALIGNMENT = "http://edamontology.org/data_0863"
EDAM_SEQUENCE_ASSEMBLY = "http://edamontology.org/data_0925"
EDAM_GENE_REPORT = "http://edamontology.org/data_0916"

EDAM_GENERIC_FORMAT = "http://edamontology.org/format_1915"
EDAM_FASTA = "http://edamontology.org/format_1929"
EDAM_FASTQ = "http://edamontology.org/format_1930"
EDAM_HTML = "http://edamontology.org/format_2331"
EDAM_BAM = "http://edamontology.org/format_2572"
EDAM_SAM = "http://edamontology.org/format_2573"
EDAM_GFF = "http://edamontology.org/format_1975"
EDAM_BED = "http://edamontology.org/format_3003"
EDAM_BIGWIG = "http://edamontology.org/format_3006"
EDAM_VCF = "http://edamontology.org/format_3016"
EDAM_JSON = "http://edamontology.org/format_3464"
EDAM_TSV = "http://edamontology.org/format_3475"

_TABULAR_KINDS = {
    "annotation_table",
    "coverage_table",
    "distance_table",
    "functional_profile",
    "interval_table",
    "sequence_composition",
    "sequence_motif_hits",
    "sequence_stats",
    "sequence_table",
    "tabular_data",
    "tabular_hits",
    "tabular_sequence",
    "tabular_summary",
    "taxonomy_abundance",
    "taxonomy_lineage",
    "taxonomy_profile",
    "transcript_quantification",
    "variant_table",
}
_GENERIC_TEXT_KINDS = {
    "alignment_stats",
    "amplicon_sequences",
    "amr_report",
    "annotation_report",
    "bowtie2_index",
    "bwa_index",
    "coverage_bedgraph",
    "distance_matrix",
    "genome_file",
    "identifier_list",
    "peaks_narrowpeak",
    "profile_hmm",
    "profile_hmm_hits",
    "profile_hmm_report",
    "qc_report",
    "quality_report",
    "report_archive",
    "sequence_search_results",
    "sequence_sketch_report",
    "taxonomy_classification",
    "taxonomy_ids",
    "taxonomy_report",
    "variant_stats",
}
_PORT_KIND_SEMANTICS: dict[str, tuple[str, str]] = {
    **{kind: (EDAM_GENERIC_DATA, EDAM_TSV) for kind in _TABULAR_KINDS},
    **{kind: (EDAM_GENERIC_DATA, EDAM_GENERIC_FORMAT) for kind in _GENERIC_TEXT_KINDS},
    "alignment_bam": (EDAM_SEQUENCE_ALIGNMENT, EDAM_BAM),
    "alignment_index": (EDAM_GENERIC_DATA, EDAM_BAM),
    "alignment_paf": (EDAM_GENERIC_DATA, EDAM_TSV),
    "alignment_sam": (EDAM_SEQUENCE_ALIGNMENT, EDAM_SAM),
    "annotation_gff": (EDAM_GENE_REPORT, EDAM_GFF),
    "assembly_contigs": (EDAM_SEQUENCE_ASSEMBLY, EDAM_FASTA),
    "coverage_bigwig": (EDAM_GENERIC_DATA, EDAM_BIGWIG),
    "fasta_index": (EDAM_GENERIC_DATA, EDAM_FASTA),
    "gene_counts": (EDAM_GENE_REPORT, EDAM_TSV),
    "gene_sequence": (EDAM_GENERIC_DATA, EDAM_FASTA),
    "intervals_bed": (EDAM_GENERIC_DATA, EDAM_BED),
    "multiple_sequence_alignment": (EDAM_GENERIC_DATA, EDAM_FASTA),
    "protein_sequence": (EDAM_GENERIC_DATA, EDAM_FASTA),
    "reference_fasta": (EDAM_GENERIC_DATA, EDAM_FASTA),
    "report": (EDAM_GENERIC_DATA, EDAM_HTML),
    "sequence_clusters": (EDAM_GENERIC_DATA, EDAM_FASTA),
    "sequence_reads": (EDAM_SEQUENCE, EDAM_FASTQ),
    "sequence_sketch": (EDAM_GENERIC_DATA, EDAM_GENERIC_FORMAT),
    "sequence_windows": (EDAM_GENERIC_DATA, EDAM_FASTA),
    "variants_vcf": (EDAM_GENERIC_DATA, EDAM_VCF),
}


def enrich_rule_template_semantics(rule_template: dict[str, Any]) -> dict[str, Any]:
    enriched = deepcopy(rule_template)
    for key in ("inputs", "outputs"):
        ports = enriched.get(key)
        if not isinstance(ports, list):
            continue
        enriched[key] = [_enrich_port(port) if isinstance(port, dict) else port for port in ports]
    return enriched


def semantic_port_fields(kind: str, *, data: str = "", format: str = "") -> dict[str, str]:
    resolved_data, resolved_format = _PORT_KIND_SEMANTICS.get(_clean(kind), ("", ""))
    if not resolved_data and not resolved_format and not _clean(data) and not _clean(format):
        return {"type": "", "data": "", "format": ""}
    return {
        "type": "file",
        "data": _clean(data) or resolved_data,
        "format": _clean(format) or resolved_format,
    }


def _enrich_port(port: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(port)
    fields = semantic_port_fields(str(enriched.get("kind") or ""))
    for key, value in fields.items():
        if value and not _clean(enriched.get(key)):
            enriched[key] = value
    return enriched


def _clean(value: Any) -> str:
    return str(value or "").strip()
