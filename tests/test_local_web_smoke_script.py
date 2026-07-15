from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_local_web_smoke_script_is_exposed_from_web_package() -> None:
    package = json.loads((REPO_ROOT / "apps" / "web" / "package.json").read_text(encoding="utf-8"))

    assert package["scripts"]["smoke:local"] == "powershell -ExecutionPolicy Bypass -File ../../scripts/local_web_smoke.ps1"


def test_local_web_smoke_checks_api_routes_web_routes_and_next_assets() -> None:
    source = (REPO_ROOT / "scripts" / "local_web_smoke.ps1").read_text(encoding="utf-8")

    assert "$ApiBase/health" in source
    assert "$ApiBase/api/v1/service-info" in source
    assert "$ApiBase/api/v1/workflow-catalog" in source
    assert "$ApiBase/api/v1/tools" in source
    assert "$ApiBase/api/v1/databases" in source
    assert 'Path = "/workflows"' in source
    assert 'Path = "/workflows/databases"' in source
    assert 'Path = "/workflows/tools"' in source
    assert 'Path = "/workflows/detail?workflow=generated-tool-run-v1"' in source
    assert 'Path = "/workflows/results"' in source
    assert "app/workflows/page.js" in source
    assert "app/workflows/databases/page.js" in source
    assert "app/workflows/tools/page.js" in source
    assert "app/workflows/detail/page.js" in source
    assert "generated-tool-run-v1" in source
    assert "app/workflows/results/page.js" in source
    assert "Assert-NextStaticAsset" in source
    assert 'Assert-NextStaticAsset $firstPage "CSS"' in source
    assert 'Assert-NextStaticAsset $firstPage "JS"' in source
    assert "/_next/static/(?:chunks|app)/" in source
    assert "LOCAL_WEB_SMOKE_FAILED" in source
