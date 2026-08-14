import json
from datetime import date
from pathlib import Path

import pytest

from xiyou_skill.models import CaseConfig, load_case
from xiyou_skill.raw_store import RawStore


def test_load_case_validates_asins_and_period(tmp_path: Path):
    config = tmp_path / "case.json"
    config.write_text(json.dumps({
        "case_id": "case-1", "marketplace": "US", "own_asin": "B0SYNTH001",
        "competitors": ["B0SYNTH002"], "period": {"start": "2026-07-12", "end": "2026-08-10"}
    }), encoding="utf-8")

    case = load_case(config)

    assert case.own_asin == "B0SYNTH001"
    assert case.period_start == date(2026, 7, 12)


def test_load_case_rejects_invalid_asin(tmp_path: Path):
    config = tmp_path / "case.json"
    config.write_text('{"case_id":"x","marketplace":"US","own_asin":"bad","competitors":[],"period":{"start":"2026-07-12","end":"2026-08-10"}}', encoding="utf-8")
    with pytest.raises(ValueError, match="ASIN"):
        load_case(config)


def test_raw_store_registers_immutable_file_and_is_idempotent(tmp_path: Path):
    source = tmp_path / "export.xlsx"
    source.write_bytes(b"real-export-placeholder")
    case = CaseConfig("case-1", "US", "B0SYNTH001", ("B0SYNTH002",), date(2026, 7, 12), date(2026, 8, 10))
    store = RawStore(tmp_path / "data")

    first = store.register(source, source_name="XIYOU", source_level="L3", case=case, asins=case.all_asins)
    second = store.register(source, source_name="XIYOU", source_level="L3", case=case, asins=case.all_asins)

    assert first.artifact_id == second.artifact_id
    assert first.path.read_bytes() == source.read_bytes()
    metadata = json.loads(first.metadata_path.read_text(encoding="utf-8"))
    assert metadata["sha256"] == first.sha256
    assert metadata["marketplace"] == "US"
    assert metadata["period"] == {"start": "2026-07-12", "end": "2026-08-10"}


def test_raw_store_records_source_period_separately(tmp_path: Path):
    source = tmp_path / "export.xlsx"
    source.write_bytes(b"real-export-placeholder")
    case = CaseConfig("case-1", "US", "B0SYNTH001", (), date(2026, 7, 12), date(2026, 8, 10))

    artifact = RawStore(tmp_path / "data").register(
        source, source_name="XIYOU", source_level="L3", case=case, asins=case.all_asins,
        source_period={"start": "2026-08-03", "end": "2026-08-09", "basis": "workbook_sheet_name"},
    )

    metadata = json.loads(artifact.metadata_path.read_text(encoding="utf-8"))
    assert metadata["analysis_period"] == {"start": "2026-07-12", "end": "2026-08-10"}
    assert metadata["source_period"]["basis"] == "workbook_sheet_name"
