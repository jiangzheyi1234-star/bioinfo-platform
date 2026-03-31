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


def test_normalize_artifacts_adds_typed_metadata(tmp_path: Path):
    artifact_file = tmp_path / "report.html"
    artifact_file.write_text("<html></html>", encoding="utf-8")

    normalized = ArtifactStore.normalize_artifacts(
        [
            {
                "name": "report.html",
                "local_path": str(artifact_file),
                "available": True,
            }
        ]
    )

    assert normalized[0]["artifact_type"] == "html"
    assert normalized[0]["display_role"] in {"report", "primary_result"}
    assert normalized[0]["viewer_hint"] == "html"


def test_normalize_artifacts_rejects_invalid_metadata():
    try:
        ArtifactStore.normalize_artifacts(
            [
                {
                    "name": "bad.txt",
                    "artifact_type": "spreadsheet",
                    "display_role": "primary_result",
                    "viewer_hint": "text",
                }
            ]
        )
    except RuntimeError as exc:
        assert "Invalid artifact_type" in str(exc)
    else:
        raise AssertionError("normalize_artifacts should loudly reject invalid metadata")


def test_persist_execution_artifacts_preserves_explicit_typed_metadata(tmp_path: Path):
    project_dir = tmp_path / "project"
    project_dir.mkdir(parents=True, exist_ok=True)
    store = ArtifactStore(lambda: project_dir)

    src = tmp_path / "custom.txt"
    src.write_text("payload\n", encoding="utf-8")
    artifacts = [
        {
            "name": "custom.txt",
            "remote_path": "/remote/custom.txt",
            "local_path": str(src),
            "available": True,
            "artifact_type": "text",
            "display_role": "primary_result",
            "viewer_hint": "table",
        }
    ]

    persisted = store.persist_execution_artifacts(
        execution_id="exec_meta",
        tool_id="custom_tool",
        output_dir="/remote/out",
        artifacts=artifacts,
    )
    loaded = store.list_local_execution_artifacts("exec_meta")

    assert persisted[0]["artifact_type"] == "text"
    assert persisted[0]["display_role"] == "primary_result"
    assert persisted[0]["viewer_hint"] == "table"
    assert loaded[0]["artifact_type"] == "text"
    assert loaded[0]["display_role"] == "primary_result"
    assert loaded[0]["viewer_hint"] == "table"
