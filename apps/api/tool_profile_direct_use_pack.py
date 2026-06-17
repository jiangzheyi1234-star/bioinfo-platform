"""Additional direct-use Bio Tool Pack v1 profiles."""

from __future__ import annotations

from typing import Any

from .tool_profile_direct_use_extra_pack import extra_direct_use_tool_profiles
from .tool_profile_model import ToolProfile


_FIXTURES: dict[str, dict[str, str]] = {
    "fastq": {
        "kind": "sequence_reads",
        "mimeType": "text/plain",
        "filename": "reads.fastq",
        "content": (
            "@smoke\n"
            "ACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGT\n"
            "+\n"
            "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF\n"
        ),
    },
    "fasta": {
        "kind": "sequence_reads",
        "mimeType": "text/plain",
        "filename": "sequences.fasta",
        "content": (
            ">smoke\n"
            "ACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGT\n"
            ">smoke_alt\n"
            "ACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGA\n"
        ),
    },
    "reference": {
        "kind": "reference_fasta",
        "mimeType": "text/plain",
        "filename": "reference.fasta",
        "content": (
            ">chr1\n"
            "ACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGT\n"
        ),
    },
    "protein": {
        "kind": "protein_sequence",
        "mimeType": "text/plain",
        "filename": "proteins.faa",
        "content": ">protein1\nMKKLLPTAA\n",
    },
    "alignment": {
        "kind": "multiple_sequence_alignment",
        "mimeType": "text/plain",
        "filename": "alignment.faa",
        "content": ">protein1\nMKKLLPTAA\n>protein2\nMKKLLPTAT\n",
    },
    "orf_contigs": {
        "kind": "assembly_contigs",
        "mimeType": "text/plain",
        "filename": "contigs.fasta",
        "content": ">orf_contig\n" + "ATG" + ("AAA" * 100) + "TAA" + "\n",
    },
    "trna_contigs": {
        "kind": "assembly_contigs",
        "mimeType": "text/plain",
        "filename": "trna.fasta",
        "content": (
            ">trna_candidate\n"
            "GGGGCTATAGCTCAGCTGGGAGAGCGCCTGCTTTGCACGCAGGAGGTCTGCGGTTCGATCCCGC"
            "ATAGCTCCA\n"
        ),
    },
    "sam": {
        "kind": "alignment_sam",
        "mimeType": "text/plain",
        "filename": "alignment.sam",
        "content": (
            "@HD\tVN:1.6\tSO:unsorted\n"
            "@SQ\tSN:chr1\tLN:16\n"
            "smoke\t0\tchr1\t1\t60\t8M\t*\t0\t0\tACGTACGT\tFFFFFFFF\n"
        ),
    },
    "vcf": {
        "kind": "variants_vcf",
        "mimeType": "text/plain",
        "filename": "variants.vcf",
        "content": (
            "##fileformat=VCFv4.2\n"
            "##contig=<ID=chr1,length=64>\n"
            "##INFO=<ID=DP,Number=1,Type=Integer,Description=\"Read depth\">\n"
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
            "chr1\t2\t.\tC\tT\t60\tPASS\tDP=8\n"
        ),
    },
    "bed": {
        "kind": "intervals_bed",
        "mimeType": "text/plain",
        "filename": "regions.bed",
        "content": "chr1\t0\t4\tregion_a\t1\nchr1\t4\t8\tregion_b\t2\n",
    },
    "bed_b": {
        "kind": "intervals_bed",
        "mimeType": "text/plain",
        "filename": "regions_b.bed",
        "content": "chr1\t2\t6\tregion_c\t3\n",
    },
    "genome": {
        "kind": "genome_file",
        "mimeType": "text/plain",
        "filename": "genome.txt",
        "content": "chr1\t16\n",
    },
    "ids": {
        "kind": "identifier_list",
        "mimeType": "text/plain",
        "filename": "ids.txt",
        "content": "smoke\n",
    },
    "table": {
        "kind": "tabular_data",
        "mimeType": "text/tab-separated-values",
        "filename": "table.tsv",
        "content": "sample\tgroup\tvalue\ns1\tcase\t2\ns2\tcontrol\t1\n",
    },
    "table_b": {
        "kind": "tabular_data",
        "mimeType": "text/tab-separated-values",
        "filename": "table_b.tsv",
        "content": "sample\tbatch\ns1\tA\ns2\tB\n",
    },
    "tab2fx": {
        "kind": "tabular_sequence",
        "mimeType": "text/tab-separated-values",
        "filename": "sequences.tsv",
        "content": "smoke\tACGTACGT\n",
    },
}


