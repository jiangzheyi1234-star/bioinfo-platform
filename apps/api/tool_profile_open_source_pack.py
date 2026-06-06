"""Curated open-source Bio Tool Pack v1 profiles."""

from __future__ import annotations

from typing import Any

from .tool_profile_model import ToolProfile


def _profile(
    profile_id: str,
    package_name: str,
    command: str,
    inputs: list[dict[str, Any]],
    outputs: list[dict[str, Any]],
    *,
    tool_names: tuple[str, ...] | None = None,
    params: dict[str, Any] | None = None,
    resources: dict[str, Any] | None = None,
    threads: int = 1,
    mem_mb: int = 1024,
) -> ToolProfile:
    return ToolProfile(
        profile_id=profile_id,
        version=1,
        tool_names=tool_names or (package_name,),
        rule_template={
            "commandTemplate": command,
            "inputs": [_rule_input(item) for item in inputs],
            "outputs": outputs,
            "params": params or {},
            "resources": {"threads": {"default": threads}, "mem_mb": {"default": mem_mb}, **(resources or {})},
            "environment": {"conda": {"channels": ["conda-forge", "bioconda"], "dependencies": ["{packageSpec}"]}},
            "log": f"logs/{profile_id}.log",
            "smokeTest": {
                "inputs": {
                    item["name"]: {
                        "filename": item.get("filename", f"{item['name']}.txt"),
                        "content": item["content"],
                        "mimeType": item["mimeType"],
                    }
                    for item in inputs
                },
                "timeoutSeconds": 300,
            },
        },
    )


def _fastq_input(name: str) -> list[dict[str, Any]]:
    return [_input(name, "sequence_reads", "text/plain", filename=f"{name}.fastq", content="@smoke\nACGTACGT\n+\nFFFFFFFF\n")]


def _input(
    name: str,
    kind: str,
    mime_type: str,
    *,
    filename: str | None = None,
    content: str,
) -> dict[str, Any]:
    return {"name": name, "type": "file", "kind": kind, "mimeType": mime_type, "required": True, "filename": filename, "content": content}


def _rule_input(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in item.items()
        if key not in {"filename", "content"} and value is not None
    }


def _output(name: str, path: str, kind: str, mime_type: str) -> dict[str, Any]:
    return {"name": name, "path": path, "kind": kind, "mimeType": mime_type}


def _database_resource(template_id: str) -> dict[str, Any]:
    return {"type": "database", "required": True, "acceptedTemplates": [template_id]}


