"""Curated open-source Bio Tool Pack v1 profiles."""

from __future__ import annotations

from typing import Any

from .tool_profile_model import ToolProfile


_PACKAGE_LOCKS: dict[str, tuple[str, str]] = {
    "bedtools": ("bioconda", "2.31.1"),
    "bcftools": ("bioconda", "1.23.1"),
    "blast": ("bioconda", "2.17.0"),
    "bowtie2": ("bioconda", "2.5.5"),
    "bwa": ("bioconda", "0.7.19"),
    "centrifuge": ("bioconda", "1.0.4.2"),
    "checkm2": ("bioconda", "1.1.0"),
    "cutadapt": ("bioconda", "5.2"),
    "deeptools": ("bioconda", "3.5.6"),
    "diamond": ("bioconda", "2.2.1"),
    "eggnog-mapper": ("bioconda", "2.1.13"),
    "freebayes": ("bioconda", "1.3.10"),
    "gtdbtk": ("bioconda", "2.7.2"),
    "hisat2": ("bioconda", "2.2.2"),
    "hmmer": ("bioconda", "3.4"),
    "htseq": ("bioconda", "2.1.2"),
    "humann": ("bioconda", "3.9"),
    "interproscan": ("bioconda", "5.59_91.0"),
    "kaiju": ("bioconda", "1.10.1"),
    "kallisto": ("bioconda", "0.52.0"),
    "macs3": ("bioconda", "3.0.4"),
    "mash": ("bioconda", "2.3"),
    "metaphlan": ("bioconda", "4.2.4"),
    "minimap2": ("bioconda", "2.31"),
    "mmseqs2": ("bioconda", "18.8cc5c"),
    "picard": ("bioconda", "3.4.0"),
    "prokka": ("bioconda", "1.15.6"),
    "q2-feature-classifier": ("qiime2", "2024.10.0"),
    "quast": ("bioconda", "5.3.0"),
    "rgi": ("bioconda", "6.0.8"),
    "salmon": ("bioconda", "2.0.0"),
    "samtools": ("bioconda", "1.23.1"),
    "sourmash": ("bioconda", "4.9.4"),
    "spades": ("bioconda", "4.3.0"),
    "star": ("bioconda", "2.7.11b"),
    "subread": ("bioconda", "2.1.1"),
    "taxonkit": ("bioconda", "0.20.0"),
    "trimmomatic": ("bioconda", "0.40"),
    "vcftools": ("bioconda", "0.1.17"),
}

