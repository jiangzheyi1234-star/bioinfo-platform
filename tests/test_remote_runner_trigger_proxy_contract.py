from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_remote_runner_trigger_client_and_proxy_keep_response_shapes() -> None:
    client_source = _source("core/remote_runner/client.py")
    proxy_source = _source("core/remote_runner/proxy.py")

    assert 'def list_workflow_triggers(self) -> dict[str, Any]:' in client_source
    assert 'return self.get_json("/api/v1/workflow-triggers")["data"]' in client_source
    assert 'def create_workflow_trigger(self, payload: dict[str, Any]) -> dict[str, Any]:' in client_source
    assert 'return self.post_json("/api/v1/workflow-triggers", payload)["data"]' in client_source
    assert "def submit_workflow_trigger_event(self, trigger_id: str, payload: dict[str, Any])" in client_source
    assert 'return self.post_json(f"/api/v1/workflow-triggers/{trigger_id}/events", payload)' in client_source
    assert "def submit_workflow_trigger_inbox_event(self, trigger_id: str, payload: dict[str, Any])" in client_source
    assert 'return self.post_json(f"/api/v1/workflow-triggers/{trigger_id}/inbox", payload)' in client_source
    assert "def submit_workflow_trigger_readiness_event(self, trigger_id: str, payload: dict[str, Any])" in client_source
    assert 'return self.post_json(f"/api/v1/workflow-triggers/{trigger_id}/readiness", payload)' in client_source
    assert "def preview_workflow_trigger_backfill(self, trigger_id: str, payload: dict[str, Any])" in client_source
    assert 'return self.post_json(f"/api/v1/workflow-triggers/{trigger_id}/backfill/preview", payload)' in client_source
    assert "def launch_workflow_trigger_backfill(self, trigger_id: str, payload: dict[str, Any])" in client_source
    assert 'return self.post_json(f"/api/v1/workflow-triggers/{trigger_id}/backfill/launch", payload)' in client_source
    assert 'def list_workflow_trigger_events(self, trigger_id: str) -> dict[str, Any]:' in client_source
    assert "def list_workflow_trigger_inbox_events(" in client_source
    assert 'return self.get_json(f"/api/v1/workflow-triggers/{trigger_id}/inbox?{query}")["data"]' in client_source
    assert "def list_workflow_backfill_launches(" in client_source
    assert 'return self.get_json(f"/api/v1/workflow-backfill-launches?{query}")["data"]' in client_source
    assert "def get_workflow_backfill_launch(self, launch_id: str) -> dict[str, Any]:" in client_source
    assert 'return self.get_json(f"/api/v1/workflow-backfill-launches/{launch_id}")["data"]' in client_source
    assert "def cancel_workflow_backfill_launch(self, launch_id: str, payload: dict[str, Any])" in client_source
    assert 'return self.post_json(f"/api/v1/workflow-backfill-launches/{launch_id}/cancel", payload)["data"]' in client_source

    assert "def list_workflow_triggers(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert "def create_workflow_trigger(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert "def submit_workflow_trigger_event(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert "def submit_workflow_trigger_inbox_event(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert "def submit_workflow_trigger_readiness_event(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert "def preview_workflow_trigger_backfill(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert "def launch_workflow_trigger_backfill(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert "def list_workflow_trigger_events(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert "def list_workflow_trigger_inbox_events(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert "def list_workflow_backfill_launches(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert "def get_workflow_backfill_launch(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert "def cancel_workflow_backfill_launch(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert 'client.get_json("/api/v1/workflow-triggers")["data"]' in proxy_source
    assert 'client.post_json("/api/v1/workflow-triggers", kwargs["payload"])["data"]' in proxy_source
    assert 'client.post_json(\n            f"/api/v1/workflow-triggers/{kwargs[\'trigger_id\']}/events"' in proxy_source
    assert 'client.post_json(\n            f"/api/v1/workflow-triggers/{kwargs[\'trigger_id\']}/inbox"' in proxy_source
    assert 'client.post_json(\n            f"/api/v1/workflow-triggers/{kwargs[\'trigger_id\']}/readiness"' in proxy_source
    assert 'client.post_json(\n            f"/api/v1/workflow-triggers/{kwargs[\'trigger_id\']}/backfill/preview"' in proxy_source
    assert 'client.post_json(\n            f"/api/v1/workflow-triggers/{kwargs[\'trigger_id\']}/backfill/launch"' in proxy_source
    assert 'client.get_json(f"/api/v1/workflow-triggers/{kwargs[\'trigger_id\']}/inbox?{query}")["data"]' in proxy_source
    assert 'client.get_json(f"/api/v1/workflow-backfill-launches?{query}")["data"]' in proxy_source
    assert 'client.get_json(f"/api/v1/workflow-backfill-launches/{kwargs[\'launch_id\']}")["data"]' in proxy_source
    assert 'f"/api/v1/workflow-backfill-launches/{kwargs[\'launch_id\']}/cancel"' in proxy_source
