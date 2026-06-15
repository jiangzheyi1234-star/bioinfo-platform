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
        resources={"reference_fasta": _database_resource("minimap2")},
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
        "STAR --genomeDir {config.star_index:q} --readFilesIn {input.reads:q} --runThreadN {threads} --outFileNamePrefix results/star/ && cp results/star/Aligned.out.sam {output.sam:q}",
        _fastq_input("reads"),
        [_output("sam", "results/star/Aligned.out.sam", "alignment_sam", "text/plain")],
        resources={"star_index": _database_resource("star")},
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
        resources={"transcriptome_index": _database_resource("kallisto")},
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
        "metaphlan-profile",
        "metaphlan",
        "metaphlan {input.reads:q} --input_type fastq --bowtie2db {config.metaphlan_db:q} --nproc {threads} -o {output.profile:q}",
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
        "rgi main --input_sequence {input.contigs:q} --output_file results/rgi --local --clean --card_json {config.card_db.card_json:q} && cp results/rgi.txt {output.report:q}",
        [_input("contigs", "assembly_contigs", "text/plain", filename="contigs.fasta", content=">contig1\nACGTACGT\n")],
        [_output("report", "results/rgi.txt", "amr_report", "text/plain")],
        tool_names=("rgi", "rgi-main"),
        resources={"card_db": _database_resource("card_rgi")},
        threads=2,
        mem_mb=4096,
    ),
    _profile(
        "diamond-blastp",
        "diamond",
        "diamond blastp --db {config.diamond_db:q} --query {input.query:q} --out {output.hits:q} --outfmt 6 --threads {threads}",
        _fasta_input("query"),
        [_output("hits", "results/diamond-hits.tsv", "tabular_hits", "text/tab-separated-values")],
        resources={"diamond_db": _database_resource("diamond")},
        threads=4,
        mem_mb=4096,
    ),
    _profile(
        "humann-profile",
        "humann",
        "humann --input {input.reads:q} --output results/humann --nucleotide-database {config.humann_db.nucleotide:q} --protein-database {config.humann_db.protein:q} --threads {threads} && cp results/humann/*_genefamilies.tsv {output.genefamilies:q}",
        _fastq_input("reads"),
        [_output("genefamilies", "results/humann-genefamilies.tsv", "functional_profile", "text/tab-separated-values")],
        resources={"humann_db": _database_resource("humann")},
        threads=4,
        mem_mb=8192,
    ),
    _profile(
        "gtdbtk-classify",
        "gtdbtk",
        "mkdir -p results/gtdbtk-genomes && cp {input.genome:q} results/gtdbtk-genomes/genome.fna && gtdbtk classify_wf --genome_dir results/gtdbtk-genomes --out_dir results/gtdbtk --cpus {threads} --data_path {config.gtdbtk_db:q} && touch {output.summary:q}",
        [_input("genome", "assembly_contigs", "text/plain", filename="genome.fna", content=">genome\nACGTACGT\n")],
        [_output("summary", "results/gtdbtk-summary.tsv", "taxonomy_report", "text/tab-separated-values")],
        tool_names=("gtdbtk", "gtdbtk-classify"),
        resources={"gtdbtk_db": _database_resource("gtdbtk")},
        threads=4,
        mem_mb=8192,
    ),
    _profile(
        "sourmash-gather",
        "sourmash",
        "sourmash gather {input.query:q} {config.sourmash_db:q} -o {output.matches:q}",
        _fasta_input("query"),
        [_output("matches", "results/sourmash-gather.csv", "sequence_search_results", "text/csv")],
        resources={"sourmash_db": _database_resource("sourmash")},
        mem_mb=2048,
    ),
    _profile(
        "mmseqs-easy-search",
        "mmseqs2",
        "mmseqs easy-search {input.query:q} {config.mmseqs_db:q} {output.hits:q} results/mmseqs-tmp --threads {threads}",
        _fasta_input("query"),
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
        [_input("proteins", "protein_sequence", "text/plain", filename="proteins.faa", content=">protein\nMKKLL\n")],
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
        "emapper.py -i {input.proteins:q} --data_dir {config.eggnog_db.data_dir:q} -o eggnog --output_dir results/eggnog --cpu {threads} && cp results/eggnog/eggnog.emapper.annotations {output.annotations:q}",
        [_input("proteins", "protein_sequence", "text/plain", filename="proteins.faa", content=">protein\nMKKLL\n")],
        [_output("annotations", "results/eggnog-annotations.tsv", "annotation_table", "text/tab-separated-values")],
        tool_names=("eggnog-mapper", "emapper"),
        resources={"eggnog_db": _database_resource("eggnog_mapper")},
        threads=4,
        mem_mb=8192,
    ),
    _profile(
        "interproscan",
        "interproscan",
        "INTERPROSCAN_DATA_DIR={config.interproscan_data:q} interproscan.sh -i {input.proteins:q} -d results/interproscan -f tsv && cp results/interproscan/*.tsv {output.tsv:q}",
        [_input("proteins", "protein_sequence", "text/plain", filename="proteins.faa", content=">protein\nMKKLL\n")],
        [_output("tsv", "results/interproscan.tsv", "annotation_table", "text/tab-separated-values")],
        resources={"interproscan_data": _database_resource("interproscan")},
        threads=2,
        mem_mb=4096,
    ),
    _profile(
        "qiime2-classify-sklearn",
        "q2-feature-classifier",
        "qiime feature-classifier classify-sklearn --i-classifier {config.silva_classifier:q} --i-reads {input.rep_seqs:q} --o-classification {output.taxonomy:q}",
        [_input("rep_seqs", "amplicon_sequences", "application/x-qza", filename="rep-seqs.qza", content="QIIME2\n")],
        [_output("taxonomy", "results/silva-taxonomy.qza", "taxonomy_classification", "application/x-qza")],
        tool_names=("qiime2-classify-sklearn", "q2-feature-classifier"),
        resources={"silva_classifier": _database_resource("silva_qiime")},
        mem_mb=4096,
    ),
    _profile(
        "checkm2-predict",
        "checkm2",
        "mkdir -p results/checkm2-genomes && cp {input.genome:q} results/checkm2-genomes/genome.fna && checkm2 predict --threads {threads} --database_path {config.checkm_db:q} --input results/checkm2-genomes --output-directory results/checkm2 && cp results/checkm2/quality_report.tsv {output.report:q}",
        [_input("genome", "assembly_contigs", "text/plain", filename="genome.fna", content=">genome\nACGTACGT\n")],
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
        "vcftools --vcf {input.vcf:q} --recode --recode-INFO-all --out results/vcftools-filtered {params.extra} && cp results/vcftools-filtered.recode.vcf {output.filtered_vcf:q}",
        _vcf_input(),
        [_output("filtered_vcf", "results/vcftools-filtered.recode.vcf", "variants_vcf", "text/plain")],
        params={"extra": {"type": "string", "title": "Extra VCFtools filter arguments", "default": ""}},
    ),
)
