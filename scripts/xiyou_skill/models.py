from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any


ASIN_PATTERN = re.compile(r"^[A-Z0-9]{10}$")


@dataclass(frozen=True)
class CaseConfig:
    case_id: str
    marketplace: str
    own_asin: str
    competitors: tuple[str, ...]
    period_start: date
    period_end: date
    run_id: str = ""
    ruleset_version: str = "sop-v5.1"
    lifecycle: str = "unknown"
    objective: str = "综合诊断"
    competitor_review_status: str = "PENDING"
    event_history_status: str = "MISSING"
    competitor_metadata: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    known_events: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        asins = (self.own_asin, *self.competitors)
        if any(not ASIN_PATTERN.fullmatch(asin) for asin in asins):
            raise ValueError("ASIN 必须是 10 位大写字母或数字")
        if len(set(asins)) != len(asins):
            raise ValueError("自身 ASIN 与竞品 ASIN 不能重复")
        if self.period_start > self.period_end:
            raise ValueError("分析周期开始日期不能晚于结束日期")
        if not self.marketplace:
            raise ValueError("marketplace 不能为空")
        if not self.run_id:
            object.__setattr__(self, "run_id", self.case_id)

    @property
    def all_asins(self) -> tuple[str, ...]:
        return (self.own_asin, *self.competitors)


@dataclass(frozen=True)
class RawArtifact:
    artifact_id: str
    source_name: str
    source_level: str
    path: Path
    metadata_path: Path
    sha256: str
    captured_at: str
    case_id: str = ""
    run_id: str = ""


@dataclass(frozen=True)
class MetricRecord:
    evidence_id: str
    artifact_id: str
    source_name: str
    source_level: str
    marketplace: str
    asin: str
    period_start: str
    period_end: str
    metric: str
    value: Any
    unit: str
    locator: str
    raw_path: str
    captured_at: str
    dimensions: dict[str, Any] = field(default_factory=dict)
    case_id: str = ""
    run_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MetricRecord":
        values = {"case_id": "", "run_id": "", **payload}
        return cls(**values)


def load_case(path: str | Path) -> CaseConfig:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    period = payload["period"]
    competitors_payload = payload.get("competitors", [])
    competitor_metadata = tuple(
        dict(value) for value in competitors_payload if isinstance(value, dict)
    )
    competitors = tuple(
        str(value["asin"] if isinstance(value, dict) else value).upper()
        for value in competitors_payload
    )
    return CaseConfig(
        case_id=str(payload["case_id"]),
        marketplace=str(payload["marketplace"]).upper(),
        own_asin=str(payload["own_asin"]).upper(),
        competitors=competitors,
        period_start=date.fromisoformat(period["start"]),
        period_end=date.fromisoformat(period["end"]),
        run_id=str(payload.get("run_id") or payload["case_id"]),
        ruleset_version=str(payload.get("ruleset_version", "sop-v5.1")),
        lifecycle=str(payload.get("lifecycle", "unknown")),
        objective=str(payload.get("objective", "综合诊断")),
        competitor_review_status=str(payload.get("competitor_review_status", "PENDING")),
        event_history_status=str(payload.get("event_history_status", "MISSING")),
        competitor_metadata=competitor_metadata,
        known_events=tuple(dict(value) for value in payload.get("known_events", [])),
    )

