"""Additional direct-use profiles that sit behind the core lightweight pack."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .tool_profile_model import ToolProfile


ProfileFactory = Callable[..., ToolProfile]
InputsFactory = Callable[..., list[dict[str, Any]]]
OutputFactory = Callable[..., dict[str, Any]]


def extra_direct_use_tool_profiles(
    _profile: ProfileFactory,
    _inputs: InputsFactory,
    _output: OutputFactory,
) -> tuple[ToolProfile, ...]:
    return (
        _profile(
            "sourmash-sketch-dna",
            "sourmash",
            "sourmash sketch dna -o {output.sketch:q} {input.sequences:q}",
            _inputs(("sequences", "fasta")),
            [
                _output(
                    "sketch",
                    "results/sourmash-sketch.sig",
                    "sequence_sketch",
                    "application/json",
                )
            ],
            mem_mb=1024,
        ),
        _profile(
            "sourmash-compare-self",
            "sourmash",
            "sourmash sketch dna -o sourmash-compare.sig {input.sequences:q} && sourmash compare sourmash-compare.sig sourmash-compare.sig -o {output.matrix:q}",
            _inputs(("sequences", "fasta")),
            [
                _output(
                    "matrix",
                    "results/sourmash-compare.npy",
                    "distance_matrix",
                    "application/octet-stream",
                )
            ],
            mem_mb=1024,
        ),
        _profile(
            "sourmash-signature-describe",
            "sourmash",
            "sourmash sketch dna -o sourmash-describe.sig {input.sequences:q} && sourmash sig describe sourmash-describe.sig > {output.description:q}",
            _inputs(("sequences", "fasta")),
            [
                _output(
                    "description",
                    "results/sourmash-description.txt",
                    "sequence_sketch_report",
                )
            ],
            mem_mb=1024,
        ),
        _profile(
            "mash-dist-self",
            "mash",
            "mash sketch -o mash-dist {input.sequences:q} && mash dist mash-dist.msh mash-dist.msh > {output.distances:q}",
            _inputs(("sequences", "fasta")),
            [
                _output(
                    "distances",
                    "results/mash-dist.tsv",
                    "distance_table",
                    "text/tab-separated-values",
                )
            ],
            mem_mb=1024,
        ),
        _profile(
            "mash-info",
            "mash",
            "mash sketch -o mash-info {input.sequences:q} && mash info mash-info.msh > {output.info:q}",
            _inputs(("sequences", "fasta")),
            [_output("info", "results/mash-info.txt", "sequence_sketch_report")],
            mem_mb=1024,
        ),
        _profile(
            "minimap2-paf",
            "minimap2",
            "minimap2 -x map-ont -t {threads} {input.reference:q} {input.query:q} > {output.paf:q}",
            _inputs(("reference", "reference"), ("query", "fasta")),
            [
                _output(
                    "paf",
                    "results/minimap2.paf",
                    "alignment_paf",
                    "text/tab-separated-values",
                )
            ],
            threads=2,
            mem_mb=1024,
        ),
        _profile(
            "bwa-index",
            "bwa",
            "mkdir -p {output.index:q} && cp {input.reference:q} {output.index:q}/reference.fasta && bwa index {output.index:q}/reference.fasta",
            _inputs(("reference", "reference")),
            [
                _output(
                    "index",
                    "results/bwa-index",
                    "bwa_index",
                    "inode/directory",
                    directory=True,
                )
            ],
            mem_mb=1024,
        ),
        _profile(
            "bowtie2-build",
            "bowtie2",
            "mkdir -p {output.index:q} && bowtie2-build {input.reference:q} {output.index:q}/reference",
            _inputs(("reference", "reference")),
            [
                _output(
                    "index",
                    "results/bowtie2-index",
                    "bowtie2_index",
                    "inode/directory",
                    directory=True,
                )
            ],
            threads=2,
            mem_mb=1024,
        ),
        _profile(
            "prodigal-genes",
            "prodigal",
            "prodigal -i {input.contigs:q} -a {output.proteins:q} -d {output.genes:q} -o {output.report:q} -p meta",
            _inputs(("contigs", "orf_contigs")),
            [
                _output("proteins", "results/prodigal.faa", "protein_sequence"),
                _output("genes", "results/prodigal.fna", "gene_sequence"),
                _output("report", "results/prodigal.gbk", "annotation_report"),
            ],
            mem_mb=1024,
        ),
        _profile(
            "barrnap-rrna",
            "barrnap",
            "barrnap --threads {threads} {input.contigs:q} > {output.gff:q}",
            _inputs(("contigs", "fasta")),
            [_output("gff", "results/barrnap.gff", "annotation_gff")],
            threads=2,
            mem_mb=1024,
        ),
        _profile(
            "trnascan-se",
            "trnascan-se",
            "tRNAscan-SE -o {output.table:q} {input.contigs:q}",
            _inputs(("contigs", "trna_contigs")),
            [
                _output(
                    "table",
                    "results/trnascan.tsv",
                    "annotation_table",
                    "text/tab-separated-values",
                )
            ],
            mem_mb=1024,
        ),
        _profile(
            "cd-hit-est",
            "cd-hit",
            "cd-hit-est -i {input.sequences:q} -o {output.clusters:q} -c 0.9 -T {threads} -M 0",
            _inputs(("sequences", "fasta")),
            [_output("clusters", "results/cdhit-clusters.fasta", "sequence_clusters")],
            threads=2,
            mem_mb=1024,
        ),
        _profile(
            "vsearch-cluster",
            "vsearch",
            "vsearch --cluster_fast {input.sequences:q} --id 0.9 --centroids {output.centroids:q} --threads {threads}",
            _inputs(("sequences", "fasta")),
            [
                _output(
                    "centroids", "results/vsearch-centroids.fasta", "sequence_clusters"
                )
            ],
            threads=2,
            mem_mb=1024,
        ),
        _profile(
            "vsearch-filter",
            "vsearch",
            "vsearch --fastq_filter {input.reads:q} --fastq_maxee 1.0 --fastqout {output.filtered:q}",
            _inputs(("reads", "fastq")),
            [_output("filtered", "results/vsearch-filter.fastq", "sequence_reads")],
            mem_mb=1024,
        ),
        _profile(
            "mafft-align",
            "mafft",
            "mafft --thread {threads} {input.sequences:q} > {output.alignment:q}",
            _inputs(("sequences", "fasta")),
            [
                _output(
                    "alignment",
                    "results/mafft-alignment.fasta",
                    "multiple_sequence_alignment",
                )
            ],
            threads=2,
            mem_mb=1024,
        ),
        _profile(
            "muscle-align",
            "muscle",
            "muscle -align {input.sequences:q} -output {output.alignment:q}",
            _inputs(("sequences", "fasta")),
            [
                _output(
                    "alignment",
                    "results/muscle-alignment.fasta",
                    "multiple_sequence_alignment",
                )
            ],
            threads=2,
            mem_mb=1024,
        ),
        _profile(
            "clustalo-align",
            "clustalo",
            "clustalo -i {input.sequences:q} -o {output.alignment:q} --force --threads={threads}",
            _inputs(("sequences", "fasta")),
            [
                _output(
                    "alignment",
                    "results/clustalo-alignment.fasta",
                    "multiple_sequence_alignment",
                )
            ],
            threads=2,
            mem_mb=1024,
        ),
        _profile(
            "hmmer-hmmbuild",
            "hmmer",
            "hmmbuild {output.hmm:q} {input.alignment:q}",
            _inputs(("alignment", "alignment")),
            [_output("hmm", "results/hmmer-model.hmm", "profile_hmm")],
            mem_mb=1024,
        ),
        _profile(
            "hmmer-hmmsearch",
            "hmmer",
            "hmmbuild hmmer-query.hmm {input.alignment:q} && hmmsearch --tblout {output.tblout:q} hmmer-query.hmm {input.proteins:q} > {output.report:q}",
            _inputs(("alignment", "alignment"), ("proteins", "protein")),
            [
                _output("tblout", "results/hmmer-hits.tblout", "profile_hmm_hits"),
                _output("report", "results/hmmer-report.txt", "profile_hmm_report"),
            ],
            threads=2,
            mem_mb=1024,
        ),
        _profile(
            "emboss-seqret",
            "emboss",
            "seqret -sequence {input.sequences:q} -outseq {output.converted:q}",
            _inputs(("sequences", "fasta")),
            [_output("converted", "results/emboss-seqret.fasta", "sequence_reads")],
            mem_mb=1024,
        ),
        _profile(
            "seqmagick-convert",
            "seqmagick",
            "seqmagick convert {input.sequences:q} {output.converted:q}",
            _inputs(("sequences", "fasta")),
            [
                _output(
                    "converted", "results/seqmagick-converted.fasta", "sequence_reads"
                )
            ],
            mem_mb=1024,
        ),
    )
