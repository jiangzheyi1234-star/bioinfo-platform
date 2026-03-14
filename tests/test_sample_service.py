import json
from pathlib import Path

from core.data.project_manager import ProjectManager
from core.data.sample_service import SampleService


def _make_service(tmp_path: Path) -> tuple[ProjectManager, SampleService]:
    pm = ProjectManager(
        projects_root=tmp_path / "projects",
        index_path=tmp_path / "projects.json",
    )
    project_id = pm.create_project("sample service", "tests")
    pm.open_project(project_id)
    return pm, SampleService(pm.db)


def test_list_sample_cards_aggregates_latest_stage_statuses(tmp_path: Path) -> None:
    pm, service = _make_service(tmp_path)
    try:
        pm.db.execute(
            "INSERT INTO samples (sample_id, name, source, metadata) VALUES (?, ?, ?, ?)",
            ("smp_1", "alpha", "river", json.dumps({"r1": "alpha_R1.fastq.gz"})),
        )
        pm.db.executemany(
            "INSERT INTO executions (execution_id, sample_id, tool_id, parameters, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("exec_1", "smp_1", "fastp", "{}", "running", 100.0),
                ("exec_2", "smp_1", "fastp", "{}", "completed", 200.0),
                ("exec_3", "smp_1", "kraken2", "{}", "failed", 150.0),
            ],
        )
        pm.db.commit()

        cards = service.list_sample_cards()

        assert len(cards) == 1
        assert cards[0].sample_id == "smp_1"
        assert cards[0].metadata["r1"] == "alpha_R1.fastq.gz"
        assert cards[0].stage_statuses == {"fastp": "completed", "kraken2": "failed"}
        assert cards[0].last_activity == 200.0
    finally:
        pm.close()


def test_list_sample_cards_applies_search_before_loading_snapshots(tmp_path: Path) -> None:
    pm, service = _make_service(tmp_path)
    try:
        pm.db.executemany(
            "INSERT INTO samples (sample_id, name, source, metadata) VALUES (?, ?, ?, ?)",
            [
                ("smp_1", "alpha", "river", "{}"),
                ("smp_2", "beta", "soil", "{}"),
            ],
        )
        pm.db.executemany(
            "INSERT INTO executions (execution_id, sample_id, tool_id, parameters, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("exec_1", "smp_1", "fastp", "{}", "completed", 100.0),
                ("exec_2", "smp_2", "fastp", "{}", "failed", 200.0),
            ],
        )
        pm.db.commit()

        cards = service.list_sample_cards("alp")

        assert [card.sample_id for card in cards] == ["smp_1"]
        assert cards[0].stage_statuses == {"fastp": "completed"}
        assert cards[0].last_activity == 100.0
    finally:
        pm.close()
