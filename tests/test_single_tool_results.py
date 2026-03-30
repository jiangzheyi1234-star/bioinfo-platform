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
        "get_fastp_results_for_execution",
        lambda execution_id: {"status": "ok", "view": {"feature_id": "fastp", "execution_id": execution_id}},
    )

    payload = service.get_results_for_execution("exec_fastp")

    assert payload["status"] == "ok"
    assert payload["view"]["execution_id"] == "exec_fastp"


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
    assert payload["view"]["summary"][0]["label"] == "CDS"
    assert payload["view"]["rows"][0]["organism"] == "Demo bacterium"
    assert payload["view"]["artifacts"][0]["available"] is True
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
        "get_targeted_seq_results_for_execution",
        lambda execution_id: {"status": "ok", "view": {"feature_id": "targeted_sequencing", "execution_id": execution_id}},
    )

    payload = service.get_results_for_execution("exec_kraken2")

    assert payload["status"] == "ok"
    assert payload["view"]["feature_id"] == "targeted_sequencing"
