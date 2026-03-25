from __future__ import annotations

from pathlib import Path

from core.execution.artifact_store import ArtifactStore


def test_persist_and_load_execution_artifacts(tmp_path: Path):
    project_dir = tmp_path / "project"
    project_dir.mkdir(parents=True, exist_ok=True)
    store = ArtifactStore(lambda: project_dir)

    src = tmp_path / "source.txt"
    src.write_text("line1\nline2\n", encoding="utf-8")
    artifacts = [
        {
            "name": "primer_result_final_2.txt",
            "remote_path": "/remote/primer_result_final_2.txt",
            "local_path": str(src),
            "available": True,
        }
    ]

    persisted = store.persist_execution_artifacts(
        execution_id="exec_1",
        tool_id="primer_design",
        output_dir="/remote/out",
        artifacts=artifacts,
    )
    assert persisted and persisted[0]["available"] is True

    loaded = store.list_local_execution_artifacts("exec_1")
    assert loaded and loaded[0]["name"] == "primer_result_final_2.txt"
    assert Path(loaded[0]["local_path"]).exists()


def test_read_and_count_local_artifact_lines(tmp_path: Path):
    artifact_file = tmp_path / "result.txt"
    artifact_file.write_text("a\n\nb\n", encoding="utf-8")
    artifacts = [{"name": "result.txt", "local_path": str(artifact_file), "available": True}]

    content = ArtifactStore.read_local_artifact_text(artifacts, "result.txt")
    assert "a" in content and "b" in content
    assert ArtifactStore.count_local_artifact_lines(artifacts, "result.txt") == 2
