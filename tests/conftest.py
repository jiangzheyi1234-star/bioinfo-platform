from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_app_config_and_keyring(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import config

    appdata = tmp_path / "appdata"
    localappdata = tmp_path / "localappdata"
    config_path = appdata / "H2OMeta" / "config.json"
    keyring_values: dict[tuple[str, str], str] = {}

    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("LOCALAPPDATA", str(localappdata))
    monkeypatch.setattr(config, "_CONFIG_PATH", config_path)
    monkeypatch.setattr(config, "_CACHE", None)
    monkeypatch.setattr(
        config.keyring,
        "set_password",
        lambda service, username, password: keyring_values.__setitem__((service, username), password),
    )
    monkeypatch.setattr(
        config.keyring,
        "get_password",
        lambda service, username: keyring_values.get((service, username)),
    )
    monkeypatch.setattr(
        config.keyring,
        "delete_password",
        lambda service, username: keyring_values.pop((service, username), None),
    )

