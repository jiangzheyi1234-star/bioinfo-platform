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
class TableView:
    title: str = ""
    subtitle: str = ""
    columns: list[dict[str, str]] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ProvenanceInfo:
    execution_id: str = ""
    parameters: list[dict[str, Any]] = field(default_factory=list)
    tool_version: str = ""
    remote_result_dir: str = ""
    local_result_dir: str = ""
    command_preview: str = ""


@dataclass
class ViewSection:
    section_id: str
    title: str
    archetype: str
    summary: list[SummaryItem] = field(default_factory=list)
    charts: list[dict[str, Any]] = field(default_factory=list)
    table: TableView = field(default_factory=TableView)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    provenance: ProvenanceInfo = field(default_factory=ProvenanceInfo)

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_id": self.section_id,
            "title": self.title,
            "archetype": self.archetype,
            "summary": [asdict(item) for item in self.summary],
            "charts": list(self.charts),
            "table": asdict(self.table),
            "artifacts": list(self.artifacts),
            "provenance": asdict(self.provenance),
        }


@dataclass
class SingleToolView:
    feature_id: str
    tool_id: str
    archetype: str
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
    sections: list[ViewSection] = field(default_factory=list)
    tool_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = asdict(self.status)
        payload["hero"] = asdict(self.hero)
        payload["summary"] = [asdict(item) for item in self.summary]
        payload["table"] = asdict(self.table)
        payload["provenance"] = asdict(self.provenance)
        payload["sections"] = [section.to_dict() for section in self.sections]
        payload["tool_ids"] = list(self.tool_ids or [self.tool_id])
        return payload
