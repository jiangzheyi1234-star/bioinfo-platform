from __future__ import annotations


def test_terminal_stream_logic_lives_outside_main_module() -> None:
    from apps.api.ssh_terminal_service import stream_terminal_session_with_runtime

    assert callable(stream_terminal_session_with_runtime)


def test_terminal_stream_logic_does_not_live_in_route_module() -> None:
    from pathlib import Path

    route_module = Path(__file__).resolve().parents[1] / "apps/api/ssh_terminal_routes.py"

    assert not route_module.exists()
