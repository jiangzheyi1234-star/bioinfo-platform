from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Finding:
    code: str
    path: str
    line: int
    detail: str

    def format(self) -> str:
        suffix = f":{self.line}" if self.line else ""
        return f"{self.code}: {self.path}{suffix} {self.detail}".rstrip()


def line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1
