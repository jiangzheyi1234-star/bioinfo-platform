from __future__ import annotations

from apps.api.tool_profile_catalog import catalog_tool_profiles
from apps.api.tool_profile_identity import profile_tool_id
from apps.api.tool_profile_prepare_payload import profile_prepare_payload
from apps.api.tool_profile_registry import TOOL_PROFILES
from apps.api.tool_profiles import resolve_tool_profile
from apps.remote_runner.database_templates import DATABASE_TEMPLATES


BIO_TOOL_PACK_V1_PROFILE_COUNT = 100
EDAM_SEQUENCE = "http://edamontology.org/data_2044"
EDAM_SEQUENCE_ALIGNMENT = "http://edamontology.org/data_0863"
EDAM_FASTQ = "http://edamontology.org/format_1930"
EDAM_SAM = "http://edamontology.org/format_2573"
EDAM_HTML = "http://edamontology.org/format_2331"


def test_bio_tool_pack_v1_has_hundred_curated_profiles() -> None:
    profile_ids = [profile.profile_id for profile in TOOL_PROFILES]
    tool_ids = [
        profile_tool_id(profile, source=profile.package_source) for profile in TOOL_PROFILES
    ]

    assert len(profile_ids) >= BIO_TOOL_PACK_V1_PROFILE_COUNT
    assert len(profile_ids) == len(set(profile_ids))
    assert len(tool_ids) == len(set(tool_ids))
    assert {
        "fastp",
        "fastqc",
        "kraken2",
        "bracken",
        "multiqc",
        "seqkit-stats",
        "samtools-sort",
        "picard-markduplicates",
        "blastn-search",
        "salmon-quant",
        "seqkit-grep",
        "samtools-flagstat",
        "bedtools-intersect",
        "bcftools-query",
        "sourmash-sketch-dna",
    }.issubset(profile_ids)


def test_bio_tool_pack_v1_profiles_are_snakemake_renderable() -> None:
    for profile in TOOL_PROFILES:
        template = profile.rule_template
        action_count = sum(
            1
            for key in ("commandTemplate", "wrapper", "script", "module")
            if template.get(key)
        )
        inputs = [
            item for item in template.get("inputs") or [] if isinstance(item, dict)
        ]
        outputs = [
            item for item in template.get("outputs") or [] if isinstance(item, dict)
        ]
        conda = (template.get("environment") or {}).get("conda") or {}
        smoke_inputs = (template.get("smokeTest") or {}).get("inputs") or {}

        assert action_count == 1, profile.profile_id
        assert inputs, profile.profile_id
        assert outputs, profile.profile_id
        assert all(item.get("name") for item in inputs), profile.profile_id
        assert all(
            "content" not in item and "filename" not in item for item in inputs
        ), profile.profile_id
        assert all(item.get("name") and item.get("path") for item in outputs), (
            profile.profile_id
        )
        channels = conda.get("channels")
        assert "conda-forge" in channels, profile.profile_id
        assert "bioconda" in channels, profile.profile_id
        assert channels.index("conda-forge") < channels.index("bioconda"), profile.profile_id
        dependencies = conda.get("dependencies")
        assert dependencies[0] == "{packageSpec}", profile.profile_id
        if profile.profile_id == "qiime2-classify-sklearn":
            assert dependencies == [
                "{packageSpec}",
                "qiime2::qiime2=2024.10.0",
                "qiime2::q2cli=2024.10.0",
                "conda-forge::click=8.1.7",
                "conda-forge::setuptools=80.9.0",
            ]
        elif profile.profile_id == "humann-profile":
            assert dependencies == ["{packageSpec}", "conda-forge::python=3.12"]
        else:
            assert dependencies == ["{packageSpec}"], profile.profile_id
        assert smoke_inputs, profile.profile_id
        for input_spec in inputs:
            if input_spec.get("required", True):
                assert input_spec["name"] in smoke_inputs, profile.profile_id


def test_open_source_profiles_do_not_publish_temp_files_as_artifacts() -> None:
    forbidden_fragments = {
        "results/deeptools-input.bam",
        "results/bedtools-input.bam",
        "results/macs2-input.bam",
        "results/featurecounts-input.bam",
        "results/picard-input.bam",
        "results/htseq-input.bam",
        "results/freebayes-input.bam",
        "results/mmseqs-tmp",
        "results/gtdbtk-genomes",
        "results/checkm2-genomes",
        "touch {output",
    }

    for profile in TOOL_PROFILES:
        command = str(profile.rule_template.get("commandTemplate") or "")
        for fragment in forbidden_fragments:
            assert fragment not in command, profile.profile_id


