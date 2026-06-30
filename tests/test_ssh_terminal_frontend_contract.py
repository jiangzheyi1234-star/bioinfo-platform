from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"

CONTRACT_FILES = {
    "model": COMPONENTS / "ssh-shell-model.ts",
    "shell": COMPONENTS / "ssh-shell.tsx",
    "terminal": COMPONENTS / "ssh-shell-terminal.ts",
    "xterm": COMPONENTS / "ssh-shell-xterm.ts",
}


def _source(name: str) -> str:
    return CONTRACT_FILES[name].read_text(encoding="utf-8")


def _assert_contains(source: str, *tokens: str) -> None:
    for token in tokens:
        assert token in source


def _assert_not_contains(source: str, *tokens: str) -> None:
    for token in tokens:
        assert token not in source


def _assert_matches(source: str, *patterns: str) -> None:
    for pattern in patterns:
        assert re.search(pattern, source, re.DOTALL), pattern


def _between(source: str, start: str, end: str) -> str:
    return source.split(start, 1)[1].split(end, 1)[0]


def test_terminal_input_and_resize_are_queued_until_stream_opens() -> None:
    source = _source("terminal")
    on_open_body = _between(source, "onOpen: () => {", "},")

    _assert_contains(
        source,
        "pendingTerminalResizeRef",
        "pendingTerminalInputRef",
        "flushPendingTerminalResize",
        "flushPendingTerminalInput",
        'message.type === "input"',
        'message.type === "resize"',
        'sendTerminalStreamMessage({ type: "input", data }, { queueInput: true })',
        'sendTerminalStreamMessage({ type: "resize", cols, rows }, { queueResize: true })',
    )
    _assert_contains(on_open_body, "flushPendingTerminalResize();", "flushPendingTerminalInput();")


def test_terminal_stream_error_event_does_not_directly_show_user_error() -> None:
    source = _source("terminal")

    on_error_body = _between(source, "onError: () => {", "},")
    _assert_not_contains(on_error_body, "setTerminalMessage")


def test_terminal_session_uses_current_api_contract() -> None:
    source = _source("terminal")

    _assert_contains(
        source,
        "refreshStatus({ silent: true })",
        "TERMINAL_RECONNECT_DELAY_MS",
    )
    _assert_matches(
        source,
        r'requestLocalApiJson\(\s*"POST",\s*"/api/v1/ssh/terminal/sessions"',
        r'requestLocalApiJson\(\s*"DELETE",\s*`/api/v1/ssh/terminal/sessions/\$\{activeSessionId\}`',
        r"connectTerminalStream\(\s*snapshot\.session_id,\s*snapshot\.cursor\s*\|\|\s*0\s*\)",
    )
    send_body = _between(source, "const sendTerminalStreamMessage = useCallback(", "const queueTerminalInput = useCallback")
    _assert_not_contains(send_body, "setTerminalMessage")


def test_terminal_scrollback_is_capped_on_stream_and_viewport() -> None:
    model_source = _source("model")
    stream_source = (COMPONENTS / "ssh-terminal-stream.ts").read_text(encoding="utf-8")
    terminal_source = _source("terminal")
    xterm_source = _source("xterm")

    _assert_contains(
        model_source,
        "TERMINAL_XTERM_SCROLLBACK_ROWS",
        "TERMINAL_REPLAY_BUFFER_MAX_CHARS",
        "TERMINAL_PENDING_INPUT_MAX_CHARS",
        "retainTerminalReplayBufferTail",
        "retainTerminalPendingInputPrefix",
        "base_cursor: number",
        "truncated: boolean",
        "scrollback_limit: number",
    )
    _assert_contains(stream_source, "cursor: number", "base_cursor: number", "truncated: boolean")
    _assert_contains(
        terminal_source,
        'case "output":',
        "typeof message.cursor === \"number\"",
        "if (message.truncated)",
        "terminalViewport.replaceOutput(message.data)",
        "terminalViewport.appendOutput(message.data)",
        "retainTerminalPendingInputPrefix(nextInput)",
        "TERMINAL_PENDING_INPUT_MAX_CHARS",
    )
    _assert_contains(
        xterm_source,
        "TERMINAL_XTERM_SCROLLBACK_ROWS",
        "retainTerminalReplayBufferTail",
        "scrollback: TERMINAL_XTERM_SCROLLBACK_ROWS",
    )
    _assert_not_contains(xterm_source, "terminalBufferRef.current += data")
    _assert_not_contains(terminal_source, "pendingTerminalInputRef.current += message.data")


def test_terminal_requires_ready_ssh_channel_not_optimistic_connection() -> None:
    model_source = _source("model")
    shell_source = _source("shell")
    terminal_source = _source("terminal")

    _assert_contains(
        model_source,
        "export function isSshChannelReady",
        "!status.connecting",
        "!status.auto_connect_in_progress",
    )
    _assert_contains(
        shell_source,
        "isSshChannelReady(connection.status)",
        "disabled={!sshChannelReady}",
    )
    _assert_contains(
        terminal_source,
        "isSshChannelReady(nextStatus)",
        "isSshChannelReady(status)",
        "if (!isSshChannelReady(status))",
    )
    _assert_not_contains(
        shell_source,
        "disabled={!connection.status?.connected}",
    )
    _assert_not_contains(
        terminal_source,
        "if (!status?.connected)",
    )


def test_terminal_filters_xterm_mode_query_auto_replies() -> None:
    source = _source("xterm")

    _assert_contains(
        source,
        "createTerminalAutoReplyFilter",
        'let pending = "";',
        "pending = input.slice(index)",
        "isCsiFinalByte",
        "findOscTerminator",
        r"\u001b\[\d+;\d+R",
        r"\u001b\[\??[0-9;]*\$y",
        "terminalAutoReplyFilterRef.current(data)",
        "onInput(filtered)",
    )
