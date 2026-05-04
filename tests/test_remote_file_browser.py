from __future__ import annotations

from core.app_runtime.errors import RuntimeServiceError
from core.app_runtime.service import RuntimeService, ServiceLocator


class FakeSSH:
    is_connected = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, bool, int, int]] = []

    def list_directory(self, path: str, *, directories_only: bool, limit: int, offset: int = 0) -> dict:
        self.calls.append((path, directories_only, limit, offset))
        return {
            "path": "/home/user/databases",
            "parentPath": "/home/user",
            "items": [{"name": "kraken2", "path": "/home/user/databases/kraken2", "type": "directory", "isDirectory": True}],
            "truncated": False,
        }

    def close(self) -> None:
        return None


def test_runtime_lists_remote_files_through_connected_ssh() -> None:
    ssh = FakeSSH()
    service = RuntimeService(service_locator=ServiceLocator(ssh_service=ssh))
    service._initialized = True

    response = service.list_remote_files("~/databases", directories_only=True, limit=25, offset=50)

    assert ssh.calls == [("~/databases", True, 25, 50)]
    assert response["data"]["path"] == "/home/user/databases"
    assert response["data"]["items"][0]["path"] == "/home/user/databases/kraken2"


def test_runtime_remote_files_requires_ssh_connection() -> None:
    service = RuntimeService(service_locator=ServiceLocator())
    service._initialized = True

    try:
        service.list_remote_files("~/databases")
    except RuntimeServiceError as exc:
        assert "SSH disconnected" in str(exc)
    else:
        raise AssertionError("expected RuntimeServiceError")
