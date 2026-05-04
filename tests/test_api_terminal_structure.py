from __future__ import annotations


def test_terminal_stream_logic_lives_outside_main_module() -> None:
    from apps.api.ssh_terminal_routes import stream_terminal_session_with_runtime

    assert callable(stream_terminal_session_with_runtime)
