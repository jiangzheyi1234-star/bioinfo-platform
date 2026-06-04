from __future__ import annotations

from pathlib import Path

import pytest

from apps.remote_runner.pipeline import PipelineNotFoundError, get_pipeline
from tests.helpers.reference_database import make_configured_remote_runner


def test_missing_pipeline_raises_domain_not_found_error(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)

    with pytest.raises(PipelineNotFoundError) as raised:
        get_pipeline(cfg, "missing-pipeline-v1")

    assert str(raised.value) == "PIPELINE_NOT_FOUND"
    assert raised.value.status_code == 404
