from __future__ import annotations

import json
from pathlib import Path

from core.data.project_manager import ProjectManager
from core.execution.tool_bridge_service import ToolBridgeService
from core.plugins.plugin_registry import PluginRegistry
from core.pipeline.chart_data_parser import ChartDataParser


def _build_project_manager(tmp_path: Path) -> ProjectManager:
    pm = ProjectManager(
        projects_root=tmp_path / "projects",
        index_path=tmp_path / "projects.json",
        last_project_path=tmp_path / "last_project.txt",
    )
    project_id = pm.create_project("single-tool-results")
    pm.open_project(project_id)
    return pm


def _build_plugin_registry() -> PluginRegistry:
    registry = PluginRegistry(Path("plugins"))
    registry.scan()
    return registry


def test_get_results_for_execution_rejects_non_completed(tmp_path: Path):
    pm = _build_project_manager(tmp_path)
    pm.db.execute(
        "INSERT INTO samples (sample_id, name, source, metadata) VALUES (?, ?, ?, ?)",
        ("smp_demo", "demo", "test", "{}"),
    )
    pm.db.execute(
        "INSERT INTO executions (execution_id, sample_id, tool_id, tool_version, parameters, status, triggered_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("exec_demo", "smp_demo", "fastp", "0.23.4", "{}", "running", "manual", 1.0),
    )
    pm.db.commit()

    class _Locator:
        project_manager = pm

    service = ToolBridgeService(service_locator=_Locator(), plugin_registry=_build_plugin_registry())

    payload = service.get_results_for_execution("exec_demo")

    assert payload["status"] == "error"
    assert "尚未完成" in payload["message"]
    pm.close()


def test_get_results_for_execution_dispatches_fastp(monkeypatch):
    service = ToolBridgeService()
    monkeypatch.setattr(
        service,
        "_get_execution_result_row",
        lambda execution_id: {
            "execution_id": execution_id,
            "tool_id": "fastp",
            "status": "completed",
        },
    )
    monkeypatch.setattr(
        service,
        "_build_qc_report_view_for_execution",
        lambda execution_id, row: {"feature_id": "fastp", "tool_id": "fastp", "archetype": "qc_report", "hero": {"execution_id": execution_id}},
    )

    payload = service.get_results_for_execution("exec_fastp")

    assert payload["status"] == "ok"
    assert payload["view"]["hero"]["execution_id"] == "exec_fastp"
    assert payload["view"]["archetype"] == "qc_report"


