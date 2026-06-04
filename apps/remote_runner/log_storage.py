from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .config import RemoteRunnerConfig


def append_log_lines(cfg: RemoteRunnerConfig, run_id: str, stream: str, lines: Iterable[str]) -> None:
    logs_dir = Path(cfg.logs_dir)
    logs_dir.mkdir(parents=True, exist_ok=True)
    path = logs_dir / f"{run_id}.{stream}.log"
    with path.open("a", encoding="utf-8") as handle:
        for line in lines:
            handle.write(f"{line}\n")


def fetch_log_lines(cfg: RemoteRunnerConfig, run_id: str, stream: str, cursor: str | None) -> dict[str, Any]:
    path = Path(cfg.logs_dir) / f"{run_id}.{stream}.log"
    if not path.exists():
        return {"runId": run_id, "stream": stream, "cursor": cursor or "", "nextCursor": cursor or "", "lines": []}
    content = path.read_text(encoding="utf-8")
    start = int(cursor or 0)
    next_cursor = len(content)
    lines = [line for line in content[start:].splitlines() if line]
    return {
        "runId": run_id,
        "stream": stream,
        "cursor": cursor or "",
        "nextCursor": str(next_cursor),
        "lines": lines,
    }