_DNA64 = "ACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGT"
_DNA64_ALT = "ACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGA"
_KALLISTO_READ = "TGGCATTTTTATTACACTCAGAAACAGAACTCGGGTAATTTTGACAGGTCACGCAGAGGCGCGCCCTCCTGAAGTGCGTGGACACTCGCTATGAATCTCT"
_FASTQ64 = f"@smoke\n{_DNA64}\n+\n{'F' * len(_DNA64)}\n"
_KALLISTO_FASTQ = f"@smoke\n{_KALLISTO_READ}\n+\n{'F' * len(_KALLISTO_READ)}\n"
_ASSEMBLY_FASTQ = (
    f"@smoke_1\n{_DNA64}\n+\n{'F' * len(_DNA64)}\n"
    f"@smoke_2\n{_DNA64_ALT}\n+\n{'F' * len(_DNA64_ALT)}\n"
    f"@smoke_3\n{_DNA64}\n+\n{'F' * len(_DNA64)}\n"
)
_FASTA_MULTI = f">smoke\n{_DNA64}\n>smoke_alt\n{_DNA64_ALT}\n"
_ORF_CONTIG = ">orf_contig\n" + "ATG" + ("AAA" * 200) + "TAA" + "\n"
_PROTEIN_FASTA = ">protein\nMKKLLPTAAGLLLLAAQPAMA\n"
_INTERPROSCAN_PFAM_FASTA = (
    ">UPI00043D6473 tr|A0A0E0LFU2|A0A0E0LFU2_ORYPU Uncharacterized protein OS=Oryza punctata PE=3 SV=1\n"
    "MAPPCSASHLLITASLPKPTSSSLRPPRLPHHKTPLPAVLLALAAAPTLP\n"
    "ALADAPAPSPPPAPTQDVQVLEAPSPAANPFSNALLTAPKPTSSDLPDGA\n"
    "QWRYSEFLNAVKKGKVERVRFSKDGGLLQLTAIDGRRATVVVPNDPDLID\n"
    "ILATNGVDISVAEGDAAGPGGFLAFVGNLLFPFLAFAGLFFLFRRAQGGP\n"
    "GAGPGGLGGPMDFGRSKSKFQEVPETGVTFVDVAGADQAKLELQEVVDFL\n"
    "KNPDKYTALGAKIPKGCLLVGPPGTGKTLLARAVAGEAGVPFFSCAASEF\n"
    "VELFVGVGASRVRDLFEKAKAKAPCIVFIDEIDAVGRQRGAGLGGGNDER\n"
    "EQTINQLLTEMDGFAGNSGVIVLAATNRPDVLDAALLRPGRFDRQVTVDR\n"
    "PDVAGRVKILEVHSRGKALAKDVDFEKIARRTPGFTGADLQNLMNEAAIL\n"
    "AARRDLKEISKDEISDALERIIAGPEKKNAVVSEEKKRLVAYHEAGHALV\n"
    "GALMPEYDPVAKISIIPRGQAGGLTFFAPSEERLESGLYSRSYLENQMAV\n"
    "ALGGRVAEEVIFGQENVTTGASNDFMQVSRVARQMVERFGFSKKIGQIAI\n"
    "GGPGGNPFLGQQMSSQKDYSMATADVVDAEVRELVEKAYSRATQIITTHI\n"
    "DILHKLAQLLMEKETVDGEEFMSLFIDGQAELFPTSSDLPDGAQWRYSEF\n"
    "LNAVKKGKVERVRFSKDGGLLQLTAIDGRRATVVEVPETGVTFVDVAGAD\n"
    "QAKLELQEVVDFLKNPDKYTALGAKIPKGCLLVGPPGTGKTLLARALFVG\n"
    "VGASRVRDLFEKAKAKAPCIVFIDEIDAVGRQRGAGLGGGNDEREQTINQ\n"
    "LLTEMDGFAGNSGVIVLAATNRPDVLDAALLRPGRFDRQVTVDRPDVAGR\n"
    "VKILEVHSRGKALAKDVDFEKIARRTPGFTGADLQNLMNEAAILAARRDL\n"
    "KEISKDEISDALERIIAGPEKKNAVVSEEKKRLVAYHEAGHALVGALMPE\n"
    "YDPVAKISIIPRGQAGGLTFFAPSEERLESGLYSRSYLENQMAVALGGRV\n"
    "AEEVIFGQENVTTGASNDFMQVSRVARQMVERFGFSKKIGQIAIGGPGGN\n"
    "PFLGQQMSSQKDYSMATADVVDAEVRELVEKAYSRATQIITTHIDILHKL\n"
    "AQLLMEKETVDGEEFMSLFIDGQAELFVA\n"
)
_CHECKM2_POSITIVE_CONTIG = (
    ">checkm2_positive_from_uniref100_q6gzs4\n"
    "ATGGTTAAATATGTTGTTACTGGTGGTTGTGGTTTTCTGGGTTCTCATATTGTTAAATGTATTCTGAAATATGCTCCTGA\n"
    "AGTTACTGAAGTTGTTGCTTATGATATTAATATTTCTCATATTATGACTATGTGGTCTTCTAAACTGAAAGTTGTTCGTG\n"
    "GTGATGTTATGGATGTTATGGCTCTGGCTAAAGCTGTTGATGGTGCTGATGTTGTTATTCATACTGCTGGTATTGTTGAT\n"
    "GTTTGGTATCGTCATACTGATGATGAAATTTATCGTGTTAATGTTTCTGGTACTAAAAATGTTCTGATGTGTTGTATTAA\n"
    "TGCTGGTGTTCAAGTTCTGGTTAATACTTCTTCTATGGAAGTTGTTGGTCCTAATACTACTTCTGGTGTTTTTGTTCGTG\n"
    "GTGGTGAACGTACTCCTTATAATACTGTTCATGATCATGTTTATCCTCTGTCTAAAGATCGTGCTGAAAAACTGGTTAAA\n"
    "CATTATACTGGTGTTGCTGCTGCTCCTGGTATGCCTGCTCTGAAAACTTGTTCTCTGCGTCCTACTGGTATTTATGGTGA\n"
    "AGGTTGTGATCTGCTGGAAAAATTTTTTCATGATACTGTTAATGCTGGTAATGTTGCTTATGGTGGTTCTCCTCCTGATT\n"
    "CTGAACATGGTCGTGTTTATGTTGGTAATGTTGCTTGGATGCATCTGCTGGCTGCTCGTGCTCTGCTGGCTGGTGGTGAA\n"
    "TCTGCTCATAAAGTTAATGGTGAAGCTTTTTTTTGTTATGATGATTCTCCTTATATGTCTTATGATGCTTTTAATGCTGA\n"
    "ACTGTTTGAAGATCGTGGTTTTGGTTATGTTTATGTTCCTTATTGGGTTATGAAACCTATGGCTGCTTATAATGATCTGA\n"
    "AACGTAAATTTCTGGGTTGTTTTGGTGTTAAACGTTCTCCTATTCTGAATTCTTATACTCTGGCTCTGGCTCGTACTTCT\n"
    "TTTACTGTTAAAACTTCTAAAGCTCGTCGTATGTTTGGTTATATGCCTCTGTATGAATGGTCTGAAGCTAAACGTCGTAC\n"
    "TAAAGATTGGATTTCTACTCTGAAATAA\n"
)
_SAM64 = (
    "@HD\tVN:1.6\tSO:coordinate\n"
    "@SQ\tSN:chr1\tLN:64\n"
    f"smoke\t0\tchr1\t1\t60\t64M\t*\t0\t0\t{_DNA64}\t{'F' * len(_DNA64)}\n"
)
_PEAK_SAM = (
    "@HD\tVN:1.6\tSO:coordinate\n"
    "@SQ\tSN:chr1\tLN:256\n"
    + "".join(
        f"peak_{index}\t0\tchr1\t{index + 1}\t60\t64M\t*\t0\t0\t{_DNA64}\t{'F' * len(_DNA64)}\n"
        for index in range(20)
    )
)
_VCF_MINIMAL = (
    "##fileformat=VCFv4.2\n"
    "##contig=<ID=chr1,length=64>\n"
    "##INFO=<ID=DP,Number=1,Type=Integer,Description=\"Read depth\">\n"
    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
    "chr1\t2\t.\tC\tT\t60\tPASS\tDP=8\n"
)


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
    env_dependencies: list[str] | None = None,
    threads: int = 1,
    mem_mb: int = 1024,
) -> ToolProfile:
    package_source, package_version = _PACKAGE_LOCKS[package_name]
    return ToolProfile(
        profile_id=profile_id,
        version=1,
        tool_names=tool_names or (package_name,),
        package_name=package_name,
        package_source=package_source,
        package_version=package_version,
        rule_template={
            "commandTemplate": command,
            "inputs": [_rule_input(item) for item in inputs],
            "outputs": outputs,
            "params": params or {},
            "resources": {"threads": {"default": threads}, "mem_mb": {"default": mem_mb}, **(resources or {})},
            "environment": {
                "conda": {
                    "channels": _conda_channels(package_source),
                    "dependencies": env_dependencies or ["{packageSpec}"],
                }
            },
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
    return [_input(name, "sequence_reads", "text/plain", filename=f"{name}.fastq", content=_FASTQ64)]


def _kallisto_fastq_input(name: str) -> list[dict[str, Any]]:
    return [_input(name, "sequence_reads", "text/plain", filename=f"{name}.fastq", content=_KALLISTO_FASTQ)]


def _fasta_input(name: str) -> list[dict[str, Any]]:
    return [_input(name, "sequence_reads", "text/plain", filename=f"{name}.fasta", content=_FASTA_MULTI)]


def _protein_input(name: str) -> list[dict[str, Any]]:
    return [_input(name, "protein_sequence", "text/plain", filename=f"{name}.faa", content=_PROTEIN_FASTA)]


def _interproscan_pfam_input(name: str) -> list[dict[str, Any]]:
    return [_input(name, "protein_sequence", "text/plain", filename=f"{name}.faa", content=_INTERPROSCAN_PFAM_FASTA)]


def _orf_contig_input(name: str) -> list[dict[str, Any]]:
    return [_input(name, "assembly_contigs", "text/plain", filename=f"{name}.fasta", content=_ORF_CONTIG)]


def _checkm2_positive_contig_input(name: str) -> list[dict[str, Any]]:
    return [_input(name, "assembly_contigs", "text/plain", filename=f"{name}.fasta", content=_CHECKM2_POSITIVE_CONTIG)]


def _assembly_reads_input(name: str) -> list[dict[str, Any]]:
    return [_input(name, "sequence_reads", "text/plain", filename=f"{name}.fastq", content=_ASSEMBLY_FASTQ)]


def _amplicon_fasta_input(name: str) -> list[dict[str, Any]]:
    return [_input(name, "amplicon_sequences", "text/plain", filename=f"{name}.fasta", content=_FASTA_MULTI)]


def _sam_input(name: str = "alignment") -> list[dict[str, Any]]:
    return [
        _input(
            name,
            "alignment_sam",
            "text/plain",
            filename=f"{name}.sam",
            content=_SAM64,
        )
    ]


def _peak_sam_input(name: str = "alignment") -> list[dict[str, Any]]:
    return [
        _input(
            name,
            "alignment_sam",
            "text/plain",
            filename=f"{name}.sam",
            content=_PEAK_SAM,
        )
    ]


def _vcf_input(name: str = "vcf") -> list[dict[str, Any]]:
    return [
        _input(
            name,
            "variants_vcf",
            "text/plain",
            filename=f"{name}.vcf",
            content=_VCF_MINIMAL,
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


def _conda_channels(package_source: str) -> list[str]:
    if package_source == "qiime2":
        return ["qiime2", "conda-forge", "bioconda"]
    return ["conda-forge", "bioconda"]


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
        "java -jar \"$CONDA_PREFIX/share/trimmomatic/trimmomatic.jar\" SE -threads {threads} -phred33 {input.reads:q} {output.trimmed:q} MINLEN:1",
        _fastq_input("reads"),
        [_output("trimmed", "results/trimmomatic-trimmed.fastq", "sequence_reads", "text/plain")],
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
        resources={"reference_fasta": _database_resource("minimap2")},
        threads=4,
        mem_mb=4096,
    ),
    _profile(
        "deeptools-bamcoverage",
        "deeptools",
        "samtools view -bS {input.alignment:q} | samtools sort -o deeptools-input.bam && samtools index deeptools-input.bam && bamCoverage -b deeptools-input.bam -o {output.bigwig:q} --numberOfProcessors {threads}",
        _sam_input(),
        [_output("bigwig", "results/coverage.bw", "coverage_bigwig", "application/octet-stream")],
        threads=2,
    ),
    _profile(
        "bedtools-bamtobed",
        "bedtools",
        "samtools view -bS {input.alignment:q} > bedtools-input.bam && bedtools bamtobed -i bedtools-input.bam > {output.bed:q}",
        _sam_input(),
        [_output("bed", "results/alignments.bed", "intervals_bed", "text/plain")],
    ),
    _profile(
        "bcftools-stats",
        "bcftools",
        "bcftools stats {input.vcf:q} > {output.stats:q}",
        _vcf_input(),
        [_output("stats", "results/bcftools-stats.txt", "variant_stats", "text/plain")],
    ),
    _profile(
        "mash-sketch",
        "mash",
        "mash sketch -o mash {input.fastx:q} && cp mash.msh {output.sketch:q}",
        _fastq_input("fastx"),
        [_output("sketch", "results/mash.msh", "sequence_sketch", "application/octet-stream")],
    ),
    _profile(
        "spades-assembly",
        "spades",
        "spades.py --only-assembler -s {input.reads:q} -o spades-output -t {threads} -k 21,33 && cp spades-output/contigs.fasta {output.contigs:q}",
        _assembly_reads_input("reads"),
        [_output("contigs", "results/spades-contigs.fasta", "assembly_contigs", "text/plain")],
        threads=4,
        mem_mb=8192,
    ),
    _profile(
        "quast-report",
        "quast",
        "quast.py {input.contigs:q} -o quast-output --threads {threads} && cp quast-output/report.html {output.html:q}",
        _orf_contig_input("contigs"),
        [_output("html", "results/quast-report.html", "report", "text/html")],
        threads=2,
    ),
    _profile(
        "prokka-annotation",
        "prokka",
        "prokka --outdir prokka-output --prefix sample {input.contigs:q} && cp prokka-output/sample.gff {output.gff:q}",
        _orf_contig_input("contigs"),
        [_output("gff", "results/prokka.gff", "annotation_gff", "text/plain")],
        threads=2,
        mem_mb=4096,
    ),
    _profile(
        "macs2-callpeak",
        "macs3",
        "samtools view -bS {input.alignment:q} > macs-input.bam && macs3 callpeak -t macs-input.bam -f BAM -n sample --outdir macs-output --nomodel --extsize 64 --keep-dup all -g 256 -p 1.0 && cp macs-output/sample_peaks.narrowPeak {output.peaks:q}",
        _peak_sam_input(),
        [_output("peaks", "results/macs2-peaks.narrowPeak", "peaks_narrowpeak", "text/plain")],
        tool_names=("macs2-callpeak", "macs3 callpeak", "macs2"),
    ),
    _profile(
        "featurecounts",
        "subread",
        "samtools view -bS {input.alignment:q} > featurecounts-input.bam && featureCounts -T {threads} -a {config.annotation_gtf:q} -o {output.counts:q} featurecounts-input.bam",
        _sam_input(),
        [_output("counts", "results/featurecounts.txt", "gene_counts", "text/plain")],
        tool_names=("subread", "featureCounts"),
        resources={"annotation_gtf": _database_resource("annotation_gtf")},
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
        "samtools view -bS {input.alignment:q} > picard-input.bam && picard MarkDuplicates I=picard-input.bam O={output.dedup_bam:q} M={output.metrics:q} VALIDATION_STRINGENCY=SILENT",
        _sam_input(),
        [
            _output("dedup_bam", "results/picard-dedup.bam", "alignment_bam", "application/octet-stream"),
            _output("metrics", "results/picard-markduplicates-metrics.txt", "report", "text/plain"),
        ],
        tool_names=("picard-markduplicates", "picard MarkDuplicates"),
        mem_mb=2048,
    ),
    _profile(
        "blastn-search",
        "blast",
        "blastn -task blastn-short -dust no -word_size 7 -query {input.query:q} -db {config.blast_db:q} -out {output.hits:q} -outfmt 6",
        _fasta_input("query"),
        [_output("hits", "results/blastn-hits.tsv", "tabular_hits", "text/tab-separated-values")],
        tool_names=("blastn-search", "blastn"),
        resources={"blast_db": _database_resource("blast")},
        threads=2,
        mem_mb=2048,
    ),
    _profile(
        "salmon-quant",
        "salmon",
        "salmon quant -i {config.transcriptome_index:q} -l A -r {input.reads:q} -p {threads} -o salmon-output && cp salmon-output/quant.sf {output.quant:q}",
        _fastq_input("reads"),
        [_output("quant", "results/salmon-quant.sf", "transcript_quantification", "text/tab-separated-values")],
        tool_names=("salmon-quant", "salmon quant"),
        resources={"transcriptome_index": _database_resource("salmon")},
        threads=4,
        mem_mb=4096,
    ),
    _profile(
        "hisat2-align",
        "hisat2",
        "hisat2 -x {config.hisat2_index:q} -U {input.reads:q} -S {output.sam:q} -p {threads}",
        _fastq_input("reads"),
        [_output("sam", "results/hisat2.sam", "alignment_sam", "text/plain")],
        resources={"hisat2_index": _database_resource("hisat2")},
        threads=4,
        mem_mb=4096,
    ),
    _profile(
        "star-align",
        "star",
        "mkdir -p star-output && STAR --genomeDir {config.star_index:q} --readFilesIn {input.reads:q} --runThreadN {threads} --outFileNamePrefix star-output/ && cp star-output/Aligned.out.sam {output.sam:q}",
        _fastq_input("reads"),
        [_output("sam", "results/star-aligned.sam", "alignment_sam", "text/plain")],
        resources={"star_index": _database_resource("star")},
        threads=4,
        mem_mb=8192,
    ),
    _profile(
        "kallisto-quant",
        "kallisto",
        "kallisto quant -i {config.transcriptome_index:q} -o kallisto-output --single -l {params.fragment_length} -s {params.fragment_sd} {input.reads:q} && cp kallisto-output/abundance.tsv {output.abundance:q}",
        _kallisto_fastq_input("reads"),
        [_output("abundance", "results/kallisto-abundance.tsv", "transcript_quantification", "text/tab-separated-values")],
        params={
            "fragment_length": {"type": "integer", "title": "Fragment length", "default": 100, "minimum": 1},
            "fragment_sd": {"type": "integer", "title": "Fragment length standard deviation", "default": 10, "minimum": 1},
        },
        resources={"transcriptome_index": _database_resource("kallisto")},
        threads=4,
        mem_mb=4096,
    ),
    _profile(
        "htseq-count",
        "htseq",
        "samtools view -bS {input.alignment:q} > htseq-input.bam && htseq-count -f bam -r pos -s no htseq-input.bam {config.annotation_gtf:q} > {output.counts:q}",
        _sam_input(),
        [_output("counts", "results/htseq-counts.tsv", "gene_counts", "text/tab-separated-values")],
        resources={"annotation_gtf": _database_resource("annotation_gtf")},
        mem_mb=2048,
    ),
    _profile(
        "freebayes-call",
        "freebayes",
        "cp {config.reference_fasta:q} freebayes-reference.fasta && samtools faidx freebayes-reference.fasta && samtools view -bS {input.alignment:q} | samtools sort -o freebayes-input.bam && samtools index freebayes-input.bam && freebayes -f freebayes-reference.fasta freebayes-input.bam > {output.vcf:q}",
        _sam_input(),
        [_output("vcf", "results/freebayes.vcf", "variants_vcf", "text/plain")],
        resources={"reference_fasta": _database_resource("reference_fasta")},
        threads=2,
        mem_mb=4096,
    ),
    _profile(
        "metaphlan-profile",
        "metaphlan",
        "metaphlan {input.reads:q} --input_type fastq --db_dir {config.metaphlan_db:q} --offline --read_min_len 50 --nproc {threads} -o {output.profile:q}",
        _fastq_input("reads"),
        [_output("profile", "results/metaphlan-profile.tsv", "taxonomy_profile", "text/tab-separated-values")],
        tool_names=("metaphlan", "metaphlan-profile"),
        resources={"metaphlan_db": _database_resource("metaphlan")},
        threads=4,
        mem_mb=4096,
    ),
    _profile(
        "centrifuge-classify",
        "centrifuge",
        "centrifuge -x {config.centrifuge_index:q} -U {input.reads:q} -S {output.classification:q} --report-file {output.report:q} -p {threads}",
        _fastq_input("reads"),
        [
            _output("classification", "results/centrifuge-classification.tsv", "taxonomy_classification", "text/tab-separated-values"),
            _output("report", "results/centrifuge-report.tsv", "taxonomy_report", "text/tab-separated-values"),
        ],
        resources={"centrifuge_index": _database_resource("centrifuge")},
        threads=4,
        mem_mb=4096,
    ),
    _profile(
        "kaiju-classify",
        "kaiju",
        "kaiju -t {config.kaiju_db:q}/nodes.dmp -f {config.kaiju_db:q}/proteins.fmi -i {input.reads:q} -o {output.matches:q} -z {threads}",
        _fastq_input("reads"),
        [_output("matches", "results/kaiju-matches.tsv", "taxonomy_classification", "text/tab-separated-values")],
        resources={"kaiju_db": _database_resource("kaiju")},
        threads=4,
        mem_mb=4096,
    ),
    _profile(
        "rgi-main",
        "rgi",
        "rgi load -i {config.card_db.card_json:q} --local && rgi main --input_sequence {input.contigs:q} --output_file rgi-output --local --clean && cp rgi-output.txt {output.report:q}",
        _orf_contig_input("contigs"),
        [_output("report", "results/rgi-report.txt", "amr_report", "text/plain")],
        tool_names=("rgi", "rgi-main"),
        resources={"card_db": _database_resource("card_rgi")},
        threads=2,
        mem_mb=4096,
    ),
    _profile(
        "diamond-blastp",
        "diamond",
        "diamond blastp --db {config.diamond_db:q} --query {input.query:q} --out {output.hits:q} --outfmt 6 --threads {threads}",
        _protein_input("query"),
        [_output("hits", "results/diamond-hits.tsv", "tabular_hits", "text/tab-separated-values")],
        resources={"diamond_db": _database_resource("diamond")},
        threads=4,
        mem_mb=4096,
    ),
    _profile(
        "humann-profile",
        "humann",
        "humann --input {input.reads:q} --output humann-output --nucleotide-database {config.humann_db.nucleotide:q} --protein-database {config.humann_db.protein:q} --bypass-prescreen --threads {threads} && cp humann-output/*_genefamilies.tsv {output.genefamilies:q}",
        _fastq_input("reads"),
        [_output("genefamilies", "results/humann-genefamilies.tsv", "functional_profile", "text/tab-separated-values")],
        resources={"humann_db": _database_resource("humann")},
        env_dependencies=["{packageSpec}", "conda-forge::python=3.12"],
        threads=4,
        mem_mb=8192,
    ),
    _profile(
        "gtdbtk-classify",
        "gtdbtk",
        "export GTDBTK_DATA_PATH={config.gtdbtk_db:q} && gtdbtk check_install && mkdir -p gtdbtk-genomes && cp {input.genome:q} gtdbtk-genomes/genome.fna && gtdbtk classify_wf --genome_dir gtdbtk-genomes --out_dir gtdbtk-output --cpus {threads} && summary=$(find gtdbtk-output -name '*summary.tsv' -type f | head -n 1) && test -n \"$summary\" && cp \"$summary\" {output.summary:q}",
        _orf_contig_input("genome"),
        [_output("summary", "results/gtdbtk-summary.tsv", "taxonomy_report", "text/tab-separated-values")],
        tool_names=("gtdbtk", "gtdbtk-classify"),
        resources={"gtdbtk_db": _database_resource("gtdbtk")},
        threads=4,
        mem_mb=8192,
    ),
    _profile(
        "sourmash-gather",
        "sourmash",
        "sourmash sketch dna -p k=21,scaled=1 -o sourmash-query.sig {input.query:q} && sourmash gather sourmash-query.sig {config.sourmash_db:q} --threshold-bp 1 -o {output.matches:q}",
        _fasta_input("query"),
        [_output("matches", "results/sourmash-gather.csv", "sequence_search_results", "text/csv")],
        resources={"sourmash_db": _database_resource("sourmash")},
        mem_mb=2048,
    ),
    _profile(
        "mmseqs-easy-search",
        "mmseqs2",
        "mmseqs easy-search {input.query:q} {config.mmseqs_db:q} {output.hits:q} mmseqs-tmp --threads {threads}",
        _protein_input("query"),
        [_output("hits", "results/mmseqs-hits.tsv", "tabular_hits", "text/tab-separated-values")],
        tool_names=("mmseqs", "mmseqs2", "mmseqs-easy-search"),
        resources={"mmseqs_db": _database_resource("mmseqs2")},
        threads=4,
        mem_mb=4096,
    ),
    _profile(
        "hmmscan-pfam",
        "hmmer",
        "hmmscan --cpu {threads} --tblout {output.tblout:q} {config.pfam_db:q} {input.proteins:q} > {output.report:q}",
        _protein_input("proteins"),
        [
            _output("tblout", "results/hmmscan.tblout", "profile_hmm_hits", "text/plain"),
            _output("report", "results/hmmscan-report.txt", "profile_hmm_report", "text/plain"),
        ],
        tool_names=("hmmscan", "hmmer", "hmmer-pfam"),
        resources={"pfam_db": _database_resource("hmmer_pfam")},
        threads=2,
        mem_mb=2048,
    ),
    _profile(
        "eggnog-mapper",
        "eggnog-mapper",
        "mkdir -p results/eggnog && emapper.py -i {input.proteins:q} --data_dir {config.eggnog_db.data_dir:q} -o eggnog --output_dir results/eggnog --cpu {threads} && cp results/eggnog/eggnog.emapper.annotations {output.annotations:q}",
        _protein_input("proteins"),
        [_output("annotations", "results/eggnog-annotations.tsv", "annotation_table", "text/tab-separated-values")],
        tool_names=("eggnog-mapper", "emapper"),
        resources={"eggnog_db": _database_resource("eggnog_mapper")},
        threads=4,
        mem_mb=8192,
    ),
    _profile(
        "interproscan",
        "interproscan",
        "mkdir -p results && data_dir={config.interproscan_data:q} && sed \"s#^data.directory=.*#data.directory=$data_dir#\" \"$CONDA_PREFIX/share/InterProScan/interproscan.properties\" > interproscan-smoke.properties && INTERPROSCAN_CONF=\"$PWD/interproscan-smoke.properties\" interproscan.sh -i {input.proteins:q} -o {output.tsv:q} -f TSV -appl Pfam -dp -cpu {threads}",
        _interproscan_pfam_input("proteins"),
        [_output("tsv", "results/interproscan.tsv", "annotation_table", "text/tab-separated-values")],
        resources={"interproscan_data": _database_resource("interproscan")},
        threads=2,
        mem_mb=4096,
    ),
    _profile(
        "qiime2-classify-sklearn",
        "q2-feature-classifier",
        "qiime tools import --type 'FeatureData[Sequence]' --input-path {input.rep_seqs:q} --input-format DNAFASTAFormat --output-path rep-seqs.qza && qiime feature-classifier classify-sklearn --i-classifier {config.silva_classifier:q} --i-reads rep-seqs.qza --o-classification {output.taxonomy:q}",
        _amplicon_fasta_input("rep_seqs"),
        [_output("taxonomy", "results/silva-taxonomy.qza", "taxonomy_classification", "application/x-qza")],
        tool_names=("qiime2-classify-sklearn", "q2-feature-classifier"),
        resources={"silva_classifier": _database_resource("silva_qiime")},
        env_dependencies=[
            "{packageSpec}",
            "qiime2::qiime2=2024.10.0",
            "qiime2::q2cli=2024.10.0",
            "conda-forge::click=8.1.7",
            "conda-forge::setuptools=80.9.0",
        ],
        mem_mb=4096,
    ),
    _profile(
        "checkm2-predict",
        "checkm2",
        "mkdir -p checkm2-genomes && cp {input.genome:q} checkm2-genomes/genome.fna && checkm2 predict --threads {threads} --database_path {config.checkm_db:q} --input checkm2-genomes --output-directory checkm2-output && cp checkm2-output/quality_report.tsv {output.report:q}",
        _checkm2_positive_contig_input("genome"),
        [_output("report", "results/checkm2-quality-report.tsv", "quality_report", "text/tab-separated-values")],
        tool_names=("checkm2", "checkm2-predict"),
        resources={"checkm_db": _database_resource("checkm")},
        threads=4,
        mem_mb=8192,
    ),
    _profile(
        "taxonkit-lineage",
        "taxonkit",
        "taxonkit --data-dir {config.ncbi_taxonomy:q} lineage {input.taxids:q} > {output.lineage:q}",
        [_input("taxids", "taxonomy_ids", "text/plain", filename="taxids.txt", content="562\n")],
        [_output("lineage", "results/taxonkit-lineage.tsv", "taxonomy_lineage", "text/tab-separated-values")],
        tool_names=("taxonkit", "taxonkit-lineage"),
        resources={"ncbi_taxonomy": _database_resource("ncbi_taxonomy")},
        mem_mb=1024,
    ),
    _profile(
        "vcftools-filter",
        "vcftools",
        "vcftools --vcf {input.vcf:q} --recode --recode-INFO-all --out vcftools-filtered && cp vcftools-filtered.recode.vcf {output.filtered_vcf:q}",
        _vcf_input(),
        [_output("filtered_vcf", "results/vcftools-filtered.vcf", "variants_vcf", "text/plain")],
    ),
)