def test_bio_tool_pack_profile_prepare_payloads_keep_profile_identity_separate_from_package() -> (
    None
):
    for profile in TOOL_PROFILES:
        payload = profile_prepare_payload(profile)
        package_name = profile.package_name or profile.tool_names[0]

        assert payload["id"] == profile_tool_id(profile, source=payload["source"])
        assert payload["source"] == profile.package_source
        assert payload["profileId"] == profile.profile_id
        assert payload["validationTarget"] == profile.profile_id
        assert payload["packageName"] == package_name
        assert payload["packageSpec"] == f"{profile.package_source}::{package_name}={profile.package_version}"
        assert payload["version"] == profile.package_version
        assert payload["latestVersion"] == profile.package_version
        assert payload["ruleSpecDraft"]["lock"]["profileId"] == profile.profile_id
        assert payload["ruleSpecDraft"]["lock"]["packageSpec"] == payload["packageSpec"]


def test_bio_tool_pack_v1_catalog_exposes_addable_profile_candidates() -> None:
    catalog = catalog_tool_profiles(page=1, page_size=100)

    assert catalog["total"] >= BIO_TOOL_PACK_V1_PROFILE_COUNT
    assert catalog["addableTotal"] >= BIO_TOOL_PACK_V1_PROFILE_COUNT
    assert catalog["qualityCounts"]["draftRunnable"] >= BIO_TOOL_PACK_V1_PROFILE_COUNT
    assert len(catalog["items"]) == 100
    assert catalog["hasMore"] is True
    assert all(
        item["candidateKind"] == "h2ometa-tool-profile" for item in catalog["items"]
    )
    assert all(
        item["contractState"] == "SnakemakeRenderable" for item in catalog["items"]
    )
    assert all(item["qualityTier"] == "draft-runnable" for item in catalog["items"])
    assert all(
        item.get("preparePayload", {}).get("validationTarget") == item["profileId"]
        for item in catalog["items"]
    )
    for item in catalog["items"]:
        ref_types = {ref["type"] for ref in item["externalRefs"]}
        if item["preparePayload"]["source"] == "bioconda":
            assert {"bioconda-package", "biocontainers-container", "bio.tools-entry"}.issubset(ref_types)
        else:
            assert {"conda-package", "bio.tools-entry"}.issubset(ref_types)


def test_bio_tool_pack_v1_catalog_paginates_all_hundred_plus_profiles() -> None:
    first_page = catalog_tool_profiles(page=1, page_size=50)
    second_page = catalog_tool_profiles(page=2, page_size=50)
    collected: list[str] = []
    page = 1
    while True:
        catalog = catalog_tool_profiles(page=page, page_size=50)
        collected.extend(str(item["profileId"]) for item in catalog["items"])
        assert all(
            item["candidateKind"] == "h2ometa-tool-profile" for item in catalog["items"]
        )
        assert all(
            item["contractState"] == "SnakemakeRenderable" for item in catalog["items"]
        )
        assert all(item["qualityTier"] == "draft-runnable" for item in catalog["items"])
        assert all(
            isinstance(item.get("preparePayload"), dict) for item in catalog["items"]
        )
        if not catalog["hasMore"]:
            break
        page += 1

    expected_profile_ids = sorted(profile.profile_id for profile in TOOL_PROFILES)
    assert first_page["total"] == len(TOOL_PROFILES) >= BIO_TOOL_PACK_V1_PROFILE_COUNT
    assert len(first_page["items"]) == 50
    assert len(second_page["items"]) == 50
    assert not {item["profileId"] for item in first_page["items"]} & {
        item["profileId"] for item in second_page["items"]
    }
    assert collected == expected_profile_ids