def test_get_results_for_execution_builds_prokka_view(tmp_path: Path):
    pm = _build_project_manager(tmp_path)
    registry = _build_plugin_registry()
    pm.db.execute(
        "INSERT INTO samples (sample_id, name, source, metadata) VALUES (?, ?, ?, ?)",
        ("smp_prokka", "prokka sample", "test", "{}"),
    )
    pm.db.execute(
        "INSERT INTO executions (execution_id, sample_id, tool_id, tool_version, parameters, status, triggered_by, created_at, completed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "exec_prokka",
            "smp_prokka",
            "prokka",
            "1.14.6",
            json.dumps({"kingdom": "Bacteria", "threads": 8}),
            "completed",
            "manual",
            1.0,
            2.0,
        ),
    )
    pm.db.commit()

    results_dir = pm.current_project_dir / "results" / "exec_prokka"
    results_dir.mkdir(parents=True, exist_ok=True)
    stats_path = results_dir / "smp_prokka.prokka.txt"
    stats_path.write_text(
        "\n".join(
            [
                "organism: Demo bacterium",
                "contigs: 12",
                "bases: 3456789",
                "CDS: 3210",
                "rRNA: 6",
                "tRNA: 44",
            ]
        ),
        encoding="utf-8",
    )
    gff_path = results_dir / "smp_prokka.prokka.gff"
    gff_path.write_text("##gff-version 3\n", encoding="utf-8")
    (results_dir / "artifacts_manifest.json").write_text(
        json.dumps(
            {
                "execution_id": "exec_prokka",
                "tool_id": "prokka",
                "output_dir": "/remote/prokka",
                "artifacts": [
                    {
                        "name": "smp_prokka.prokka.txt",
                        "remote_path": "/remote/prokka/smp_prokka.prokka.txt",
                        "local_path": str(stats_path),
                        "available": True,
                    },
                    {
                        "name": "smp_prokka.prokka.gff",
                        "remote_path": "/remote/prokka/smp_prokka.prokka.gff",
                        "local_path": str(gff_path),
                        "available": True,
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    class _Locator:
        project_manager = pm

    service = ToolBridgeService(service_locator=_Locator(), plugin_registry=registry)

    payload = service.get_results_for_execution("exec_prokka")

    assert payload["status"] == "ok"
    assert payload["view"]["feature_id"] == "prokka"
    assert payload["view"]["archetype"] == "annotation_table"
    assert payload["view"]["summary"][0]["label"] == "CDS"
    assert payload["view"]["rows"][0]["organism"] == "Demo bacterium"
    assert payload["view"]["artifacts"][0]["available"] is True
    assert payload["view"]["provenance"]["execution_id"] == "exec_prokka"
    pm.close()


def test_fastp_view_uses_sample_scoped_artifact_names(tmp_path: Path):
    pm = _build_project_manager(tmp_path)
    pm.db.execute(
        "INSERT INTO samples (sample_id, name, source, metadata) VALUES (?, ?, ?, ?)",
        ("smp_fastp", "fastp sample", "test", "{}"),
    )
    pm.db.execute(
        "INSERT INTO executions (execution_id, sample_id, tool_id, tool_version, parameters, status, triggered_by, created_at, completed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "exec_fastp",
            "smp_fastp",
            "fastp",
            "0.23.4",
            "{}",
            "completed",
            "manual",
            1.0,
            2.0,
        ),
    )
    pm.db.commit()

    results_dir = pm.current_project_dir / "results" / "exec_fastp"
    results_dir.mkdir(parents=True, exist_ok=True)
    json_path = results_dir / "smp_fastp.fastp.json"
    html_path = results_dir / "smp_fastp.fastp.html"
    json_path.write_text(
        json.dumps(
            {
                "summary": {
                    "before_filtering": {"total_reads": 1000, "q30_rate": 0.9, "gc_content": 0.5},
                    "after_filtering": {"total_reads": 800, "q30_rate": 0.95, "gc_content": 0.48},
                },
                "filtering_result": {
                    "passed_filter_reads": 800,
                    "low_quality_reads": 100,
                    "too_short_reads": 80,
                    "too_many_N_reads": 20,
                },
            }
        ),
        encoding="utf-8",
    )
    html_path.write_text("<html></html>", encoding="utf-8")
    (results_dir / "artifacts_manifest.json").write_text(
        json.dumps(
            {
                "execution_id": "exec_fastp",
                "tool_id": "fastp",
                "output_dir": "/remote/fastp",
                "artifacts": [
                    {
                        "name": "smp_fastp.fastp.json",
                        "remote_path": "/remote/fastp/smp_fastp.fastp.json",
                        "local_path": str(json_path),
                        "available": True,
                    },
                    {
                        "name": "smp_fastp.fastp.html",
                        "remote_path": "/remote/fastp/smp_fastp.fastp.html",
                        "local_path": str(html_path),
                        "available": True,
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    class _Locator:
        project_manager = pm

    service = ToolBridgeService(service_locator=_Locator())
    view = service._build_fastp_view_for_execution("exec_fastp")

    assert view is not None
    assert view["artifacts"][0]["name"] == "smp_fastp.fastp.json"
    assert view["artifacts"][1]["name"] == "smp_fastp.fastp.html"
    assert view["artifacts"][1]["available"] is True
    pm.close()


def test_kraken2_kreport_parsing_matches_manual_style_sample(tmp_path: Path):
    kreport_path = tmp_path / "sample.kreport"
    kreport_path.write_text(
        "\n".join(
            [
                "99.98\t787758\t787758\tU\t0\tunclassified",
                "0.02\t119\t0\tR\t1\troot",
                "0.02\t119\t0\tR1\t131567\tcellular organisms",
                "0.02\t119\t0\tD\t2759\tEukaryota",
                "0.01\t96\t0\tK\t4751\tFungi",
                "0.01\t96\t96\tS\t4932\tSaccharomyces cerevisiae",
            ]
        ),
        encoding="utf-8",
    )

    chart = ChartDataParser.parse_kreport(str(kreport_path))
    summary = ChartDataParser.parse_kreport_summary(str(kreport_path))

    assert chart["type"] == "pie"
    assert chart["data"][0]["name"] == "Saccharomyces cerevisiae"
    assert summary["classified_reads"] == 119
    assert summary["unclassified_reads"] == 787758
    assert summary["species_count"] == 1
    assert summary["top_species"] == "Saccharomyces cerevisiae"


def test_get_results_for_execution_dispatches_kraken2_to_targeted(monkeypatch):
    service = ToolBridgeService()
    monkeypatch.setattr(
        service,
        "_get_execution_result_row",
        lambda execution_id: {
            "execution_id": execution_id,
            "tool_id": "kraken2",
            "status": "completed",
        },
    )
    monkeypatch.setattr(
        service,
        "_build_taxonomy_profile_view_for_execution",
        lambda execution_id, row: {"feature_id": "kraken2", "tool_id": "kraken2", "archetype": "taxonomy_profile", "hero": {"execution_id": execution_id}},
    )

    payload = service.get_results_for_execution("exec_kraken2")

    assert payload["status"] == "ok"
    assert payload["view"]["feature_id"] == "kraken2"
    assert payload["view"]["archetype"] == "taxonomy_profile"


def test_get_results_for_execution_builds_fastp_without_ssh(tmp_path: Path):
    pm = _build_project_manager(tmp_path)
    pm.db.execute(
        "INSERT INTO samples (sample_id, name, source, metadata) VALUES (?, ?, ?, ?)",
        ("smp_fastp2", "fastp sample", "test", "{}"),
    )
    pm.db.execute(
        "INSERT INTO executions (execution_id, sample_id, tool_id, tool_version, parameters, status, triggered_by, created_at, completed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "exec_fastp2",
            "smp_fastp2",
            "fastp",
            "0.23.4",
            "{}",
            "completed",
            "manual",
            1.0,
            2.0,
        ),
    )
    pm.db.commit()

    results_dir = pm.current_project_dir / "results" / "exec_fastp2"
    results_dir.mkdir(parents=True, exist_ok=True)
    json_path = results_dir / "smp_fastp2.fastp.json"
    json_path.write_text(
        json.dumps(
            {
                "summary": {
                    "before_filtering": {"total_reads": 1000, "q30_rate": 0.9, "gc_content": 0.5},
                    "after_filtering": {"total_reads": 900, "q30_rate": 0.96, "gc_content": 0.49},
                },
                "filtering_result": {
                    "passed_filter_reads": 900,
                    "low_quality_reads": 40,
                    "too_short_reads": 30,
                    "too_many_N_reads": 10,
                },
            }
        ),
        encoding="utf-8",
    )
    (results_dir / "artifacts_manifest.json").write_text(
        json.dumps(
            {
                "execution_id": "exec_fastp2",
                "tool_id": "fastp",
                "output_dir": "/remote/fastp2",
                "artifacts": [
                    {
                        "name": "smp_fastp2.fastp.json",
                        "remote_path": "/remote/fastp2/smp_fastp2.fastp.json",
                        "local_path": str(json_path),
                        "available": True,
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    class _NoSSH:
        is_connected = False

        def download(self, remote_path, local_path):
            raise AssertionError("should not download in result path")

    class _Locator:
        project_manager = pm
        ssh_service = _NoSSH()

    service = ToolBridgeService(service_locator=_Locator(), plugin_registry=_build_plugin_registry())

    payload = service.get_results_for_execution("exec_fastp2")

    assert payload["status"] == "ok"
    assert payload["view"]["feature_id"] == "fastp"
    assert payload["view"]["archetype"] == "qc_report"
    assert payload["view"]["summary"][0]["value"] == "1,000"
    assert payload["view"]["provenance"]["local_result_dir"] == str(results_dir)
    pm.close()


def test_get_results_for_execution_builds_targeted_without_ssh(tmp_path: Path):
    pm = _build_project_manager(tmp_path)
    pm.db.execute(
        "INSERT INTO samples (sample_id, name, source, metadata) VALUES (?, ?, ?, ?)",
        ("smp_k2", "kraken sample", "test", "{}"),
    )
    pm.db.execute(
        "INSERT INTO executions (execution_id, sample_id, tool_id, tool_version, parameters, status, triggered_by, created_at, completed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "exec_k2_local",
            "smp_k2",
            "kraken2",
            "2.1.3",
            "{}",
            "completed",
            "manual",
            1.0,
            2.0,
        ),
    )
    pm.db.commit()

    results_dir = pm.current_project_dir / "results" / "exec_k2_local"
    results_dir.mkdir(parents=True, exist_ok=True)
    kreport_path = results_dir / "smp_k2.kreport"
    kreport_path.write_text(
        "\n".join(
            [
                "99.98\t787758\t787758\tU\t0\tunclassified",
                "0.02\t119\t0\tR\t1\troot",
                "0.02\t119\t0\tD\t2759\tEukaryota",
                "0.01\t96\t96\tS\t4932\tSaccharomyces cerevisiae",
            ]
        ),
        encoding="utf-8",
    )
    bracken_path = results_dir / "smp_k2.bracken.tsv"
    bracken_path.write_text(
        "\n".join(
            [
                "name\ttaxonomy_id\ttaxonomy_lvl\tkraken_assigned_reads\tadded_reads\tnew_est_reads\tfraction_total_reads",
                "Saccharomyces cerevisiae\t4932\tS\t50\t10\t60\t0.50",
            ]
        ),
        encoding="utf-8",
    )
    (results_dir / "artifacts_manifest.json").write_text(
        json.dumps(
            {
                "execution_id": "exec_k2_local",
                "tool_id": "kraken2",
                "output_dir": "/remote/k2",
                "artifacts": [
                    {
                        "name": "smp_k2.kreport",
                        "remote_path": "/remote/k2/smp_k2.kreport",
                        "local_path": str(kreport_path),
                        "available": True,
                    },
                    {
                        "name": "smp_k2.bracken.tsv",
                        "remote_path": "/remote/k2/smp_k2.bracken.tsv",
                        "local_path": str(bracken_path),
                        "available": True,
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    class _NoSSH:
        is_connected = False

        def download(self, remote_path, local_path):
            raise AssertionError("should not download in result path")

    class _Locator:
        project_manager = pm
        ssh_service = _NoSSH()

    service = ToolBridgeService(service_locator=_Locator(), plugin_registry=_build_plugin_registry())

    payload = service.get_results_for_execution("exec_k2_local")

    assert payload["status"] == "ok"
    assert payload["view"]["feature_id"] == "kraken2"
    assert payload["view"]["archetype"] == "taxonomy_profile"
    assert payload["view"]["table"]["title"] == "Bracken 丰度结果"
    assert payload["view"]["table"]["rows"][0]["name"] == "Saccharomyces cerevisiae"
    assert payload["view"]["provenance"]["execution_id"] == "exec_k2_local"
    pm.close()


def test_registered_plugins_have_result_archetype_mapping():
    service = ToolBridgeService(plugin_registry=_build_plugin_registry())

    tool_ids = service._plugin_registry.list_all_ids()
    mapped = {tool_id: service._resolve_result_archetype(tool_id) for tool_id in tool_ids}

    assert mapped["fastp"] == "qc_report"
    assert mapped["kraken2"] == "taxonomy_profile"
    assert mapped["quast"] == "quality_assessment"
    assert mapped["prokka"] == "annotation_table"
    assert mapped["wastewater_metagenomics_basic"] == "workflow_product"
    assert mapped["metabat2"] == "artifact_collection"
    assert mapped["krona"] == "html_report"


def test_get_results_for_execution_builds_quast_quality_view(tmp_path: Path):
    pm = _build_project_manager(tmp_path)
    registry = _build_plugin_registry()
    pm.db.execute(
        "INSERT INTO samples (sample_id, name, source, metadata) VALUES (?, ?, ?, ?)",
        ("smp_quast", "quast sample", "test", "{}"),
    )
    pm.db.execute(
        "INSERT INTO executions (execution_id, sample_id, tool_id, tool_version, parameters, status, triggered_by, created_at, completed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "exec_quast",
            "smp_quast",
            "quast",
            "5.2.0",
            json.dumps({"min_contig": 500}),
            "completed",
            "manual",
            1.0,
            2.0,
        ),
    )
    pm.db.commit()

    results_dir = pm.current_project_dir / "results" / "exec_quast"
    results_dir.mkdir(parents=True, exist_ok=True)
    report_path = results_dir / "smp_quast.quast.report.tsv"
    report_path.write_text(
        "\n".join(
            [
                "Assembly\t# contigs\tTotal length\tN50",
                "smp_quast\t12\t3456789\t80234",
            ]
        ),
        encoding="utf-8",
    )
    (results_dir / "artifacts_manifest.json").write_text(
        json.dumps(
            {
                "execution_id": "exec_quast",
                "tool_id": "quast",
                "output_dir": "/remote/quast",
                "artifacts": [
                    {
                        "name": "smp_quast.quast.report.tsv",
                        "remote_path": "/remote/quast/smp_quast.quast.report.tsv",
                        "local_path": str(report_path),
                        "available": True,
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    class _Locator:
        project_manager = pm

    service = ToolBridgeService(service_locator=_Locator(), plugin_registry=registry)

    payload = service.get_results_for_execution("exec_quast")

    assert payload["status"] == "ok"
    assert payload["view"]["archetype"] == "quality_assessment"
    assert payload["view"]["table"]["rows"][0]["N50"] == "80234"
    pm.close()


def test_get_results_for_execution_builds_hostile_qc_view(tmp_path: Path):
    pm = _build_project_manager(tmp_path)
    registry = _build_plugin_registry()
    pm.db.execute(
        "INSERT INTO samples (sample_id, name, source, metadata) VALUES (?, ?, ?, ?)",
        ("smp_host", "host sample", "test", "{}"),
    )
    pm.db.execute(
        "INSERT INTO executions (execution_id, sample_id, tool_id, tool_version, parameters, status, triggered_by, created_at, completed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "exec_hostile",
            "smp_host",
            "hostile",
            "1.1.0",
            json.dumps({"aligner": "bowtie2"}),
            "completed",
            "manual",
            1.0,
            2.0,
        ),
    )
    pm.db.commit()

    results_dir = pm.current_project_dir / "results" / "exec_hostile"
    results_dir.mkdir(parents=True, exist_ok=True)
    log_path = results_dir / "hostile_log.json"
    log_path.write_text(
        json.dumps(
            {
                "total_reads": 1000,
                "host_reads": 250,
                "non_host_reads": 750,
                "host_fraction": "25.0%",
            }
        ),
        encoding="utf-8",
    )
    (results_dir / "artifacts_manifest.json").write_text(
        json.dumps(
            {
                "execution_id": "exec_hostile",
                "tool_id": "hostile",
                "output_dir": "/remote/hostile",
                "artifacts": [
                    {
                        "name": "hostile_log.json",
                        "remote_path": "/remote/hostile/hostile_log.json",
                        "local_path": str(log_path),
                        "available": True,
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    class _Locator:
        project_manager = pm

    service = ToolBridgeService(service_locator=_Locator(), plugin_registry=registry)

    payload = service.get_results_for_execution("exec_hostile")

    assert payload["status"] == "ok"
    assert payload["view"]["archetype"] == "qc_report"
    assert "Reads" in payload["view"]["summary"][0]["label"]
    assert payload["view"]["table"]["rows"][0]["total_reads"] == 1000
    pm.close()


def test_get_results_for_execution_builds_workflow_product_with_sections(tmp_path: Path):
    pm = _build_project_manager(tmp_path)
    registry = _build_plugin_registry()
    pm.db.execute(
        "INSERT INTO samples (sample_id, name, source, metadata) VALUES (?, ?, ?, ?)",
        ("smp_waste", "waste sample", "test", "{}"),
    )
    pm.db.execute(
        "INSERT INTO executions (execution_id, sample_id, tool_id, tool_version, parameters, status, triggered_by, created_at, completed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "exec_waste",
            "smp_waste",
            "wastewater_metagenomics_basic",
            "1.0.0",
            json.dumps({"confidence": 0.1}),
            "completed",
            "manual",
            1.0,
            2.0,
        ),
    )
    pm.db.commit()

    results_dir = pm.current_project_dir / "results" / "exec_waste"
    results_dir.mkdir(parents=True, exist_ok=True)
    fastp_json = results_dir / "smp_waste.fastp.json"
    fastp_json.write_text(
        json.dumps(
            {
                "summary": {
                    "before_filtering": {"total_reads": 1000, "q30_rate": 0.9, "gc_content": 0.5},
                    "after_filtering": {"total_reads": 900, "q30_rate": 0.96, "gc_content": 0.49},
                },
                "filtering_result": {
                    "passed_filter_reads": 900,
                    "low_quality_reads": 40,
                    "too_short_reads": 30,
                    "too_many_N_reads": 10,
                },
            }
        ),
        encoding="utf-8",
    )
    kreport = results_dir / "smp_waste.kreport"
    kreport.write_text(
        "\n".join(
            [
                "99.98\t787758\t787758\tU\t0\tunclassified",
                "0.02\t119\t0\tR\t1\troot",
                "0.02\t119\t0\tD\t2759\tEukaryota",
                "0.01\t96\t96\tS\t4932\tSaccharomyces cerevisiae",
            ]
        ),
        encoding="utf-8",
    )
    bracken = results_dir / "smp_waste.bracken.tsv"
    bracken.write_text(
        "\n".join(
            [
                "name\ttaxonomy_id\ttaxonomy_lvl\tkraken_assigned_reads\tadded_reads\tnew_est_reads\tfraction_total_reads",
                "Saccharomyces cerevisiae\t4932\tS\t50\t10\t60\t0.50",
            ]
        ),
        encoding="utf-8",
    )
    krona = results_dir / "smp_waste.krona.html"
    krona.write_text("<html><body>Krona</body></html>", encoding="utf-8")
    (results_dir / "artifacts_manifest.json").write_text(
        json.dumps(
            {
                "execution_id": "exec_waste",
                "tool_id": "wastewater_metagenomics_basic",
                "output_dir": "/remote/waste",
                "artifacts": [
                    {"name": "smp_waste.fastp.json", "remote_path": "/remote/waste/smp_waste.fastp.json", "local_path": str(fastp_json), "available": True},
                    {"name": "smp_waste.kreport", "remote_path": "/remote/waste/smp_waste.kreport", "local_path": str(kreport), "available": True},
                    {"name": "smp_waste.bracken.tsv", "remote_path": "/remote/waste/smp_waste.bracken.tsv", "local_path": str(bracken), "available": True},
                    {"name": "smp_waste.krona.html", "remote_path": "/remote/waste/smp_waste.krona.html", "local_path": str(krona), "available": True},
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    class _Locator:
        project_manager = pm

    service = ToolBridgeService(service_locator=_Locator(), plugin_registry=registry)

    payload = service.get_results_for_execution("exec_waste")

    assert payload["status"] == "ok"
    assert payload["view"]["feature_id"] == "wastewater_metagenomics_basic"
    assert payload["view"]["archetype"] == "workflow_product"
    assert len(payload["view"]["sections"]) >= 2
    assert payload["view"]["sections"][0]["section_id"] == "fastp"
    pm.close()


def test_get_results_for_execution_builds_explicit_artifact_collection(tmp_path: Path):
    pm = _build_project_manager(tmp_path)
    registry = _build_plugin_registry()
    pm.db.execute(
        "INSERT INTO samples (sample_id, name, source, metadata) VALUES (?, ?, ?, ?)",
        ("smp_bin", "bin sample", "test", "{}"),
    )
    pm.db.execute(
        "INSERT INTO executions (execution_id, sample_id, tool_id, tool_version, parameters, status, triggered_by, created_at, completed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "exec_metabat",
            "smp_bin",
            "metabat2",
            "2.15",
            "{}",
            "completed",
            "manual",
            1.0,
            2.0,
        ),
    )
    pm.db.commit()

    results_dir = pm.current_project_dir / "results" / "exec_metabat"
    results_dir.mkdir(parents=True, exist_ok=True)
    bins_dir = results_dir / "bins"
    bins_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "artifacts_manifest.json").write_text(
        json.dumps(
            {
                "execution_id": "exec_metabat",
                "tool_id": "metabat2",
                "output_dir": "/remote/metabat",
                "artifacts": [
                    {
                        "name": "bins",
                        "remote_path": "/remote/metabat/bins",
                        "local_path": str(bins_dir),
                        "available": True,
                        "type": "directory",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    class _Locator:
        project_manager = pm

    service = ToolBridgeService(service_locator=_Locator(), plugin_registry=registry)

    payload = service.get_results_for_execution("exec_metabat")

    assert payload["status"] == "ok"
    assert payload["view"]["archetype"] == "artifact_collection"
    assert payload["view"]["summary"][0]["label"] == "已同步文件"
    pm.close()


def test_all_registered_tools_have_result_archetype():
    registry = _build_plugin_registry()
    service = ToolBridgeService(plugin_registry=registry)

    missing = []
    for tool_id in registry.list_all_ids():
        try:
            archetype = service._resolve_result_archetype(tool_id)
        except Exception:
            missing.append(tool_id)
            continue
        assert archetype

    assert missing == []


def test_get_results_for_execution_builds_checkm2_quality_view(tmp_path: Path):
    pm = _build_project_manager(tmp_path)
    registry = _build_plugin_registry()
    pm.db.execute(
        "INSERT INTO samples (sample_id, name, source, metadata) VALUES (?, ?, ?, ?)",
        ("smp_mag", "mag sample", "test", "{}"),
    )
    pm.db.execute(
        "INSERT INTO executions (execution_id, sample_id, tool_id, tool_version, parameters, status, triggered_by, created_at, completed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("exec_checkm2", "smp_mag", "checkm2", "1.0.2", json.dumps({"threads": 8}), "completed", "manual", 1.0, 2.0),
    )
    pm.db.commit()

    results_dir = pm.current_project_dir / "results" / "exec_checkm2"
    results_dir.mkdir(parents=True, exist_ok=True)
    report_path = results_dir / "smp_mag.checkm2_quality.tsv"
    report_path.write_text(
        "\n".join(
            [
                "Name\tCompleteness\tContamination\tGenome_Size\tGC_Content",
                "bin.1\t97.5\t1.2\t2500000\t50.1",
            ]
        ),
        encoding="utf-8",
    )
    (results_dir / "artifacts_manifest.json").write_text(
        json.dumps(
            {
                "execution_id": "exec_checkm2",
                "tool_id": "checkm2",
                "output_dir": "/remote/checkm2",
                "artifacts": [
                    {
                        "name": "smp_mag.checkm2_quality.tsv",
                        "remote_path": "/remote/checkm2/smp_mag.checkm2_quality.tsv",
                        "local_path": str(report_path),
                        "available": True,
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    class _Locator:
        project_manager = pm

    service = ToolBridgeService(service_locator=_Locator(), plugin_registry=registry)
    payload = service.get_results_for_execution("exec_checkm2")

    assert payload["status"] == "ok"
    assert payload["view"]["archetype"] == "quality_assessment"
    assert payload["view"]["table"]["rows"][0]["Name"] == "bin.1"
    assert any(item["label"] == "Completeness" for item in payload["view"]["summary"])
    pm.close()


def test_get_results_for_execution_builds_abricate_annotation_view(tmp_path: Path):
    pm = _build_project_manager(tmp_path)
    registry = _build_plugin_registry()
    pm.db.execute(
        "INSERT INTO samples (sample_id, name, source, metadata) VALUES (?, ?, ?, ?)",
        ("smp_amr", "amr sample", "test", "{}"),
    )
    pm.db.execute(
        "INSERT INTO executions (execution_id, sample_id, tool_id, tool_version, parameters, status, triggered_by, created_at, completed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("exec_abricate", "smp_amr", "abricate", "1.0.1", json.dumps({"database": "ncbi"}), "completed", "manual", 1.0, 2.0),
    )
    pm.db.commit()

    results_dir = pm.current_project_dir / "results" / "exec_abricate"
    results_dir.mkdir(parents=True, exist_ok=True)
    hits_path = results_dir / "smp_amr.abricate.tsv"
    hits_path.write_text(
        "\n".join(
            [
                "GENE\tDATABASE\t%IDENTITY\t%COVERAGE",
                "blaTEM\tncbi\t99.5\t100.0",
            ]
        ),
        encoding="utf-8",
    )
    (results_dir / "artifacts_manifest.json").write_text(
        json.dumps(
            {
                "execution_id": "exec_abricate",
                "tool_id": "abricate",
                "output_dir": "/remote/abricate",
                "artifacts": [
                    {
                        "name": "smp_amr.abricate.tsv",
                        "remote_path": "/remote/abricate/smp_amr.abricate.tsv",
                        "local_path": str(hits_path),
                        "available": True,
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    class _Locator:
        project_manager = pm

    service = ToolBridgeService(service_locator=_Locator(), plugin_registry=registry)
    payload = service.get_results_for_execution("exec_abricate")

    assert payload["status"] == "ok"
    assert payload["view"]["archetype"] == "annotation_table"
    assert payload["view"]["table"]["rows"][0]["GENE"] == "blaTEM"
    pm.close()


def test_get_results_for_execution_builds_krona_html_view(tmp_path: Path):
    pm = _build_project_manager(tmp_path)
    registry = _build_plugin_registry()
    pm.db.execute(
        "INSERT INTO samples (sample_id, name, source, metadata) VALUES (?, ?, ?, ?)",
        ("smp_html", "html sample", "test", "{}"),
    )
    pm.db.execute(
        "INSERT INTO executions (execution_id, sample_id, tool_id, tool_version, parameters, status, triggered_by, created_at, completed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("exec_krona", "smp_html", "krona", "2.8", "{}", "completed", "manual", 1.0, 2.0),
    )
    pm.db.commit()

    results_dir = pm.current_project_dir / "results" / "exec_krona"
    results_dir.mkdir(parents=True, exist_ok=True)
    html_path = results_dir / "smp_html.krona.html"
    html_path.write_text("<html><body>krona</body></html>", encoding="utf-8")
    (results_dir / "artifacts_manifest.json").write_text(
        json.dumps(
            {
                "execution_id": "exec_krona",
                "tool_id": "krona",
                "output_dir": "/remote/krona",
                "artifacts": [
                    {
                        "name": "smp_html.krona.html",
                        "remote_path": "/remote/krona/smp_html.krona.html",
                        "local_path": str(html_path),
                        "available": True,
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    class _Locator:
        project_manager = pm

    service = ToolBridgeService(service_locator=_Locator(), plugin_registry=registry)
    payload = service.get_results_for_execution("exec_krona")

    assert payload["status"] == "ok"
    assert payload["view"]["archetype"] == "html_report"
    assert payload["view"]["artifacts"][0]["name"] == "smp_html.krona.html"
    pm.close()


def test_get_results_for_execution_builds_artifact_collection_view(tmp_path: Path):
    pm = _build_project_manager(tmp_path)
    registry = _build_plugin_registry()
    pm.db.execute(
        "INSERT INTO samples (sample_id, name, source, metadata) VALUES (?, ?, ?, ?)",
        ("smp_bins", "bins sample", "test", "{}"),
    )
    pm.db.execute(
        "INSERT INTO executions (execution_id, sample_id, tool_id, tool_version, parameters, status, triggered_by, created_at, completed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("exec_bins", "smp_bins", "metabat2", "2.15", "{}", "completed", "manual", 1.0, 2.0),
    )
    pm.db.commit()

    results_dir = pm.current_project_dir / "results" / "exec_bins"
    results_dir.mkdir(parents=True, exist_ok=True)
    bin_path = results_dir / "bin.1.fa"
    bin_path.write_text(">bin1\nATGC\n", encoding="utf-8")
    (results_dir / "artifacts_manifest.json").write_text(
        json.dumps(
            {
                "execution_id": "exec_bins",
                "tool_id": "metabat2",
                "output_dir": "/remote/metabat2",
                "artifacts": [
                    {
                        "name": "bin.1.fa",
                        "remote_path": "/remote/metabat2/bin.1.fa",
                        "local_path": str(bin_path),
                        "available": True,
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    class _Locator:
        project_manager = pm

    service = ToolBridgeService(service_locator=_Locator(), plugin_registry=registry)
    payload = service.get_results_for_execution("exec_bins")

    assert payload["status"] == "ok"
    assert payload["view"]["archetype"] == "artifact_collection"
    assert payload["view"]["summary"][0]["label"] == "已同步文件"
    pm.close()


def test_get_results_for_execution_builds_workflow_sections(tmp_path: Path):
    pm = _build_project_manager(tmp_path)
    registry = _build_plugin_registry()
    pm.db.execute(
        "INSERT INTO samples (sample_id, name, source, metadata) VALUES (?, ?, ?, ?)",
        ("smp_wf", "wf sample", "test", "{}"),
    )
    pm.db.execute(
        "INSERT INTO executions (execution_id, sample_id, tool_id, tool_version, parameters, status, triggered_by, created_at, completed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("exec_wf", "smp_wf", "wastewater_metagenomics_basic", "1.0.0", json.dumps({"threads": 8}), "completed", "manual", 1.0, 2.0),
    )
    pm.db.commit()

    results_dir = pm.current_project_dir / "results" / "exec_wf"
    results_dir.mkdir(parents=True, exist_ok=True)
    fastp_json = results_dir / "smp_wf.fastp.json"
    fastp_json.write_text(
        json.dumps(
            {
                "summary": {
                    "before_filtering": {"total_reads": 1000, "q30_rate": 0.9, "gc_content": 0.5},
                    "after_filtering": {"total_reads": 900, "q30_rate": 0.96, "gc_content": 0.48},
                },
                "filtering_result": {"passed_filter_reads": 900},
            }
        ),
        encoding="utf-8",
    )
    kreport = results_dir / "smp_wf.kreport"
    kreport.write_text(
        "\n".join(
            [
                "99.98\t787758\t787758\tU\t0\tunclassified",
                "0.02\t119\t0\tR\t1\troot",
                "0.02\t119\t0\tD\t2759\tEukaryota",
                "0.01\t96\t96\tS\t4932\tSaccharomyces cerevisiae",
            ]
        ),
        encoding="utf-8",
    )
    bracken = results_dir / "smp_wf.bracken.tsv"
    bracken.write_text(
        "\n".join(
            [
                "name\ttaxonomy_id\ttaxonomy_lvl\tkraken_assigned_reads\tadded_reads\tnew_est_reads\tfraction_total_reads",
                "Saccharomyces cerevisiae\t4932\tS\t50\t10\t60\t0.50",
            ]
        ),
        encoding="utf-8",
    )
    krona = results_dir / "smp_wf.krona.html"
    krona.write_text("<html><body>wf</body></html>", encoding="utf-8")
    (results_dir / "artifacts_manifest.json").write_text(
        json.dumps(
            {
                "execution_id": "exec_wf",
                "tool_id": "wastewater_metagenomics_basic",
                "output_dir": "/remote/wf",
                "artifacts": [
                    {"name": "smp_wf.fastp.json", "remote_path": "/remote/wf/smp_wf.fastp.json", "local_path": str(fastp_json), "available": True},
                    {"name": "smp_wf.kreport", "remote_path": "/remote/wf/smp_wf.kreport", "local_path": str(kreport), "available": True},
                    {"name": "smp_wf.bracken.tsv", "remote_path": "/remote/wf/smp_wf.bracken.tsv", "local_path": str(bracken), "available": True},
                    {"name": "smp_wf.krona.html", "remote_path": "/remote/wf/smp_wf.krona.html", "local_path": str(krona), "available": True},
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    class _Locator:
        project_manager = pm

    service = ToolBridgeService(service_locator=_Locator(), plugin_registry=registry)
    payload = service.get_results_for_execution("exec_wf")

    assert payload["status"] == "ok"
    assert payload["view"]["feature_id"] == "wastewater_metagenomics_basic"
    assert payload["view"]["archetype"] == "workflow_product"
    assert len(payload["view"]["sections"]) >= 2
    assert payload["view"]["sections"][0]["section_id"] in {"fastp", "qc"}
    assert payload["view"]["provenance"]["execution_id"] == "exec_wf"
    pm.close()
