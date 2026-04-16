from __future__ import annotations

import config

from core.app_runtime.service import RuntimeService


def test_merge_settings_patch_accepts_extended_runtime_resolved_fields() -> None:
    current = config.default_settings_schema()

    merged = RuntimeService._merge_settings_patch(
        current,
        {
            "runtime": {
                "resolved": {
                    "project_id": "proj_demo",
                    "task_id": "task_prepare",
                    "pipeline_id": "nf_rnaseq",
                    "pipeline_entry": "/srv/h2ometa/pipelines/nf_rnaseq/main.nf",
                    "pipeline_repo_dir": "/srv/h2ometa/pipelines",
                    "project_dir": "/srv/h2ometa/projects/proj_demo",
                    "work_dir": "/srv/h2ometa/projects/proj_demo/work",
                    "results_dir": "/srv/h2ometa/projects/proj_demo/results",
                }
            }
        },
    )

    resolved = merged["runtime"]["resolved"]
    assert resolved["project_id"] == "proj_demo"
    assert resolved["task_id"] == "task_prepare"
    assert resolved["pipeline_id"] == "nf_rnaseq"
    assert resolved["pipeline_entry"] == "/srv/h2ometa/pipelines/nf_rnaseq/main.nf"
    assert resolved["pipeline_repo_dir"] == "/srv/h2ometa/pipelines"
    assert resolved["project_dir"] == "/srv/h2ometa/projects/proj_demo"
    assert resolved["work_dir"] == "/srv/h2ometa/projects/proj_demo/work"
    assert resolved["results_dir"] == "/srv/h2ometa/projects/proj_demo/results"
