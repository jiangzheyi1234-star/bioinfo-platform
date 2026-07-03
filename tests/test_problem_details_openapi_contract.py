from __future__ import annotations

from typing import Any

from core.contracts.problem_details import PROBLEM_DETAIL_MEDIA_TYPE


def test_local_and_remote_openapi_declare_problem_details_responses() -> None:
    from apps.api.main import app as local_app
    from apps.remote_runner.main import app as remote_app

    for app, path, method in (
        (local_app, "/api/v1/tools/prepare-jobs", "post"),
        (remote_app, "/api/v1/tools/prepare-jobs", "post"),
    ):
        schema = app.openapi()
        assert "ProblemDetail" in schema["components"]["schemas"]
        response = _operation(schema, path, method)["responses"]["400"]
        assert list(response["content"]) == [PROBLEM_DETAIL_MEDIA_TYPE]
        assert response["content"][PROBLEM_DETAIL_MEDIA_TYPE]["schema"] == {
            "$ref": "#/components/schemas/ProblemDetail"
        }


def _operation(schema: dict[str, Any], path: str, method: str) -> dict[str, Any]:
    return schema["paths"][path][method]
