from __future__ import annotations

from apps.api.tool_profile_catalog import catalog_tool_profiles
from apps.api.tool_profile_registry import TOOL_PROFILES
from apps.api.tool_profiles import resolve_tool_profile


BIO_TOOL_PACK_V1_PROFILE_COUNT = 20


def test_bio_tool_pack_v1_has_twenty_curated_profiles() -> None:
    profile_ids = [profile.profile_id for profile in TOOL_PROFILES]

    assert len(profile_ids) >= BIO_TOOL_PACK_V1_PROFILE_COUNT
    assert len(profile_ids) == len(set(profile_ids))
    assert {"fastp", "fastqc", "kraken2", "bracken", "multiqc", "seqkit-stats"}.issubset(profile_ids)


def test_bio_tool_pack_v1_profiles_are_snakemake_renderable() -> None:
    for profile in TOOL_PROFILES:
        template = profile.rule_template
        action_count = sum(1 for key in ("commandTemplate", "wrapper", "script", "module") if template.get(key))
        inputs = [item for item in template.get("inputs") or [] if isinstance(item, dict)]
        outputs = [item for item in template.get("outputs") or [] if isinstance(item, dict)]
        conda = ((template.get("environment") or {}).get("conda") or {})
        smoke_inputs = ((template.get("smokeTest") or {}).get("inputs") or {})

        assert action_count == 1, profile.profile_id
        assert inputs, profile.profile_id
        assert outputs, profile.profile_id
        assert all(item.get("name") for item in inputs), profile.profile_id
        assert all("content" not in item and "filename" not in item for item in inputs), profile.profile_id
        assert all(item.get("name") and item.get("path") for item in outputs), profile.profile_id
        assert conda.get("channels") == ["conda-forge", "bioconda"], profile.profile_id
        assert conda.get("dependencies") == ["{packageSpec}"], profile.profile_id
        assert smoke_inputs, profile.profile_id
        for input_spec in inputs:
            if input_spec.get("required", True):
                assert input_spec["name"] in smoke_inputs, profile.profile_id


def test_bio_tool_pack_v1_catalog_exposes_addable_profile_candidates() -> None:
    catalog = catalog_tool_profiles(page=1, page_size=100)

    assert catalog["total"] >= BIO_TOOL_PACK_V1_PROFILE_COUNT
    assert catalog["addableTotal"] >= BIO_TOOL_PACK_V1_PROFILE_COUNT
    assert catalog["qualityCounts"]["draftRunnable"] >= BIO_TOOL_PACK_V1_PROFILE_COUNT
    assert all(item["candidateKind"] == "h2ometa-tool-profile" for item in catalog["items"])


def test_bio_tool_pack_v1_profiles_resolve_to_ready_rule_spec_drafts() -> None:
    for profile in TOOL_PROFILES:
        draft = resolve_tool_profile(
            {
                "name": profile.tool_names[0],
                "source": "bioconda",
                "packageSpec": f"bioconda::{profile.tool_names[0]}=1.0",
            }
        )

        assert draft is not None, profile.profile_id
        assert draft["source"] == "h2ometa-tool-profile"
        assert draft["requiresUserCompletion"] is False
        assert draft["status"] == "ready-for-validation"
        assert draft["lock"]["profileId"] == profile.profile_id
        assert draft["ruleTemplate"]["environment"]["conda"]["dependencies"] == [f"bioconda::{profile.tool_names[0]}=1.0"]
