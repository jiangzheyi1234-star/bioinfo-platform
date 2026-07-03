from __future__ import annotations

from pathlib import Path

from scripts.generate_local_api_openapi_types import OUTPUT_PATH, generate_types


def test_local_api_openapi_types_are_generated_from_fastapi_schema() -> None:
    generated = generate_types()
    existing = Path(OUTPUT_PATH).read_text(encoding="utf-8")

    assert existing == generated
    assert 'export type LocalApiRunSubmitRequest = LocalApiSchemas["RunSubmitRequest"];' in existing
    assert "serverId: string;" in existing
    assert "runSpec: LocalApiSchemas[\"RunSpecRequest\"];" in existing
    assert "requestId?: string | null;" in existing
    assert "WorkflowDesignDraftCreateRequest" in existing
