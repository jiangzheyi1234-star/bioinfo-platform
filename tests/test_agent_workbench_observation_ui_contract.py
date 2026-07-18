from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"
PAGE = COMPONENTS / "agent-workbench-page.tsx"
PANEL = COMPONENTS / "agent-session-observation-panel.tsx"
TIMELINE = COMPONENTS / "agent-event-timeline.tsx"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _between(source: str, start: str, end: str) -> str:
    return source.split(start, 1)[1].split(end, 1)[0]


def test_workbench_wires_one_atomic_snapshot_observation_before_timeline() -> None:
    source = _read(PAGE)
    panel_index = source.index("<AgentSessionObservationPanel")
    timeline_index = source.index("<AgentEventTimeline")
    panel_call = _between(source, "<AgentSessionObservationPanel", "/>")

    assert 'import { useMemo } from "react"' in source
    assert (
        'import { AgentSessionObservationPanel } from "./agent-session-observation-panel"'
        in source
    )
    assert "const observationFrame = useMemo(" in source
    assert "observedAtEpochMs: Date.now(), snapshot: state.snapshot" in source
    assert "[state.snapshot]" in source
    assert "{observationFrame.snapshot ? (" in source
    assert "snapshot={observationFrame.snapshot}" in panel_call
    assert "observedAtEpochMs={observationFrame.observedAtEpochMs}" in panel_call
    assert panel_index < timeline_index
    assert "events={state.snapshot?.events || []}" in source
    assert "deriveAgentSessionObservation" not in source


def test_observation_panel_is_read_only_bounded_and_fail_visible() -> None:
    source = _read(PANEL)
    props = _between(
        source,
        "export type AgentSessionObservationPanelProps = {",
        "};",
    )

    assert "observedAtEpochMs: number" in props
    assert "snapshot: AgentSessionSnapshot" in props
    assert set(re.findall(r"^\s*([A-Za-z][A-Za-z0-9]*):", props, re.MULTILINE)) == {
        "observedAtEpochMs",
        "snapshot",
    }
    assert "deriveAgentSessionObservation(snapshot, observedAtEpochMs)" in source
    assert "Object.values(AGENT_SESSION_OBSERVATION_ERRORS)" in source
    assert "KNOWN_OBSERVATION_ERRORS.has(error.message)" in source
    assert "AGENT_SESSION_OBSERVATION_DERIVATION_FAILED" in source
    for marker in (
        'data-testid="agent-session-observation"',
        "data-attention={observation.lifecycle.attention}",
        "data-status={observation.lifecycle.status}",
        "data-timing-status={observation.lifecycle.timingStatus}",
        'data-testid="agent-session-observation-error"',
    ):
        assert marker in source

    for forbidden in (
        '"use client"',
        "fetch(",
        "XMLHttpRequest",
        "useEffect(",
        "setInterval(",
        "setTimeout(",
        "localStorage",
        "sessionStorage",
        "onClick=",
        "onSubmit=",
        "href=",
        "selectedSession",
        "currentPlan",
        "ReactFlow",
        "contentEditable",
        "draggable=",
    ):
        assert forbidden not in source
    assert re.search(r"<(?:button|input|textarea|select|a)\b", source) is None
    assert (
        re.search(
            r"\b(?:snapshot|event|observation)\.(?:payload|actor|requestId|"
            r"idempotencyKey|path|uri|rawModelOutput|credential)\b",
            source,
        )
        is None
    )


def test_observation_copy_preserves_time_integrity_and_privacy_boundaries() -> None:
    panel = _read(PANEL)
    timeline = _read(TIMELINE)

    for text in (
        "刷新时的客户端估算；不能据此判断 stalled、SLA 或 timeout。",
        "已使用 / 上限；仅此预算有权威事件事实",
        "Snapshot endpoint requires full-chain validation",
        "正式 snapshot endpoint 的成功响应要求 runner 完整 hash-chain",
        "浏览器仅验证 sequence 与 prevEventHash",
        "不能重算已隐去 commandHash 的",
        "本摘要不展示事件内容、请求身份、操作者、路径或 URI、模型输出、命令哈希或凭据。",
        "这是只读提示，不授权或执行任何控制命令。",
    ):
        assert text in panel
    assert "公开 Hash-chain 字段（浏览器不重算 eventHash）" in timeline
    for invented_usage in (
        "model turns used",
        "tool calls used",
        "retries used",
        "tokens used",
        "cost used",
        "wall clock used",
    ):
        assert invented_usage not in panel.lower()
