from __future__ import annotations

import asyncio

from apps.api.execution_query_routes import export_result_package, get_result_audit


def test_result_package_routes_preserve_runtime_wrappers(monkeypatch) -> None:
    monkeypatch.setattr("apps.api.execution_query_service.runtime_service", lambda: FakeResultPackageRuntime())

    audit = asyncio.run(get_result_audit("res_run_demo"))
    package = asyncio.run(export_result_package("res_run_demo"))

    assert audit == {"data": {"resultId": "res_run_demo", "status": "passed"}}
    assert package == {
        "data": {
            "resultId": "res_run_demo",
            "packageUri": "file:///tmp/res_run_demo.zip",
            "sha256": "a" * 64,
        }
    }


class FakeResultPackageRuntime:
    def get_result_audit(self, result_id):
        assert result_id == "res_run_demo"
        return {"data": {"resultId": result_id, "status": "passed"}}

    def export_result_package(self, result_id):
        assert result_id == "res_run_demo"
        return {
            "data": {
                "resultId": result_id,
                "packageUri": "file:///tmp/res_run_demo.zip",
                "sha256": "a" * 64,
            }
        }
