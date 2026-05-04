from __future__ import annotations

from pathlib import Path

from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from apps.remote_runner.databases import add_reference_database, check_reference_database, list_database_templates


def _cfg(tmp_path: Path) -> RemoteRunnerConfig:
    return RemoteRunnerConfig(
        token="database-production-template-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(Path.cwd() / "apps" / "remote_runner"),
        managed_conda_command=str(tmp_path / "workflow-env" / "bin" / "conda"),
        snakemake_command=str(tmp_path / "workflow-env" / "bin" / "snakemake"),
    )


def _patch_tool_probe_success(monkeypatch) -> list[str]:
    from apps.remote_runner import database_validation

    calls: list[str] = []
    monkeypatch.setattr(database_validation, "prepare_tool_probe_command", lambda cfg, template_id, template, command: command)

    def fake_probe(command: str, *, timeout: int) -> database_validation.ToolProbeResult:
        calls.append(command)
        return database_validation.ToolProbeResult(ok=True, command=command, stdout="probe ok", stderr="", returncode=0)

    monkeypatch.setattr(database_validation, "run_tool_probe", fake_probe)
    return calls


def test_database_tool_probes_follow_official_smoke_test_patterns() -> None:
    templates = {item["id"]: item for item in list_database_templates()}

    bwa_probe = templates["bwa"]["toolProbe"]["commandTemplate"]
    assert "probe.fq" in bwa_probe
    assert "bwa mem" in bwa_probe
    assert " /dev/null" not in bwa_probe

    minimap2_probe = templates["minimap2"]["toolProbe"]["commandTemplate"]
    assert "probe.fa" in minimap2_probe
    assert "minimap2" in minimap2_probe
    assert " /dev/null" not in minimap2_probe

    checkm_probe = templates["checkm"]["toolProbe"]["commandTemplate"]
    assert "--database_path {path:q}" in checkm_probe
    assert "checkm2 testrun" in checkm_probe
    assert "--help" not in checkm_probe
    assert templates["checkm"]["toolProbe"]["timeoutSeconds"] >= 600

    gtdbtk_probe = templates["gtdbtk"]["toolProbe"]["commandTemplate"]
    assert "gtdbtk check_install" in gtdbtk_probe
    assert templates["gtdbtk"]["toolProbe"]["timeoutSeconds"] >= 600

    interproscan_probe = templates["interproscan"]["toolProbe"]["commandTemplate"]
    assert "--datadir" not in interproscan_probe
    assert "interproscan.sh -version" in interproscan_probe

    silva_probe = templates["silva_qiime"]["toolProbe"]
    assert silva_probe["packageSpec"] == "qiime2::q2cli=2024.10.0"
    assert silva_probe["packageSpecs"] == [
        "qiime2::q2cli=2024.10.0",
        "qiime2::q2-types=2024.10.0",
        "conda-forge::setuptools=75.8.0",
    ]


def test_all_production_templates_publish_stable_runtime_contract() -> None:
    templates = {item["id"]: item for item in list_database_templates()}

    for template_id, template in templates.items():
        assert template["supportLevel"] == "stable", template_id
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
    _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
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
    calls = _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
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
    assert calls and "rgi card_annotation -i" in calls[-1]
    assert str(card_json) in calls[-1]


def test_silva_qiime_template_requires_qiime_artifact(tmp_path: Path, monkeypatch) -> None:
    _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
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


def test_gtdbtk_template_requires_reference_bundle_and_check_install(tmp_path: Path, monkeypatch) -> None:
    calls = _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    database_dir = tmp_path / "gtdbtk"
    database_dir.mkdir()
    (database_dir / "VERSION").write_text("r226", encoding="utf-8")

    saved = add_reference_database(cfg, {"id": "gtdbtk", "name": "GTDB-Tk", "templateId": "gtdbtk", "path": str(database_dir)})

    missing = check_reference_database(cfg, saved["id"])
    assert missing["status"] == "missing"
    assert "markers" in missing["message"]

    for dirname in ("markers", "masks", "metadata", "mrca_red", "msa", "pplacer", "radii", "skani", "split", "taxonomy"):
        (database_dir / dirname).mkdir()

    checked = check_reference_database(cfg, saved["id"])
    assert checked["status"] == "available"
    assert calls and "gtdbtk check_install" in calls[-1]


def test_checkm_template_requires_checkm2_database_file(tmp_path: Path, monkeypatch) -> None:
    _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
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
    _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
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


def test_interproscan_template_probe_verifies_installed_cli_after_data_structure_check(tmp_path: Path, monkeypatch) -> None:
    calls = _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    database_dir = tmp_path / "interproscan-data"
    database_dir.mkdir()
    (database_dir / "interpro.xml").write_text("xml", encoding="utf-8")
    (database_dir / "match_complete.xml").write_text("xml", encoding="utf-8")

    saved = add_reference_database(cfg, {"id": "interproscan", "name": "InterProScan", "templateId": "interproscan", "path": str(database_dir)})

    checked = check_reference_database(cfg, saved["id"])
    assert checked["status"] == "available"
    assert calls
    assert "interproscan.sh -version" in calls[-1]
    assert "--datadir" not in calls[-1]
