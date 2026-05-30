from __future__ import annotations

from pathlib import Path

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
