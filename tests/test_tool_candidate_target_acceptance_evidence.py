from __future__ import annotations

from apps.api.tool_candidate_target_acceptance_evidence import validation_evidence
from apps.api.tool_profile_model import ToolProfile


def test_base64_smoke_fixture_counts_as_materialized_evidence() -> None:
    profile = ToolProfile(
        profile_id="binary-smoke",
        version=1,
        tool_names=("binary-smoke",),
        rule_template={},
    )
    prepare_payload = {
        "ruleTemplate": {
            "inputs": [{"name": "archive", "type": "file"}],
            "outputs": [],
            "smokeTest": {
                "inputs": {
                    "archive": {
                        "filename": "fixture.zip",
                        "mimeType": "application/zip",
                        "contentBase64": "UEsFBgAAAAAAAAAAAAAAAAAAAAAAAA==",
                    }
                }
            },
        }
    }

    evidence = validation_evidence(profile=profile, prepare_payload=prepare_payload)

    assert evidence["smokeFixtureQuality"] == "materialized"
    assert evidence["smokeFixtureIssues"] == []
