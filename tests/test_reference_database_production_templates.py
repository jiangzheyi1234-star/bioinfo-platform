from __future__ import annotations

from pathlib import Path

from apps.remote_runner.database_templates import list_database_templates
from apps.remote_runner.databases import add_reference_database, check_reference_database
from tests.helpers.reference_database import (
    make_configured_remote_runner,
)


def _cfg(tmp_path: Path):
    return make_configured_remote_runner(tmp_path, token="database-production-template-token")


def test_database_templates_publish_structure_validation_only() -> None:
    templates = {item["id"]: item for item in list_database_templates()}

    for template in templates.values():
        assert set(template["validation"]) == {"structureCheck"}


def test_all_production_templates_publish_stable_runtime_contract() -> None:
    templates = {item["id"]: item for item in list_database_templates()}

    for template_id, template in templates.items():
        assert template["supportLevel"] == "stable", template_id
        assert template["supportedLayers"] == [
            "production_full",
            "user_manual",
            "validation_fixture",
        ], template_id
        assert template["select"]["allowDirectory"] is True or template["select"]["allowFile"] is True, template_id
        assert template["resolve"]["strategy"], template_id
        assert template["validation"]["structureCheck"], template_id
        assert template["output"].get("resolvedKey") == "default" or template["output"].get("valueFrom") == "resolved", template_id
        assert template["runtime"]["example"], template_id

    assert templates["humann"]["pathKind"] == "composite"
    assert set(templates["humann"]["fields"]) == {"nucleotide", "protein", "utility_mapping"}
    assert templates["card_rgi"]["pathKind"] == "composite"
    assert set(templates["card_rgi"]["fields"]) == {"card_json"}
    assert templates["eggnog_mapper"]["pathKind"] == "composite"
    assert set(templates["eggnog_mapper"]["fields"]) == {"data_dir"}


