from __future__ import annotations

from pathlib import Path


ROOT_PAGE = Path(__file__).resolve().parents[1] / "apps" / "web" / "app" / "page.tsx"
WORKBENCH = (
    Path(__file__).resolve().parents[1]
    / "apps"
    / "web"
    / "app"
    / "components"
    / "file-summary-workbench.tsx"
)


def test_home_page_mounts_file_summary_workbench() -> None:
    source = ROOT_PAGE.read_text(encoding="utf-8")

    assert "FileSummaryWorkbench" in source
    assert 'redirect("/servers")' not in source


def test_file_summary_workbench_uses_real_remote_runner_flow() -> None:
    source = WORKBENCH.read_text(encoding="utf-8")

    assert '"/api/v1/uploads"' in source
    assert '"/api/v1/runs"' in source
    assert '"file-summary-v1"' in source
    assert "upload.uploadId" in source
    assert "`/api/v1/runs/${runId}/results`" in source
    assert "`/api/v1/results/${resultId}/preview?artifact_id=${encodeURIComponent(summary.artifactId)}`" in source