def test_bio_tool_pack_v1_profiles_resolve_to_ready_rule_spec_drafts() -> None:
    for profile in TOOL_PROFILES:
        package_name = profile.package_name or profile.tool_names[0]
        draft = resolve_tool_profile(
            {
                "name": profile.tool_names[0],
                "source": profile.package_source,
                "packageSpec": f"{profile.package_source}::{package_name}=0.0-ignored",
            }
        )

        assert draft is not None, profile.profile_id
        assert draft["source"] == "h2ometa-tool-profile"
        assert draft["requiresUserCompletion"] is False
        assert draft["status"] == "ready-for-validation"
        assert draft["lock"]["profileId"] == profile.profile_id
        assert draft["lock"]["packageSpec"] == f"{profile.package_source}::{package_name}={profile.package_version}"
        dependencies = draft["ruleTemplate"]["environment"]["conda"]["dependencies"]
        assert f"{profile.package_source}::{package_name}={profile.package_version}" in dependencies
        if profile.profile_id == "qiime2-classify-sklearn":
            assert "qiime2::qiime2=2024.10.0" in dependencies
        elif profile.profile_id == "humann-profile":
            assert dependencies == [
                f"{profile.package_source}::{package_name}={profile.package_version}",
                "conda-forge::python=3.12",
            ]
        else:
            assert dependencies == [f"{profile.package_source}::{package_name}={profile.package_version}"]


def test_bio_tool_pack_database_resources_use_dedicated_templates_when_available() -> (
    None
):
    resources_by_profile = {
        profile.profile_id: {
            key: spec
            for key, spec in (profile.rule_template.get("resources") or {}).items()
            if isinstance(spec, dict) and spec.get("type") == "database"
        }
        for profile in TOOL_PROFILES
    }

    expected_dedicated_templates = {
        ("bracken", "bracken_db"): "bracken",
        ("kraken2", "kraken2_db"): "kraken2",
        ("bwa-mem", "bwa_index"): "bwa",
        ("bowtie2-align", "bowtie2_index"): "bowtie2",
        ("blastn-search", "blast_db"): "blast",
        ("minimap2-align", "reference_fasta"): "minimap2",
        ("salmon-quant", "transcriptome_index"): "salmon",
        ("hisat2-align", "hisat2_index"): "hisat2",
        ("star-align", "star_index"): "star",
        ("kallisto-quant", "transcriptome_index"): "kallisto",
        ("featurecounts", "annotation_gtf"): "annotation_gtf",
        ("htseq-count", "annotation_gtf"): "annotation_gtf",
        ("freebayes-call", "reference_fasta"): "reference_fasta",
    }
    for (profile_id, resource_key), template_id in expected_dedicated_templates.items():
        resource = resources_by_profile[profile_id][resource_key]
        assert resource["acceptedTemplates"] == [template_id]

    referenced_templates = {
        template_id
        for resources in resources_by_profile.values()
        for resource in resources.values()
        for template_id in resource.get("acceptedTemplates") or []
    }
    assert set(DATABASE_TEMPLATES) - referenced_templates == {"custom"}
    assert {
        "metaphlan",
        "centrifuge",
        "kaiju",
        "card_rgi",
        "diamond",
        "humann",
        "gtdbtk",
        "sourmash",
        "mmseqs2",
        "hmmer_pfam",
        "eggnog_mapper",
        "interproscan",
        "silva_qiime",
        "checkm",
        "ncbi_taxonomy",
    }.issubset(referenced_templates)

    for profile_id, resources in resources_by_profile.items():
        for resource_key, resource in resources.items():
            for template_id in resource.get("acceptedTemplates") or []:
                assert template_id in DATABASE_TEMPLATES, f"{profile_id}:{resource_key}"


def test_bio_tool_pack_resolved_profiles_include_edam_port_semantics() -> None:
    fastqc = resolve_tool_profile(
        {
            "name": "fastqc",
            "source": "bioconda",
            "packageSpec": "bioconda::fastqc=1.0",
        }
    )
    bwa = resolve_tool_profile(
        {
            "name": "bwa",
            "source": "bioconda",
            "packageSpec": "bioconda::bwa=1.0",
        }
    )

    assert fastqc is not None
    reads = fastqc["ruleTemplate"]["inputs"][0]
    html = next(
        item for item in fastqc["ruleTemplate"]["outputs"] if item["name"] == "html"
    )
    assert reads["data"] == EDAM_SEQUENCE
    assert reads["format"] == EDAM_FASTQ
    assert html["format"] == EDAM_HTML

    assert bwa is not None
    sam = next(item for item in bwa["ruleTemplate"]["outputs"] if item["name"] == "sam")
    assert sam["data"] == EDAM_SEQUENCE_ALIGNMENT
    assert sam["format"] == EDAM_SAM
