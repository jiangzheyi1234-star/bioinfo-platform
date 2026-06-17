from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "reference-database-pack-lifecycle.md"


def test_reference_database_pack_lifecycle_doc_defines_manual_only_contract() -> None:
    source = DOC.read_text(encoding="utf-8")

    for token in (
        "database-pack-lifecycle-v1",
        "GET /api/v1/database-packs",
        "catalog declarations",
        "does not download, extract, install, repair, register, or mutate",
        "installMode: manual_external",
        "operatorActionRequired: true",
        "noAutomaticExecution: true",
        "metadata.installedFromPackId",
        "scripts/register_gtdbtk_r232_database.py",
        "real-database-acceptance",
        "validation_fixture",
        "must never satisfy production evidence",
    ):
        assert token in source


def test_reference_database_pack_lifecycle_doc_is_listed_in_docs_index() -> None:
    index = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")

    assert "reference-database-pack-lifecycle.md" in index
