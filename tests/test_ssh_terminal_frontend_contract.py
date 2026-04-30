from __future__ import annotations

from pathlib import Path


TERMINAL_HOOK = (
    Path(__file__).resolve().parents[1]
    / "apps"
    / "web"
    / "app"
    / "components"
    / "ssh-shell-terminal.ts"
)
XTERM_HOOK = (
    Path(__file__).resolve().parents[1]
    / "apps"
    / "web"
    / "app"
    / "components"
    / "ssh-shell-xterm.ts"
)


def test_terminal_resize_is_queued_until_stream_opens() -> None:
    source = TERMINAL_HOOK.read_text(encoding="utf-8")

    assert "pendingTerminalResizeRef" in source
    assert "flushPendingTerminalResize" in source
    assert "flushPendingTerminalResize();" in source
    assert 'message.type === "resize"' in source


def test_terminal_stream_error_event_does_not_directly_show_user_error() -> None:
    source = TERMINAL_HOOK.read_text(encoding="utf-8")

    assert 'onError: () => {' in source
    on_error_body = source.split("onError: () => {", 1)[1].split("},", 1)[0]
    assert "setTerminalMessage" not in on_error_body


def test_terminal_user_input_is_queued_while_stream_connects() -> None:
    source = TERMINAL_HOOK.read_text(encoding="utf-8")
    send_body = source.split("const sendTerminalStreamMessage = useCallback(", 1)[1].split(
        "const queueTerminalInput = useCallback", 1
    )[0]

    assert "pendingTerminalInputRef" in source
    assert "flushPendingTerminalInput" in source
    assert "setTerminalMessage" not in send_body
    assert 'sendTerminalStreamMessage({ type: "input", data }, { queueInput: true })' in source
    assert 'sendTerminalStreamMessage({ type: "resize", cols, rows }, { queueResize: true })' in source


def test_terminal_filters_xterm_mode_query_auto_replies() -> None:
    source = XTERM_HOOK.read_text(encoding="utf-8")

    assert "createTerminalAutoReplyFilter" in source
    assert 'let pending = "";' in source
    assert "pending = input.slice(index)" in source
    assert "isCsiFinalByte" in source
    assert "findOscTerminator" in source
    assert r"\u001b\[\d+;\d+R" in source
    assert r"\u001b\[\??[0-9;]*\$y" in source
    assert "terminalAutoReplyFilterRef.current(data)" in source
    assert "onInput(filtered)" in source
