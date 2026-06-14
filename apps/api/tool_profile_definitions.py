"""Static H2OMeta tool profile definitions."""

from __future__ import annotations

from .bio_tool_pack_manifest import bio_tool_pack_manifest_from_profiles, load_bio_tool_pack_manifest
from .tool_profile_open_source_pack import OPEN_SOURCE_TOOL_PROFILES
from .tool_profile_model import ToolProfile


_CURATED_TOOL_PROFILES: tuple[ToolProfile, ...] = (
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
                        "content": (
                            "100.00\t10\t0\tR\t1\troot\n"
                            "100.00\t10\t0\tD\t2\t  Bacteria\n"
                            "100.00\t10\t0\tP\t1224\t    Pseudomonadota\n"
                            "100.00\t10\t0\tC\t1236\t      Gammaproteobacteria\n"
                            "100.00\t10\t0\tO\t91347\t        Enterobacterales\n"
                            "100.00\t10\t0\tF\t543\t          Enterobacteriaceae\n"
                            "100.00\t10\t0\tG\t561\t            Escherichia\n"
                            "100.00\t10\t10\tS\t562\t              Escherichia coli\n"
                        ),
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
                        "content": "@smoke\nACGTACGTACGTACGTACGT\n+\nFFFFFFFFFFFFFFFFFFFF\n",
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
    ToolProfile(
        profile_id="seqkit-stats",
        version=1,
        tool_names=("seqkit", "seqkit stats", "seqkit-stats"),
        preferred_wrapper_paths=("bio/seqkit",),
        rule_template={
            "wrapper": "v9.8.0/bio/seqkit",
            "inputs": [
                {
                    "name": "fastx",
                    "type": "file",
                    "kind": "sequence_reads",
                    "mimeType": "text/plain",
                    "required": True,
                }
            ],
            "outputs": [
                {
                    "name": "stats",
                    "path": "results/seqkit-stats.tsv",
                    "kind": "sequence_stats",
                    "mimeType": "text/tab-separated-values",
                }
            ],
            "params": {
                "command": {
                    "type": "string",
                    "title": "SeqKit command",
                    "default": "stats",
                    "const": "stats",
                },
                "extra": {
                    "type": "string",
                    "title": "Extra seqkit stats arguments",
                    "default": "--all --tabular",
                },
            },
            "resources": {"threads": {"default": 2}, "mem_mb": {"default": 1024}},
            "environment": {
                "conda": {
                    "channels": ["conda-forge", "bioconda"],
                    "dependencies": ["{packageSpec}"],
                }
            },
            "log": "logs/seqkit-stats.log",
            "smokeTest": {
                "inputs": {
                    "fastx": {
                        "filename": "reads.fastq",
                        "content": "@smoke\nACGTACGT\n+\nFFFFFFFF\n",
                        "mimeType": "text/plain",
                    }
                },
                "params": {"command": "stats", "extra": "--all --tabular"},
                "timeoutSeconds": 300,
            },
        },
    ),
) + OPEN_SOURCE_TOOL_PROFILES


DEFAULT_BIO_TOOL_PACK_MANIFEST = bio_tool_pack_manifest_from_profiles(
    _CURATED_TOOL_PROFILES,
    pack_id="h2ometa-metagenomics-core",
    version=1,
    name="H2OMeta Metagenomics Core Tool Pack",
    source="https://github.com/h2ometa/h2ometa",
    license="project-license",
    citations=(
        "H2OMeta curated Bio Tool Pack v1",
        "Bioconda, BioContainers, Snakemake wrappers, and bio.tools package metadata",
    ),
)

TOOL_PROFILES: tuple[ToolProfile, ...] = load_bio_tool_pack_manifest(DEFAULT_BIO_TOOL_PACK_MANIFEST)
