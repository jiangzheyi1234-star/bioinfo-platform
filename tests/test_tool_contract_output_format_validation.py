from __future__ import annotations

from pathlib import Path

import pytest

from apps.remote_runner.tool_contract_validation import _validate_outputs


def test_output_validation_rejects_malformed_xml_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "report.xml"
    output.write_text("<report><sample></report>", encoding="utf-8")

    error = _validate_outputs(
        output_schema={
            "artifacts": [
                {"key": "report", "mimeType": "application/xml", "name": "report.xml"},
            ]
        },
        outputs={"report": str(output)},
    )

    assert error is not None
    assert error["code"] == "OUTPUT_ARTIFACT_FORMAT_INVALID"
    assert error["message"].startswith("report:")


def test_output_validation_rejects_malformed_json_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    output.write_text("{not-json", encoding="utf-8")

    error = _validate_outputs(
        output_schema={
            "artifacts": [
                {"key": "report", "mimeType": "application/json", "name": "report.json"},
            ]
        },
        outputs={"report": str(output)},
    )

    assert error is not None
    assert error["code"] == "OUTPUT_ARTIFACT_FORMAT_INVALID"
    assert error["message"].startswith("report:")


def test_output_validation_does_not_mask_unexpected_xml_parser_errors(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "report.xml"
    output.write_text("<report />", encoding="utf-8")

    def fake_parse(*_args, **_kwargs):
        raise RuntimeError("xml parser crashed")

    monkeypatch.setattr("apps.remote_runner.tool_contract_validation.ElementTree.parse", fake_parse)

    with pytest.raises(RuntimeError, match="xml parser crashed"):
        _validate_outputs(
            output_schema={
                "artifacts": [
                    {"key": "report", "mimeType": "application/xml", "name": "report.xml"},
                ]
            },
            outputs={"report": str(output)},
        )