def test_humann_template_requires_chocophlan_uniref_and_utility_mapping(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    database_dir = tmp_path / "humann"
    chocophlan = database_dir / "chocophlan"
    uniref = database_dir / "uniref"
    utility = database_dir / "utility_mapping"
    chocophlan.mkdir(parents=True)
    uniref.mkdir()
    utility.mkdir()
    (uniref / "uniref90_201901.dmnd").write_text("protein", encoding="utf-8")

    saved = add_reference_database(
        cfg,
        {
            "id": "humann-prod",
            "name": "HUMAnN production",
            "templateId": "humann",
            "path": str(database_dir),
            "metadata": {
                "input": {
                    "kind": "multi",
                    "fields": {
                        "nucleotide": str(chocophlan),
                        "protein": str(uniref),
                        "utility_mapping": str(utility),
                    },
                }
            },
        },
    )

    missing = check_reference_database(cfg, saved["id"])
    assert missing["status"] == "missing"
    assert "*.ffn*" in missing["message"]

    (chocophlan / "g__Bacteria.centroids.ffn.gz").write_text("nucleotide", encoding="utf-8")
    (utility / "map_uniref90_name.txt.gz").write_text("mapping", encoding="utf-8")

    checked = check_reference_database(cfg, saved["id"])
    assert checked["status"] == "available"
    assert checked["pathMode"] == "composite"
    assert checked["resolved"] == {
        "nucleotide": str(chocophlan),
        "protein": str(uniref),
        "utility_mapping": str(utility),
    }


def test_card_rgi_template_resolves_card_json_from_selected_directory(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    database_dir = tmp_path / "card"
    database_dir.mkdir()
    card_json = database_dir / "card.json"
    card_json.write_text("{}", encoding="utf-8")

    saved = add_reference_database(cfg, {"id": "card", "name": "CARD", "templateId": "card_rgi", "path": str(database_dir)})

    checked = check_reference_database(cfg, saved["id"])
    assert checked["status"] == "available"
    assert checked["pathMode"] == "composite"
    assert checked["inputPath"] == str(database_dir)
    assert checked["entryPath"] == ""
    assert checked["resolved"] == {"card_json": str(card_json)}


def test_silva_qiime_template_requires_qiime_artifact(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    fasta = tmp_path / "silva.fasta"
    fasta.write_text(">seq\nACGT\n", encoding="utf-8")

    saved = add_reference_database(cfg, {"id": "silva", "name": "SILVA", "templateId": "silva_qiime", "path": str(fasta)})

    missing = check_reference_database(cfg, saved["id"])
    assert missing["status"] == "missing"
    assert "*.qza" in missing["message"]

    qza = tmp_path / "silva-classifier.qza"
    qza.write_text("qiime artifact", encoding="utf-8")
    updated = add_reference_database(cfg, {"id": "silva", "name": "SILVA", "templateId": "silva_qiime", "path": str(qza)})
    checked = check_reference_database(cfg, updated["id"])
    assert checked["status"] == "available"


def test_gtdbtk_template_requires_reference_bundle(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    database_dir = tmp_path / "gtdbtk"
    database_dir.mkdir()
    (database_dir / "VERSION").write_text("r226", encoding="utf-8")

    saved = add_reference_database(cfg, {"id": "gtdbtk", "name": "GTDB-Tk", "templateId": "gtdbtk", "path": str(database_dir)})

    missing = check_reference_database(cfg, saved["id"])
    assert missing["status"] == "missing"
    assert "markers" in missing["message"]

    for dirname in ("markers", "masks", "metadata", "mrca_red", "msa", "pplacer", "radii", "skani", "split", "taxonomy"):
        (database_dir / dirname).mkdir()

    missing_metadata = check_reference_database(cfg, saved["id"])
    assert missing_metadata["status"] == "missing"
    assert "metadata.txt" in missing_metadata["message"]

    (database_dir / "metadata" / "metadata.txt").write_text("metadata", encoding="utf-8")

    checked = check_reference_database(cfg, saved["id"])
    assert checked["status"] == "available"


def test_checkm_template_requires_checkm2_database_file(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    wrong = tmp_path / "checkm" / "diamond.dmnd"
    wrong.parent.mkdir()
    wrong.write_text("generic diamond db", encoding="utf-8")

    saved = add_reference_database(cfg, {"id": "checkm", "name": "CheckM2", "templateId": "checkm", "path": str(wrong)})

    missing = check_reference_database(cfg, saved["id"])
    assert missing["status"] == "missing"
    assert "uniref100.KO*.dmnd" in missing["message"]

    database_file = tmp_path / "CheckM2_database" / "uniref100.KO.1.dmnd"
    database_file.parent.mkdir()
    database_file.write_text("checkm2", encoding="utf-8")
    updated = add_reference_database(cfg, {"id": "checkm", "name": "CheckM2", "templateId": "checkm", "path": str(database_file)})
    checked = check_reference_database(cfg, updated["id"])
    assert checked["status"] == "available"


def test_eggnog_mapper_template_requires_annotation_and_search_databases(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    database_dir = tmp_path / "eggnog"
    database_dir.mkdir()
    (database_dir / "eggnog.db").write_text("sqlite", encoding="utf-8")

    saved = add_reference_database(
        cfg,
        {
            "id": "eggnog",
            "name": "eggNOG",
            "templateId": "eggnog_mapper",
            "path": str(database_dir),
            "metadata": {"input": {"kind": "multi", "fields": {"data_dir": str(database_dir)}}},
        },
    )

    missing = check_reference_database(cfg, saved["id"])
    assert missing["status"] == "missing"
    assert "eggnog_proteins.dmnd" in missing["message"]

    (database_dir / "eggnog_proteins.dmnd").write_text("diamond", encoding="utf-8")
    checked = check_reference_database(cfg, saved["id"])
    assert checked["status"] == "available"
    assert checked["pathMode"] == "composite"
    assert checked["resolved"] == {"data_dir": str(database_dir)}


def test_interproscan_template_requires_data_structure(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    database_dir = tmp_path / "interproscan-data"
    pfam_dir = database_dir / "pfam" / "35.0"
    pfam_dir.mkdir(parents=True)
    (pfam_dir / "pfam_a.hmm").write_text("hmm", encoding="utf-8")

    saved = add_reference_database(cfg, {"id": "interproscan", "name": "InterProScan", "templateId": "interproscan", "path": str(database_dir)})

    missing = check_reference_database(cfg, saved["id"])
    assert missing["status"] == "missing"
    assert "pfam_a.dat" in missing["message"]

    (pfam_dir / "pfam_a.dat").write_text("dat", encoding="utf-8")

    checked = check_reference_database(cfg, saved["id"])
    assert checked["status"] == "available"
