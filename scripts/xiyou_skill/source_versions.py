from __future__ import annotations

from datetime import datetime

from .models import MetricRecord


def _captured_at(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def source_artifact_ids(records: list[MetricRecord], source_name: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(
        record.artifact_id for record in records if record.source_name == source_name
    ))


def select_latest_source_artifact(
    records: list[MetricRecord], source_name: str
) -> tuple[str | None, list[MetricRecord]]:
    candidates = [record for record in records if record.source_name == source_name]
    if not candidates:
        return None, []
    latest_artifact = max(
        {record.artifact_id for record in candidates},
        key=lambda artifact_id: max(
            _captured_at(record.captured_at)
            for record in candidates if record.artifact_id == artifact_id
        ),
    )
    return latest_artifact, [record for record in candidates if record.artifact_id == latest_artifact]

