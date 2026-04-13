import asyncio

from apps.api.main import get_workflow_tool_descriptor


class _RuntimeStub:
    def get_tool_descriptor(self, *, tool_id: str):
        return {
            "id": tool_id,
            "name": "fastp",
            "workflow_support": {
                "support_level": "Production Ready",
                "workflow_ready": True,
                "validation_errors": [],
                "runtime": {
                    "container": "quay.io/biocontainers/fastp:0.23.4",
                    "conda": "fastp=0.23.4",
                    "conda_env_name": "fastp_env",
                },
            },
        }


def test_workflow_tool_descriptor_handler_returns_runtime_metadata(monkeypatch):
    monkeypatch.setattr("apps.api.main._runtime", lambda: _RuntimeStub())

    payload = asyncio.run(get_workflow_tool_descriptor("fastp"))

    assert payload["item"]["id"] == "fastp"
    assert payload["item"]["workflow_support"]["support_level"] == "Production Ready"
    assert payload["item"]["workflow_support"]["runtime"]["conda_env_name"] == "fastp_env"
