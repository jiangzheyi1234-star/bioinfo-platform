from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_deployment_modes_document_current_artifact_s3_configuration() -> None:
    source = (ROOT / "docs" / "deployment-modes.md").read_text(encoding="utf-8")

    assert "H2OMETA_ARTIFACT_S3_ENDPOINT" in source
    assert "H2OMETA_ARTIFACT_S3_BUCKET" in source
    assert "H2OMETA_ARTIFACT_S3_PREFIX" in source
    assert "H2OMETA_ARTIFACT_S3_ACCESS_KEY" in source
    assert "H2OMETA_ARTIFACT_S3_SECRET_KEY" in source
    assert "H2OMETA_ARTIFACT_S3_SECURE" in source
    assert "H2OMETA_S3_ENDPOINT" not in source
    assert "H2OMETA_S3_BUCKET" not in source
