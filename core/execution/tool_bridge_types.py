from __future__ import annotations

from dataclasses import dataclass, field

_TOOL_ARCHETYPES: dict[str, str] = {
    "fastp": "qc_report",
    "hostile": "qc_report",
    "kraken2": "taxonomy_profile",
    "centrifuge": "taxonomy_profile",
    "metaphlan": "taxonomy_profile",
    "bracken": "taxonomy_profile",
    "gtdbtk": "taxonomy_profile",
    "krona": "html_report",
    "prokka": "annotation_table",
    "bakta": "annotation_table",
    "prodigal": "annotation_table",
    "eggnog": "annotation_table",
    "blastn": "annotation_table",
    "abricate": "annotation_table",
    "amrfinderplus": "annotation_table",
    "rgi": "annotation_table",
    "integron_finder": "annotation_table",
    "isescan": "annotation_table",
    "genomad": "annotation_table",
    "quast": "quality_assessment",
    "busco": "quality_assessment",
    "checkm2": "quality_assessment",
    "gunc": "quality_assessment",
    "concoct": "artifact_collection",
    "das_tool": "artifact_collection",
    "maxbin2": "artifact_collection",
    "metabat2": "artifact_collection",
    "semibin2": "artifact_collection",
    "unknown_sample_detection": "workflow_product",
    "wastewater_metagenomics_basic": "workflow_product",
    "animal_metagenomics_basic": "workflow_product",
    "primer_design": "workflow_product",
    "multiplex_primer_panel": "workflow_product",
}


@dataclass
class ExecutionResult:
    status: str
    message: str = ""
    execution_id: str = ""
    sample_id: str = ""


@dataclass
class PrimerView:
    description: str = ""
    status: dict = field(default_factory=dict)
    parameters: list = field(default_factory=list)
    summary: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    artifacts: list = field(default_factory=list)
    remote_result_dir: str = ""
