from core.workflow.bootstrap_ops import build_workflow_runtime_progress


def test_docker_runtime_progress_uses_step_markers_from_log() -> None:
    progress = build_workflow_runtime_progress(
        profile_kind="personal_docker",
        stage="running",
        log_text="\n".join(
            [
                "STEP=java:done",
                "STEP=docker:done",
                "STEP=nextflow:failed",
                "ERROR=nextflow requires Java 17-24",
            ]
        ),
    )
    assert progress["steps"][0]["key"] == "java"
    assert progress["steps"][0]["status"] == "done"
    assert progress["steps"][2]["key"] == "nextflow"
    assert progress["steps"][2]["status"] == "failed"


def test_failed_terminal_state_marks_running_step_failed() -> None:
    progress = build_workflow_runtime_progress(
        profile_kind="personal_docker",
        stage="failed",
        log_text="\n".join(
            [
                "STEP=java:done",
                "STEP=docker:done",
                "STEP=nextflow:running",
            ]
        ),
    )
    assert progress["steps"][2]["status"] == "failed"
    assert progress["steps"][3]["status"] == "pending"