_PACKAGE_VERSIONS: dict[str, str] = {
    "barrnap": "1.10.6",
    "bcftools": "1.23.1",
    "bedtools": "2.31.1",
    "bowtie2": "2.5.5",
    "bwa": "0.7.19",
    "cd-hit": "4.8.1",
    "clustalo": "1.2.4",
    "csvtk": "0.31.0",
    "emboss": "6.6.0",
    "hmmer": "3.4",
    "mafft": "7.525",
    "mash": "2.3",
    "minimap2": "2.31",
    "muscle": "5.3",
    "prodigal": "2.6.3",
    "samtools": "1.23.1",
    "seqkit": "2.13.0",
    "seqmagick": "0.8.6",
    "seqtk": "1.5",
    "sourmash": "4.9.4",
    "trnascan-se": "2.0.12",
    "vsearch": "2.31.0",
}


_PACKAGE_SOURCES: dict[str, str] = {
    "csvtk": "conda-forge",
    "mafft": "conda-forge",
}


def _profile(
    profile_id: str,
    package_name: str,
    command: str,
    inputs: list[dict[str, Any]],
    outputs: list[dict[str, Any]],
    *,
    threads: int = 1,
    mem_mb: int = 512,
    params: dict[str, Any] | None = None,
) -> ToolProfile:
    return ToolProfile(
        profile_id=profile_id,
        version=1,
        tool_names=(profile_id,),
        package_name=package_name,
        package_source=_PACKAGE_SOURCES.get(package_name, "bioconda"),
        package_version=_PACKAGE_VERSIONS[package_name],
        rule_template={
            "commandTemplate": command,
            "inputs": [_rule_input(item) for item in inputs],
            "outputs": outputs,
            "params": params or {},
            "resources": {
                "threads": {"default": threads},
                "mem_mb": {"default": mem_mb},
            },
            "environment": {
                "conda": {
                    "channels": ["conda-forge", "bioconda"],
                    "dependencies": ["{packageSpec}"],
                }
            },
            "log": f"logs/{profile_id}.log",
            "smokeTest": {
                "inputs": {
                    item["name"]: {
                        "filename": item["filename"],
                        "content": item["content"],
                        "mimeType": item["mimeType"],
                    }
                    for item in inputs
                },
                "timeoutSeconds": 300,
            },
        },
    )


def _input(name: str, fixture: str) -> dict[str, Any]:
    item = dict(_FIXTURES[fixture])
    item.update({"name": name, "type": "file", "required": True})
    return item


def _inputs(*items: tuple[str, str]) -> list[dict[str, Any]]:
    return [_input(name, fixture) for name, fixture in items]


def _rule_input(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in item.items()
        if key not in {"filename", "content"} and value is not None
    }


def _output(
    name: str,
    path: str,
    kind: str,
    mime_type: str = "text/plain",
    *,
    directory: bool = False,
) -> dict[str, Any]:
    item = {"name": name, "path": path, "kind": kind, "mimeType": mime_type}
    if directory:
        item["directory"] = True
    return item