OPEN_SOURCE_TOOL_PROFILES: tuple[ToolProfile, ...] = (
    _profile(
        "cutadapt",
        "cutadapt",
        "cutadapt -j {threads} -o {output.trimmed:q} {input.reads:q}",
        _fastq_input("reads"),
        [_output("trimmed", "results/cutadapt-trimmed.fastq", "sequence_reads", "text/plain")],
        threads=2,
    ),
    _profile(
        "trimmomatic",
        "trimmomatic",
        "trimmomatic SE -threads {threads} {input.reads:q} {output.trimmed:q} {params.extra}",
        _fastq_input("reads"),
        [_output("trimmed", "results/trimmomatic-trimmed.fastq", "sequence_reads", "text/plain")],
        params={"extra": {"type": "string", "title": "Extra Trimmomatic arguments", "default": "SLIDINGWINDOW:4:20 MINLEN:20"}},
        threads=2,
    ),
    _profile(
        "bwa-mem",
        "bwa",
        "bwa mem -t {threads} {config.bwa_index:q} {input.reads:q} > {output.sam:q}",
        _fastq_input("reads"),
        [_output("sam", "results/bwa.sam", "alignment_sam", "text/plain")],
        resources={"bwa_index": _database_resource("bwa")},
        threads=4,
        mem_mb=4096,
    ),
    _profile(
        "bowtie2-align",
        "bowtie2",
        "bowtie2 -x {config.bowtie2_index:q} -U {input.reads:q} -S {output.sam:q} --threads {threads}",
        _fastq_input("reads"),
        [_output("sam", "results/bowtie2.sam", "alignment_sam", "text/plain")],
        resources={"bowtie2_index": _database_resource("bowtie2")},
        threads=4,
        mem_mb=4096,
    ),
    _profile(
        "minimap2-align",
        "minimap2",
        "minimap2 -a -t {threads} {config.reference_fasta:q} {input.reads:q} > {output.sam:q}",
        _fastq_input("reads"),
        [_output("sam", "results/minimap2.sam", "alignment_sam", "text/plain")],
        resources={"reference_fasta": _database_resource("custom")},
        threads=4,
        mem_mb=4096,
    ),
    _profile(
        "deeptools-bamcoverage",
        "deeptools",
        "bamCoverage -b {input.bam:q} -o {output.bigwig:q} --numberOfProcessors {threads}",
        [_input("bam", "alignment_bam", "application/octet-stream", content="BAM placeholder\n")],
        [_output("bigwig", "results/coverage.bw", "coverage_bigwig", "application/octet-stream")],
        threads=2,
    ),
    _profile(
        "bedtools-bamtobed",
        "bedtools",
        "bedtools bamtobed -i {input.bam:q} > {output.bed:q}",
        [_input("bam", "alignment_bam", "application/octet-stream", content="BAM placeholder\n")],
        [_output("bed", "results/alignments.bed", "intervals_bed", "text/plain")],
    ),
    _profile(
        "bcftools-stats",
        "bcftools",
        "bcftools stats {input.vcf:q} > {output.stats:q}",
        [_input("vcf", "variants_vcf", "text/plain", content="##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n")],
        [_output("stats", "results/bcftools-stats.txt", "variant_stats", "text/plain")],
    ),
    _profile(
        "mash-sketch",
        "mash",
        "mash sketch -o results/mash {input.fastx:q} && cp results/mash.msh {output.sketch:q}",
        _fastq_input("fastx"),
        [_output("sketch", "results/mash.msh", "sequence_sketch", "application/octet-stream")],
    ),
    _profile(
        "spades-assembly",
        "spades",
        "spades.py -s {input.reads:q} -o results/spades && test -s {output.contigs:q}",
        _fastq_input("reads"),
        [_output("contigs", "results/spades/contigs.fasta", "assembly_contigs", "text/plain")],
        threads=4,
        mem_mb=8192,
    ),
    _profile(
        "quast-report",
        "quast",
        "quast.py {input.contigs:q} -o results/quast --threads {threads} && cp results/quast/report.html {output.html:q}",
        [_input("contigs", "assembly_contigs", "text/plain", filename="contigs.fasta", content=">contig1\nACGTACGT\n")],
        [_output("html", "results/quast/report.html", "report", "text/html")],
        threads=2,
    ),
    _profile(
        "prokka-annotation",
        "prokka",
        "prokka --outdir results/prokka --prefix sample {input.contigs:q} && cp results/prokka/sample.gff {output.gff:q}",
        [_input("contigs", "assembly_contigs", "text/plain", filename="contigs.fasta", content=">contig1\nACGTACGT\n")],
        [_output("gff", "results/prokka/sample.gff", "annotation_gff", "text/plain")],
        threads=2,
        mem_mb=4096,
    ),
    _profile(
        "macs2-callpeak",
        "macs2",
        "macs2 callpeak -t {input.bam:q} -n sample --outdir results/macs2 {params.extra} && cp results/macs2/sample_peaks.narrowPeak {output.peaks:q}",
        [_input("bam", "alignment_bam", "application/octet-stream", content="BAM placeholder\n")],
        [_output("peaks", "results/macs2/sample_peaks.narrowPeak", "peaks_narrowpeak", "text/plain")],
        params={"extra": {"type": "string", "title": "Extra MACS2 arguments", "default": "--nomodel"}},
    ),
    _profile(
        "featurecounts",
        "subread",
        "featureCounts -T {threads} -a {config.annotation_gtf:q} -o {output.counts:q} {input.bam:q}",
        [_input("bam", "alignment_bam", "application/octet-stream", content="BAM placeholder\n")],
        [_output("counts", "results/featurecounts.txt", "gene_counts", "text/plain")],
        tool_names=("subread", "featureCounts"),
        resources={"annotation_gtf": _database_resource("custom")},
        threads=2,
    ),
)
