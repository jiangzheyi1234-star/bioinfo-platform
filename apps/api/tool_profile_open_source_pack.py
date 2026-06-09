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
        package_name=package_name,
    )


def _fastq_input(name: str) -> list[dict[str, Any]]:
    return [_input(name, "sequence_reads", "text/plain", filename=f"{name}.fastq", content="@smoke\nACGTACGT\n+\nFFFFFFFF\n")]


def _fasta_input(name: str) -> list[dict[str, Any]]:
    return [_input(name, "sequence_reads", "text/plain", filename=f"{name}.fasta", content=">smoke\nACGTACGT\n")]


def _sam_input(name: str = "alignment") -> list[dict[str, Any]]:
    return [
        _input(
            name,
            "alignment_sam",
            "text/plain",
            filename=f"{name}.sam",
            content="@HD\tVN:1.6\tSO:unsorted\n@SQ\tSN:chr1\tLN:8\nsmoke\t0\tchr1\t1\t60\t8M\t*\t0\t0\tACGTACGT\tFFFFFFFF\n",
        )
    ]


def _vcf_input(name: str = "vcf") -> list[dict[str, Any]]:
    return [
        _input(
            name,
            "variants_vcf",
            "text/plain",
            filename=f"{name}.vcf",
            content="##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n",
        )
    ]


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
        "samtools view -bS {input.alignment:q} > results/deeptools-input.bam && bamCoverage -b results/deeptools-input.bam -o {output.bigwig:q} --numberOfProcessors {threads}",
        _sam_input(),
        [_output("bigwig", "results/coverage.bw", "coverage_bigwig", "application/octet-stream")],
        threads=2,
    ),
    _profile(
        "bedtools-bamtobed",
        "bedtools",
        "samtools view -bS {input.alignment:q} > results/bedtools-input.bam && bedtools bamtobed -i results/bedtools-input.bam > {output.bed:q}",
        _sam_input(),
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
        "samtools view -bS {input.alignment:q} > results/macs2-input.bam && macs2 callpeak -t results/macs2-input.bam -n sample --outdir results/macs2 {params.extra} && cp results/macs2/sample_peaks.narrowPeak {output.peaks:q}",
        _sam_input(),
        [_output("peaks", "results/macs2/sample_peaks.narrowPeak", "peaks_narrowpeak", "text/plain")],
        params={"extra": {"type": "string", "title": "Extra MACS2 arguments", "default": "--nomodel"}},
    ),
    _profile(
        "featurecounts",
        "subread",
        "samtools view -bS {input.alignment:q} > results/featurecounts-input.bam && featureCounts -T {threads} -a {config.annotation_gtf:q} -o {output.counts:q} results/featurecounts-input.bam",
        _sam_input(),
        [_output("counts", "results/featurecounts.txt", "gene_counts", "text/plain")],
        tool_names=("subread", "featureCounts"),
        resources={"annotation_gtf": _database_resource("custom")},
        threads=2,
    ),
    _profile(
        "samtools-sort",
        "samtools",
        "samtools view -bS {input.alignment:q} | samtools sort -@ {threads} -o {output.sorted_bam:q}",
        _sam_input(),
        [_output("sorted_bam", "results/samtools-sorted.bam", "alignment_bam", "application/octet-stream")],
        tool_names=("samtools-sort", "samtools sort"),
        threads=2,
    ),
    _profile(
        "picard-markduplicates",
        "picard",
        "samtools view -bS {input.alignment:q} > results/picard-input.bam && picard MarkDuplicates I=results/picard-input.bam O={output.dedup_bam:q} M={output.metrics:q} {params.extra}",
        _sam_input(),
        [
            _output("dedup_bam", "results/picard-dedup.bam", "alignment_bam", "application/octet-stream"),
            _output("metrics", "results/picard-markduplicates-metrics.txt", "report", "text/plain"),
        ],
        tool_names=("picard-markduplicates", "picard MarkDuplicates"),
        params={"extra": {"type": "string", "title": "Extra Picard MarkDuplicates arguments", "default": "VALIDATION_STRINGENCY=SILENT"}},
        mem_mb=2048,
    ),
    _profile(
        "blastn-search",
        "blast",
        "blastn -query {input.query:q} -db {config.blast_db:q} -out {output.hits:q} -outfmt 6 {params.extra}",
        _fasta_input("query"),
        [_output("hits", "results/blastn-hits.tsv", "tabular_hits", "text/tab-separated-values")],
        tool_names=("blastn-search", "blastn"),
        params={"extra": {"type": "string", "title": "Extra BLASTN arguments", "default": ""}},
        resources={"blast_db": _database_resource("blast")},
        threads=2,
        mem_mb=2048,
    ),
    _profile(
        "salmon-quant",
        "salmon",
        "salmon quant -i {config.transcriptome_index:q} -l A -r {input.reads:q} -p {threads} -o results/salmon && cp results/salmon/quant.sf {output.quant:q}",
        _fastq_input("reads"),
        [_output("quant", "results/salmon/quant.sf", "transcript_quantification", "text/tab-separated-values")],
        tool_names=("salmon-quant", "salmon quant"),
        resources={"transcriptome_index": _database_resource("custom")},
        threads=4,
        mem_mb=4096,
    ),
    _profile(
        "hisat2-align",
        "hisat2",
        "hisat2 -x {config.hisat2_index:q} -U {input.reads:q} -S {output.sam:q} -p {threads}",
        _fastq_input("reads"),
        [_output("sam", "results/hisat2.sam", "alignment_sam", "text/plain")],
        resources={"hisat2_index": _database_resource("custom")},
        threads=4,
        mem_mb=4096,
    ),
    _profile(
        "star-align",
        "star",
        "STAR --genomeDir {config.star_index:q} --readFilesIn {input.reads:q} --runThreadN {threads} --outFileNamePrefix results/star/ && cp results/star/Aligned.out.sam {output.sam:q}",
        _fastq_input("reads"),
        [_output("sam", "results/star/Aligned.out.sam", "alignment_sam", "text/plain")],
        resources={"star_index": _database_resource("custom")},
        threads=4,
        mem_mb=8192,
    ),
    _profile(
        "kallisto-quant",
        "kallisto",
        "kallisto quant -i {config.transcriptome_index:q} -o results/kallisto --single -l {params.fragment_length} -s {params.fragment_sd} {input.reads:q} && cp results/kallisto/abundance.tsv {output.abundance:q}",
        _fastq_input("reads"),
        [_output("abundance", "results/kallisto/abundance.tsv", "transcript_quantification", "text/tab-separated-values")],
        params={
            "fragment_length": {"type": "integer", "title": "Fragment length", "default": 200, "minimum": 1},
            "fragment_sd": {"type": "integer", "title": "Fragment length standard deviation", "default": 20, "minimum": 1},
        },
        resources={"transcriptome_index": _database_resource("custom")},
        threads=4,
        mem_mb=4096,
    ),
    _profile(
        "htseq-count",
        "htseq",
        "samtools view -bS {input.alignment:q} > results/htseq-input.bam && htseq-count {params.extra} results/htseq-input.bam {config.annotation_gtf:q} > {output.counts:q}",
        _sam_input(),
        [_output("counts", "results/htseq-counts.tsv", "gene_counts", "text/tab-separated-values")],
        params={"extra": {"type": "string", "title": "Extra HTSeq-count arguments", "default": "-f bam -r pos -s no"}},
        resources={"annotation_gtf": _database_resource("custom")},
        mem_mb=2048,
    ),
    _profile(
        "freebayes-call",
        "freebayes",
        "samtools view -bS {input.alignment:q} > results/freebayes-input.bam && freebayes -f {config.reference_fasta:q} results/freebayes-input.bam > {output.vcf:q}",
        _sam_input(),
        [_output("vcf", "results/freebayes.vcf", "variants_vcf", "text/plain")],
        resources={"reference_fasta": _database_resource("custom")},
        threads=2,
        mem_mb=4096,
    ),
    _profile(
        "vcftools-filter",
        "vcftools",
        "vcftools --vcf {input.vcf:q} --recode --recode-INFO-all --out results/vcftools-filtered {params.extra} && cp results/vcftools-filtered.recode.vcf {output.filtered_vcf:q}",
        _vcf_input(),
        [_output("filtered_vcf", "results/vcftools-filtered.recode.vcf", "variants_vcf", "text/plain")],
        params={"extra": {"type": "string", "title": "Extra VCFtools filter arguments", "default": ""}},
    ),
)
