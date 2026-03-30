"""Standard single-tool result view schema.

Keep this module Qt-free and focused on deterministic data shaping.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ViewStatus:
    state: str
    label: str
    detail: str = ""


@dataclass
class HeroInfo:
    sample_name: str = ""
    execution_id: str = ""
    updated_at: str = ""
    primary_action: str = "view_result"


@dataclass
class SummaryItem:
    label: str
    value: str
    tone: str = "default"


@dataclass
class TableColumn:
    key: str
    label: str


@dataclass
class TableView:
    title: str = ""
    subtitle: str = ""
    columns: list[dict[str, str]] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ProvenanceInfo:
    parameters: list[dict[str, str]] = field(default_factory=list)
    tool_version: str = ""
    remote_result_dir: str = ""
    command_preview: str = ""


@dataclass
class SingleToolView:
    feature_id: str
    tool_ids: list[str]
    title: str
    description: str
    status: ViewStatus
    hero: HeroInfo = field(default_factory=HeroInfo)
    summary: list[SummaryItem] = field(default_factory=list)
    tabs: list[str] = field(default_factory=lambda: ["overview", "chart", "table", "files"])
    charts: list[dict[str, Any]] = field(default_factory=list)
    table: TableView = field(default_factory=TableView)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    provenance: ProvenanceInfo = field(default_factory=ProvenanceInfo)
    parameters: list[dict[str, str]] = field(default_factory=list)
    table_title: str = ""
    table_subtitle: str = ""
    columns: list[dict[str, str]] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = asdict(self.status)
        payload["hero"] = asdict(self.hero)
        payload["provenance"] = asdict(self.provenance)
        payload["table"] = asdict(self.table)
        payload["summary"] = [asdict(item) for item in self.summary]
        payload["table_title"] = self.table_title or self.table.title
        payload["table_subtitle"] = self.table_subtitle or self.table.subtitle
        payload["columns"] = self.columns or list(self.table.columns)
        payload["rows"] = self.rows or list(self.table.rows)
        payload["parameters"] = self.parameters or list(self.provenance.parameters)
        payload["chart"] = payload["charts"][0] if payload["charts"] else None
        return payload