_CORE_DIRECT_USE_TOOL_PROFILES: tuple[ToolProfile, ...] = (
    _profile(
        "seqkit-grep",
        "seqkit",
        "seqkit grep -p smoke {input.reads:q} > {output.matches:q}",
        _inputs(("reads", "fastq")),
        [_output("matches", "results/seqkit-grep.fastq", "sequence_reads")],
    ),
    _profile(
        "seqkit-seq",
        "seqkit",
        "seqkit seq {input.reads:q} > {output.sequences:q}",
        _inputs(("reads", "fastq")),
        [_output("sequences", "results/seqkit-seq.fasta", "sequence_reads")],
    ),
    _profile(
        "seqkit-fx2tab",
        "seqkit",
        "seqkit fx2tab {input.sequences:q} > {output.table:q}",
        _inputs(("sequences", "fasta")),
        [
            _output(
                "table",
                "results/seqkit-fx2tab.tsv",
                "sequence_table",
                "text/tab-separated-values",
            )
        ],
    ),
    _profile(
        "seqkit-subseq",
        "seqkit",
        "seqkit subseq -r 1:12 {input.sequences:q} > {output.subset:q}",
        _inputs(("sequences", "fasta")),
        [_output("subset", "results/seqkit-subseq.fasta", "sequence_reads")],
    ),
    _profile(
        "seqkit-translate",
        "seqkit",
        "seqkit translate {input.sequences:q} > {output.proteins:q}",
        _inputs(("sequences", "fasta")),
        [_output("proteins", "results/seqkit-translate.faa", "protein_sequence")],
    ),
    _profile(
        "seqkit-rmdup",
        "seqkit",
        "seqkit rmdup {input.reads:q} > {output.deduplicated:q}",
        _inputs(("reads", "fastq")),
        [_output("deduplicated", "results/seqkit-rmdup.fastq", "sequence_reads")],
    ),
    _profile(
        "seqkit-locate",
        "seqkit",
        "seqkit locate -p ACGT {input.sequences:q} > {output.matches:q}",
        _inputs(("sequences", "fasta")),
        [
            _output(
                "matches",
                "results/seqkit-locate.tsv",
                "sequence_motif_hits",
                "text/tab-separated-values",
            )
        ],
    ),
    _profile(
        "seqkit-replace",
        "seqkit",
        "seqkit replace -p smoke -r sample {input.sequences:q} > {output.renamed:q}",
        _inputs(("sequences", "fasta")),
        [_output("renamed", "results/seqkit-replace.fasta", "sequence_reads")],
    ),
    _profile(
        "seqkit-sort",
        "seqkit",
        "seqkit sort {input.sequences:q} > {output.sorted:q}",
        _inputs(("sequences", "fasta")),
        [_output("sorted", "results/seqkit-sort.fasta", "sequence_reads")],
    ),
    _profile(
        "seqkit-sample",
        "seqkit",
        "seqkit sample -n 1 {input.reads:q} > {output.sample:q}",
        _inputs(("reads", "fastq")),
        [_output("sample", "results/seqkit-sample.fastq", "sequence_reads")],
    ),
    _profile(
        "seqkit-head",
        "seqkit",
        "seqkit head -n 1 {input.reads:q} > {output.head:q}",
        _inputs(("reads", "fastq")),
        [_output("head", "results/seqkit-head.fastq", "sequence_reads")],
    ),
    _profile(
        "seqkit-sana",
        "seqkit",
        "seqkit sana {input.reads:q} > {output.cleaned:q}",
        _inputs(("reads", "fastq")),
        [_output("cleaned", "results/seqkit-sana.fastq", "sequence_reads")],
    ),
    _profile(
        "seqkit-rename",
        "seqkit",
        "seqkit rename {input.sequences:q} > {output.renamed:q}",
        _inputs(("sequences", "fasta")),
        [_output("renamed", "results/seqkit-rename.fasta", "sequence_reads")],
    ),
    _profile(
        "seqkit-tab2fx",
        "seqkit",
        "seqkit tab2fx {input.table:q} > {output.sequences:q}",
        _inputs(("table", "tab2fx")),
        [_output("sequences", "results/seqkit-tab2fx.fasta", "sequence_reads")],
    ),
    _profile(
        "seqkit-sliding",
        "seqkit",
        "seqkit sliding -s 4 -W 4 {input.sequences:q} > {output.windows:q}",
        _inputs(("sequences", "fasta")),
        [_output("windows", "results/seqkit-sliding.fasta", "sequence_windows")],
    ),
    _profile(
        "seqtk-seq",
        "seqtk",
        "seqtk seq -A {input.reads:q} > {output.fasta:q}",
        _inputs(("reads", "fastq")),
        [_output("fasta", "results/seqtk-seq.fasta", "sequence_reads")],
    ),
    _profile(
        "seqtk-comp",
        "seqtk",
        "seqtk comp {input.sequences:q} > {output.composition:q}",
        _inputs(("sequences", "fasta")),
        [
            _output(
                "composition",
                "results/seqtk-comp.tsv",
                "sequence_composition",
                "text/tab-separated-values",
            )
        ],
    ),
    _profile(
        "seqtk-subseq",
        "seqtk",
        "seqtk subseq {input.sequences:q} {input.ids:q} > {output.subset:q}",
        _inputs(("sequences", "fasta"), ("ids", "ids")),
        [_output("subset", "results/seqtk-subseq.fasta", "sequence_reads")],
    ),
    _profile(
        "seqtk-sample",
        "seqtk",
        "seqtk sample -s11 {input.reads:q} 1 > {output.sample:q}",
        _inputs(("reads", "fastq")),
        [_output("sample", "results/seqtk-sample.fastq", "sequence_reads")],
    ),
    _profile(
        "seqtk-trimfq",
        "seqtk",
        "seqtk trimfq {input.reads:q} > {output.trimmed:q}",
        _inputs(("reads", "fastq")),
        [_output("trimmed", "results/seqtk-trimfq.fastq", "sequence_reads")],
    ),
    _profile(
        "seqtk-cutn",
        "seqtk",
        "seqtk cutN {input.sequences:q} > {output.fragments:q}",
        _inputs(("sequences", "fasta")),
        [_output("fragments", "results/seqtk-cutn.bed", "intervals_bed")],
    ),
    _profile(
        "seqtk-fqchk",
        "seqtk",
        "seqtk fqchk {input.reads:q} > {output.qc:q}",
        _inputs(("reads", "fastq")),
        [_output("qc", "results/seqtk-fqchk.txt", "quality_report")],
    ),
    _profile(
        "samtools-view",
        "samtools",
        "samtools view -bS {input.alignment:q} > {output.bam:q}",
        _inputs(("alignment", "sam")),
        [
            _output(
                "bam",
                "results/samtools-view.bam",
                "alignment_bam",
                "application/octet-stream",
            )
        ],
    ),
    _profile(
        "samtools-flagstat",
        "samtools",
        "samtools view -bS {input.alignment:q} > samtools-flagstat.bam && samtools flagstat samtools-flagstat.bam > {output.flagstat:q}",
        _inputs(("alignment", "sam")),
        [_output("flagstat", "results/samtools-flagstat.txt", "alignment_stats")],
    ),
    _profile(
        "samtools-stats",
        "samtools",
        "samtools view -bS {input.alignment:q} > samtools-stats.bam && samtools stats samtools-stats.bam > {output.stats:q}",
        _inputs(("alignment", "sam")),
        [_output("stats", "results/samtools-stats.txt", "alignment_stats")],
    ),
    _profile(
        "samtools-depth",
        "samtools",
        "samtools view -bS {input.alignment:q} > samtools-depth.bam && samtools depth samtools-depth.bam > {output.depth:q}",
        _inputs(("alignment", "sam")),
        [
            _output(
                "depth",
                "results/samtools-depth.tsv",
                "coverage_table",
                "text/tab-separated-values",
            )
        ],
    ),
    _profile(
        "samtools-coverage",
        "samtools",
        "samtools view -bS {input.alignment:q} > samtools-coverage.bam && samtools coverage samtools-coverage.bam > {output.coverage:q}",
        _inputs(("alignment", "sam")),
        [
            _output(
                "coverage",
                "results/samtools-coverage.tsv",
                "coverage_table",
                "text/tab-separated-values",
            )
        ],
    ),
    _profile(
        "samtools-faidx",
        "samtools",
        "cp {input.reference:q} samtools-faidx-reference.fasta && samtools faidx samtools-faidx-reference.fasta && cp samtools-faidx-reference.fasta.fai {output.index:q}",
        _inputs(("reference", "reference")),
        [_output("index", "results/reference.fasta.fai", "fasta_index")],
    ),
    _profile(
        "samtools-fastq",
        "samtools",
        "samtools view -bS {input.alignment:q} > samtools-fastq.bam && samtools fastq samtools-fastq.bam > {output.reads:q}",
        _inputs(("alignment", "sam")),
        [_output("reads", "results/samtools-fastq.fastq", "sequence_reads")],
    ),
    _profile(
        "samtools-index",
        "samtools",
        "samtools view -bS {input.alignment:q} | samtools sort -o samtools-index.bam && samtools index samtools-index.bam {output.index:q}",
        _inputs(("alignment", "sam")),
        [
            _output(
                "index",
                "results/samtools-index.bam.bai",
                "alignment_index",
                "application/octet-stream",
            )
        ],
    ),
    _profile(
        "samtools-fasta",
        "samtools",
        "samtools view -bS {input.alignment:q} > samtools-fasta.bam && samtools fasta samtools-fasta.bam > {output.fasta:q}",
        _inputs(("alignment", "sam")),
        [_output("fasta", "results/samtools-fasta.fasta", "sequence_reads")],
    ),
    _profile(
        "samtools-idxstats",
        "samtools",
        "samtools view -bS {input.alignment:q} | samtools sort -o samtools-idxstats.bam && samtools index samtools-idxstats.bam && samtools idxstats samtools-idxstats.bam > {output.idxstats:q}",
        _inputs(("alignment", "sam")),
        [
            _output(
                "idxstats",
                "results/samtools-idxstats.tsv",
                "alignment_stats",
                "text/tab-separated-values",
            )
        ],
    ),
    _profile(
        "bedtools-sort",
        "bedtools",
        "bedtools sort -i {input.regions:q} > {output.sorted:q}",
        _inputs(("regions", "bed")),
        [_output("sorted", "results/bedtools-sort.bed", "intervals_bed")],
    ),
    _profile(
        "bedtools-merge",
        "bedtools",
        "bedtools sort -i {input.regions:q} | bedtools merge -i - > {output.merged:q}",
        _inputs(("regions", "bed")),
        [_output("merged", "results/bedtools-merge.bed", "intervals_bed")],
    ),
    _profile(
        "bedtools-intersect",
        "bedtools",
        "bedtools intersect -a {input.a:q} -b {input.b:q} > {output.intersections:q}",
        _inputs(("a", "bed"), ("b", "bed_b")),
        [_output("intersections", "results/bedtools-intersect.bed", "intervals_bed")],
    ),
    _profile(
        "bedtools-coverage",
        "bedtools",
        "bedtools coverage -a {input.a:q} -b {input.b:q} > {output.coverage:q}",
        _inputs(("a", "bed"), ("b", "bed_b")),
        [
            _output(
                "coverage",
                "results/bedtools-coverage.tsv",
                "coverage_table",
                "text/tab-separated-values",
            )
        ],
    ),
    _profile(
        "bedtools-genomecov",
        "bedtools",
        "bedtools genomecov -i {input.regions:q} -g {input.genome:q} > {output.coverage:q}",
        _inputs(("regions", "bed"), ("genome", "genome")),
        [
            _output(
                "coverage", "results/bedtools-genomecov.bedgraph", "coverage_bedgraph"
            )
        ],
    ),
    _profile(
        "bedtools-getfasta",
        "bedtools",
        "bedtools getfasta -fi {input.reference:q} -bed {input.regions:q} -fo {output.sequences:q}",
        _inputs(("reference", "reference"), ("regions", "bed")),
        [_output("sequences", "results/bedtools-getfasta.fasta", "sequence_reads")],
    ),
    _profile(
        "bedtools-slop",
        "bedtools",
        "bedtools slop -i {input.regions:q} -g {input.genome:q} -b 1 > {output.slopped:q}",
        _inputs(("regions", "bed"), ("genome", "genome")),
        [_output("slopped", "results/bedtools-slop.bed", "intervals_bed")],
    ),
    _profile(
        "bedtools-complement",
        "bedtools",
        "bedtools complement -i {input.regions:q} -g {input.genome:q} > {output.complement:q}",
        _inputs(("regions", "bed"), ("genome", "genome")),
        [_output("complement", "results/bedtools-complement.bed", "intervals_bed")],
    ),
    _profile(
        "bedtools-window",
        "bedtools",
        "bedtools window -a {input.a:q} -b {input.b:q} -w 2 > {output.window:q}",
        _inputs(("a", "bed"), ("b", "bed_b")),
        [_output("window", "results/bedtools-window.bed", "intervals_bed")],
    ),
    _profile(
        "bedtools-map",
        "bedtools",
        "bedtools map -a {input.a:q} -b {input.b:q} -c 5 -o sum > {output.mapped:q}",
        _inputs(("a", "bed"), ("b", "bed_b")),
        [
            _output(
                "mapped",
                "results/bedtools-map.tsv",
                "interval_table",
                "text/tab-separated-values",
            )
        ],
    ),
    _profile(
        "bedtools-closest",
        "bedtools",
        "bedtools closest -a {input.a:q} -b {input.b:q} > {output.closest:q}",
        _inputs(("a", "bed"), ("b", "bed_b")),
        [_output("closest", "results/bedtools-closest.bed", "intervals_bed")],
    ),
    _profile(
        "bedtools-subtract",
        "bedtools",
        "bedtools subtract -a {input.a:q} -b {input.b:q} > {output.subtracted:q}",
        _inputs(("a", "bed"), ("b", "bed_b")),
        [_output("subtracted", "results/bedtools-subtract.bed", "intervals_bed")],
    ),
    _profile(
        "bcftools-view",
        "bcftools",
        "bcftools view {input.vcf:q} > {output.vcf:q}",
        _inputs(("vcf", "vcf")),
        [_output("vcf", "results/bcftools-view.vcf", "variants_vcf")],
    ),
    _profile(
        "bcftools-query",
        "bcftools",
        "bcftools query -f '%CHROM\\t%POS\\t%REF\\t%ALT\\n' {input.vcf:q} > {output.table:q}",
        _inputs(("vcf", "vcf")),
        [
            _output(
                "table",
                "results/bcftools-query.tsv",
                "variant_table",
                "text/tab-separated-values",
            )
        ],
    ),
    _profile(
        "bcftools-filter",
        "bcftools",
        "bcftools filter -i 'QUAL>=0' {input.vcf:q} > {output.filtered:q}",
        _inputs(("vcf", "vcf")),
        [_output("filtered", "results/bcftools-filter.vcf", "variants_vcf")],
    ),
    _profile(
        "bcftools-norm",
        "bcftools",
        "bcftools norm -m -any {input.vcf:q} > {output.normalized:q}",
        _inputs(("vcf", "vcf")),
        [_output("normalized", "results/bcftools-norm.vcf", "variants_vcf")],
    ),
    _profile(
        "bcftools-sort",
        "bcftools",
        "bcftools sort {input.vcf:q} -o {output.sorted:q}",
        _inputs(("vcf", "vcf")),
        [_output("sorted", "results/bcftools-sort.vcf", "variants_vcf")],
    ),
    _profile(
        "bcftools-annotate-remove",
        "bcftools",
        "bcftools annotate -x ID {input.vcf:q} > {output.annotated:q}",
        _inputs(("vcf", "vcf")),
        [_output("annotated", "results/bcftools-annotate.vcf", "variants_vcf")],
    ),
    _profile(
        "csvtk-cut",
        "csvtk",
        "csvtk cut -t -f sample,value {input.table:q} > {output.table:q}",
        _inputs(("table", "table")),
        [
            _output(
                "table",
                "results/csvtk-cut.tsv",
                "tabular_data",
                "text/tab-separated-values",
            )
        ],
    ),
    _profile(
        "csvtk-grep",
        "csvtk",
        "csvtk grep -t -f group -p case {input.table:q} > {output.table:q}",
        _inputs(("table", "table")),
        [
            _output(
                "table",
                "results/csvtk-grep.tsv",
                "tabular_data",
                "text/tab-separated-values",
            )
        ],
    ),
    _profile(
        "csvtk-sort",
        "csvtk",
        "csvtk sort -t -k value:n {input.table:q} > {output.table:q}",
        _inputs(("table", "table")),
        [
            _output(
                "table",
                "results/csvtk-sort.tsv",
                "tabular_data",
                "text/tab-separated-values",
            )
        ],
    ),
    _profile(
        "csvtk-join",
        "csvtk",
        "csvtk join -t -f sample {input.left:q} {input.right:q} > {output.table:q}",
        _inputs(("left", "table"), ("right", "table_b")),
        [
            _output(
                "table",
                "results/csvtk-join.tsv",
                "tabular_data",
                "text/tab-separated-values",
            )
        ],
    ),
    _profile(
        "csvtk-summary",
        "csvtk",
        "csvtk summary -t -f value:sum {input.table:q} > {output.summary:q}",
        _inputs(("table", "table")),
        [
            _output(
                "summary",
                "results/csvtk-summary.tsv",
                "tabular_summary",
                "text/tab-separated-values",
            )
        ],
    ),
    _profile(
        "csvtk-filter2",
        "csvtk",
        "csvtk filter2 -t -f '$value >= 1' {input.table:q} > {output.table:q}",
        _inputs(("table", "table")),
        [
            _output(
                "table",
                "results/csvtk-filter2.tsv",
                "tabular_data",
                "text/tab-separated-values",
            )
        ],
    ),
    _profile(
        "csvtk-freq",
        "csvtk",
        "csvtk freq -t -f group {input.table:q} > {output.frequency:q}",
        _inputs(("table", "table")),
        [
            _output(
                "frequency",
                "results/csvtk-freq.tsv",
                "tabular_summary",
                "text/tab-separated-values",
            )
        ],
    ),
)


DIRECT_USE_TOOL_PROFILES: tuple[ToolProfile, ...] = (
    *_CORE_DIRECT_USE_TOOL_PROFILES,
    *extra_direct_use_tool_profiles(_profile, _inputs, _output),
)
