from __future__ import annotations

import json

import config


class _FakeParent:
    def __init__(self) -> None:
        self.mkdir_calls: list[dict[str, object]] = []

    def mkdir(self, **kwargs) -> None:
        self.mkdir_calls.append(dict(kwargs))


class _FakeConfigPath:
    def __init__(self, payload: dict | None = None) -> None:
        self.parent = _FakeParent()
        self.payload = payload or {}
        self.written_text = ""
        self.written_encoding = ""

    def exists(self) -> bool:
        return True

    def read_text(self, *, encoding: str | None = None) -> str:
        if encoding != "utf-8":
            raise UnicodeDecodeError("cp936", b"\xff", 0, 1, "forced non-UTF-8 read")
        return json.dumps(self.payload, ensure_ascii=False)

    def write_text(self, text: str, *, encoding: str | None = None) -> int:
        if encoding != "utf-8":
            raise UnicodeEncodeError("cp936", "远端", 0, 1, "forced non-UTF-8 write")
        self.written_text = text
        self.written_encoding = str(encoding)
        return len(text)


def test_get_config_reads_utf8_config(monkeypatch) -> None:
    fake_path = _FakeConfigPath(
        {
            "ssh": {
                "auth_mode": "password_ref",
                "host": "192.168.0.152",
                "port": 22,
                "user": "zyserver",
                "password_ref": "ssh://zyserver@192.168.0.152:22",
            },
            "servers": {"srv_1": {"label": "远端"}},
        }
    )
    monkeypatch.setattr(config, "_CACHE", None)
    monkeypatch.setattr(config, "_CONFIG_PATH", fake_path)

    cfg = config.get_config()

    assert cfg["ssh"]["host"] == "192.168.0.152"
    assert cfg["servers"]["srv_1"]["label"] == "远端"


def test_save_config_writes_utf8_config(monkeypatch) -> None:
    fake_path = _FakeConfigPath()
    monkeypatch.setattr(config, "_CACHE", None)
    monkeypatch.setattr(config, "_CONFIG_PATH", fake_path)

    config.save_config({"servers": {"srv_1": {"label": "远端"}}})

    assert fake_path.written_encoding == "utf-8"
    assert '"label": "远端"' in fake_path.written_text
