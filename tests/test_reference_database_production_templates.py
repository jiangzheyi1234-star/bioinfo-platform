from __future__ import annotations

from pathlib import Path

from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from apps.remote_runner.databases import add_reference_database, check_reference_database


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


def test_humann_template_requires_chocophlan_uniref_and_utility_mapping(tmp_path: Path, monkeypatch) -> None:
    _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    database_dir = tmp_path / "humann"
    database_dir.mkdir()
    (database_dir / "uniref90.dmnd").write_text("diamond", encoding="utf-8")

    saved = add_reference_database(cfg, {"id": "humann-prod", "name": "HUMAnN production", "templateId": "humann", "path": str(database_dir)})

    missing = check_reference_database(cfg, saved["id"])
    assert missing["status"] == "missing"
    assert "chocophlan/**/*.ffn*" in missing["message"]

    chocophlan = database_dir / "chocophlan"
    uniref = database_dir / "uniref"
    utility = database_dir / "utility_mapping"
    chocophlan.mkdir()
    uniref.mkdir()
    utility.mkdir()
    (chocophlan / "g__Bacteria.centroids.ffn.gz").write_text("nucleotide", encoding="utf-8")
    (uniref / "uniref90_201901.dmnd").write_text("protein", encoding="utf-8")
    (utility / "map_uniref90_name.txt.gz").write_text("mapping", encoding="utf-8")

    checked = check_reference_database(cfg, saved["id"])
    assert checked["status"] == "available"


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

    saved = add_reference_database(cfg, {"id": "eggnog", "name": "eggNOG", "templateId": "eggnog_mapper", "path": str(database_dir)})

    missing = check_reference_database(cfg, saved["id"])
    assert missing["status"] == "missing"
    assert "eggnog_proteins.dmnd" in missing["message"]

    (database_dir / "eggnog_proteins.dmnd").write_text("diamond", encoding="utf-8")
    checked = check_reference_database(cfg, saved["id"])
    assert checked["status"] == "available"


def test_interproscan_template_probe_uses_selected_data_directory(tmp_path: Path, monkeypatch) -> None:
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
    assert "--datadir" in calls[-1]
    assert str(database_dir) in calls[-1]
