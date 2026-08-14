import json

import pytest

from openpyxl import Workbook

from xiyou_skill.cli import main
from xiyou_skill.amazon_spapi import SpApiError


def test_build_report_command_creates_blocked_report_without_inputs(tmp_path):
    case = tmp_path / "case.json"
    case.write_text(json.dumps({
        "case_id": "case-1", "marketplace": "US", "own_asin": "B0SYNTH001",
        "competitors": ["B0SYNTH002"], "period": {"start": "2026-07-12", "end": "2026-08-10"}
    }), encoding="utf-8")
    output = tmp_path / "analysis.md"

    result = main(["--case", str(case), "--data-dir", str(tmp_path / "data"), "build-report", "--output", str(output)])

    assert result == 0
    assert output.exists()
    assert "BLOCKED" in output.read_text(encoding="utf-8")


def test_ingest_xiyou_accepts_source_period_and_archive_only(tmp_path):
    case = tmp_path / "case.json"
    case.write_text(json.dumps({
        "case_id": "case-1", "marketplace": "US", "own_asin": "B0SYNTH001",
        "competitors": [], "period": {"start": "2026-07-12", "end": "2026-08-10"}
    }), encoding="utf-8")
    export = tmp_path / "overview.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["ASIN", "7天流量得分"])
    ws.append(["B0SYNTH001", 46])
    wb.save(export)
    data_dir = tmp_path / "data"

    result = main([
        "--case", str(case), "--data-dir", str(data_dir), "ingest-xiyou",
        "--file", str(export), "--source-period-start", "2026-08-03",
        "--source-period-end", "2026-08-09", "--period-basis", "workbook_sheet_name",
        "--archive-only",
    ])

    assert result == 0
    assert not (data_dir / "normalized" / "metrics.jsonl").exists()
    metadata_path = next((data_dir / "raw" / "xiyou").glob("ART-*/metadata.json"))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["source_period"] == {
        "start": "2026-08-03", "end": "2026-08-09", "basis": "workbook_sheet_name"
    }


def test_ingest_amazon_reuses_real_report_but_keeps_only_case_asin(tmp_path):
    case = tmp_path / "case.json"
    case.write_text(json.dumps({
        "case_id": "case-child", "marketplace": "US", "own_asin": "B0SYNTH004",
        "competitors": [], "period": {"start": "2026-07-12", "end": "2026-08-10"}
    }), encoding="utf-8")
    source = tmp_path / "sales-traffic.json"
    source.write_text(json.dumps({"salesAndTrafficByAsin": [
        {"parentAsin": "B0SYNTH005", "childAsin": "B0SYNTH005", "trafficByAsin": {"sessions": 14}},
        {"parentAsin": "B0SYNTH004", "childAsin": "B0SYNTH004", "trafficByAsin": {"sessions": 4},
         "salesByAsin": {"unitsOrdered": 1}},
    ]}), encoding="utf-8")
    data_dir = tmp_path / "data"

    result = main([
        "--case", str(case), "--data-dir", str(data_dir), "ingest-amazon", "--file", str(source)
    ])

    assert result == 0
    rows = [json.loads(line) for line in (data_dir / "normalized" / "metrics.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {row["asin"] for row in rows} == {"B0SYNTH004"}
    assert {row["metric"]: row["value"] for row in rows} == {"sessions": 4, "units_ordered": 1}


def test_fetch_sqp_persists_permission_block_without_secrets(tmp_path, monkeypatch):
    case = tmp_path / "case.json"
    case.write_text(json.dumps({
        "case_id": "case-1", "marketplace": "US", "own_asin": "B0SYNTH001",
        "competitors": [], "period": {"start": "2026-07-12", "end": "2026-08-10"}
    }), encoding="utf-8")
    for name in ("SP_API_LWA_CLIENT_ID", "SP_API_LWA_CLIENT_SECRET", "SP_API_REFRESH_TOKEN", "SP_API_MARKETPLACE_ID"):
        monkeypatch.setenv(name, "secret-test-value")

    class BlockedClient:
        def __init__(self, *args, **kwargs):
            pass

        def fetch_search_query_performance(self, *args, **kwargs):
            raise SpApiError(
                "需要检查 API 授权或角色权限（HTTP 403）",
                report_id="R-PERMISSION", processing_status="FATAL",
            )

    monkeypatch.setattr("xiyou_skill.cli.SalesTrafficClient", BlockedClient)
    data_dir = tmp_path / "data"

    result = main(["--case", str(case), "--data-dir", str(data_dir), "fetch-sqp"])

    assert result == 3
    status_path = data_dir / "status" / "amazon-search-query-performance.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["status"] == "BLOCKED_PERMISSION"
    assert status["source_name"] == "AMAZON_SEARCH_QUERY_PERFORMANCE"
    assert status["requested_periods"][0]["report_id"] == "R-PERMISSION"
    assert "secret-test-value" not in status_path.read_text(encoding="utf-8")


def test_resume_sqp_downloads_existing_report_id_without_creating_report(tmp_path, monkeypatch):
    case = tmp_path / "case.json"
    case.write_text(json.dumps({
        "case_id": "case-1", "marketplace": "US", "own_asin": "B0SYNTH001",
        "competitors": [], "period": {"start": "2026-07-12", "end": "2026-08-10"}
    }), encoding="utf-8")
    for name in ("SP_API_LWA_CLIENT_ID", "SP_API_LWA_CLIENT_SECRET", "SP_API_REFRESH_TOKEN", "SP_API_MARKETPLACE_ID"):
        monkeypatch.setenv(name, "secret-test-value")

    class ResumeOnlyClient:
        def __init__(self, *args, **kwargs):
            pass

        def fetch_report_by_id(self, report_id, **kwargs):
            assert report_id == "R-EXISTING"
            return {"dataByAsin": [{
                "startDate": "2026-07-12", "endDate": "2026-07-18", "asin": "B0SYNTH001",
                "searchQueryData": [{
                    "searchQuery": "dog wipes",
                    "impressionData": {"asinImpressionCount": 10},
                    "clickData": {"asinClickCount": 2},
                    "purchaseData": {"asinPurchaseCount": 1},
                }],
            }]}

        def fetch_search_query_performance(self, *args, **kwargs):
            raise AssertionError("resume-sqp must never create a report")

    monkeypatch.setattr("xiyou_skill.cli.SalesTrafficClient", ResumeOnlyClient)
    data_dir = tmp_path / "data"

    result = main([
        "--case", str(case), "--data-dir", str(data_dir), "resume-sqp",
        "--report-id", "R-EXISTING", "--period-start", "2026-07-12", "--period-end", "2026-07-18",
    ])

    assert result == 0
    status = json.loads((data_dir / "status" / "amazon-search-query-performance.json").read_text(encoding="utf-8"))
    assert status["status"] == "PARTIAL_AVAILABLE"
    assert status["requested_periods"][0]["report_id"] == "R-EXISTING"
    metrics = (data_dir / "normalized" / "metrics.jsonl").read_text(encoding="utf-8")
    assert "sqp_clicks" in metrics


def test_resume_sqp_marks_successful_empty_document_available_empty(tmp_path, monkeypatch):
    case = tmp_path / "case.json"
    case.write_text(json.dumps({
        "case_id": "case-1", "marketplace": "US", "own_asin": "B0SYNTH001",
        "competitors": [], "period": {"start": "2026-07-12", "end": "2026-08-10"}
    }), encoding="utf-8")
    for name in ("SP_API_LWA_CLIENT_ID", "SP_API_LWA_CLIENT_SECRET", "SP_API_REFRESH_TOKEN", "SP_API_MARKETPLACE_ID"):
        monkeypatch.setenv(name, "secret-test-value")

    class EmptyClient:
        def __init__(self, *args, **kwargs):
            pass

        def fetch_report_by_id(self, *args, **kwargs):
            return {"reportSpecification": {"reportType": "GET_BRAND_ANALYTICS_SEARCH_QUERY_PERFORMANCE_REPORT"}, "dataByAsin": []}

    monkeypatch.setattr("xiyou_skill.cli.SalesTrafficClient", EmptyClient)
    data_dir = tmp_path / "data"

    result = main([
        "--case", str(case), "--data-dir", str(data_dir), "resume-sqp",
        "--report-id", "R-EMPTY", "--period-start", "2026-07-12", "--period-end", "2026-07-18",
    ])

    assert result == 0
    status = json.loads((data_dir / "status" / "amazon-search-query-performance.json").read_text(encoding="utf-8"))
    assert status["status"] == "PARTIAL_AVAILABLE_EMPTY"
    assert status["requested_periods"][0]["status"] == "AVAILABLE_EMPTY"
    assert status["covered_complete_weeks"] == 1
    assert status["expected_complete_weeks"] == 4
    assert "dataByAsin" in status["reason"]


def test_fetch_sqp_skips_terminal_week_and_creates_only_missing_periods(tmp_path, monkeypatch):
    case = tmp_path / "case.json"
    case.write_text(json.dumps({
        "case_id": "case-1", "marketplace": "US", "own_asin": "B0SYNTH001",
        "competitors": [], "period": {"start": "2026-07-12", "end": "2026-08-10"}
    }), encoding="utf-8")
    for name in ("SP_API_LWA_CLIENT_ID", "SP_API_LWA_CLIENT_SECRET", "SP_API_REFRESH_TOKEN", "SP_API_MARKETPLACE_ID"):
        monkeypatch.setenv(name, "secret-test-value")

    created_periods = []

    class IncrementalClient:
        def __init__(self, *args, **kwargs):
            self.last_report_id = None

        def fetch_report_by_id(self, *args, **kwargs):
            raise AssertionError("terminal period must never be resumed or recreated")

        def fetch_search_query_performance(self, _case, period_start, period_end, on_created=None):
            created_periods.append((period_start.isoformat(), period_end.isoformat()))
            self.last_report_id = f"R-{period_start:%Y%m%d}"
            if on_created:
                on_created(self.last_report_id)
            return {"dataByAsin": []}

    monkeypatch.setattr("xiyou_skill.cli.SalesTrafficClient", IncrementalClient)
    data_dir = tmp_path / "data"
    status_dir = data_dir / "status"
    status_dir.mkdir(parents=True)
    (status_dir / "amazon-search-query-performance.json").write_text(json.dumps({
        "source_name": "AMAZON_SEARCH_QUERY_PERFORMANCE",
        "report_type": "GET_BRAND_ANALYTICS_SEARCH_QUERY_PERFORMANCE_REPORT",
        "status": "PARTIAL_AVAILABLE_EMPTY",
        "requested_periods": [{
            "start": "2026-07-12", "end": "2026-07-18", "report_id": "82273020676",
            "status": "AVAILABLE_EMPTY", "artifact_id": "ART-EXISTING", "records": 0,
        }],
    }), encoding="utf-8")

    result = main(["--case", str(case), "--data-dir", str(data_dir), "fetch-sqp"])

    assert result == 0
    assert created_periods == [
        ("2026-07-19", "2026-07-25"),
        ("2026-07-26", "2026-08-01"),
        ("2026-08-02", "2026-08-08"),
    ]
    status = json.loads((status_dir / "amazon-search-query-performance.json").read_text(encoding="utf-8"))
    assert status["status"] == "AVAILABLE_EMPTY"
    assert status["covered_complete_weeks"] == 4
    assert status["expected_complete_weeks"] == 4
    assert status["requested_periods"][0]["report_id"] == "82273020676"
    assert {item["report_id"] for item in status["requested_periods"][1:]} == {
        "R-20260719", "R-20260726", "R-20260802"
    }


def test_fetch_sqp_persists_report_id_before_polling_finishes(tmp_path, monkeypatch):
    case = tmp_path / "case.json"
    case.write_text(json.dumps({
        "case_id": "case-1", "marketplace": "US", "own_asin": "B0SYNTH001",
        "competitors": [], "period": {"start": "2026-08-02", "end": "2026-08-08"}
    }), encoding="utf-8")
    for name in ("SP_API_LWA_CLIENT_ID", "SP_API_LWA_CLIENT_SECRET", "SP_API_REFRESH_TOKEN", "SP_API_MARKETPLACE_ID"):
        monkeypatch.setenv(name, "secret-test-value")

    class SlowClient:
        def __init__(self, *args, **kwargs):
            self.last_report_id = None

        def fetch_search_query_performance(self, *_args, on_created=None):
            self.last_report_id = "R-SAVED-BEFORE-POLL"
            on_created(self.last_report_id)
            raise SpApiError("Amazon 报告在轮询上限内未完成", processing_status="IN_PROGRESS")

    monkeypatch.setattr("xiyou_skill.cli.SalesTrafficClient", SlowClient)
    data_dir = tmp_path / "data"

    result = main(["--case", str(case), "--data-dir", str(data_dir), "fetch-sqp"])

    assert result == 3
    status = json.loads((data_dir / "status" / "amazon-search-query-performance.json").read_text(encoding="utf-8"))
    assert status["requested_periods"][0]["report_id"] == "R-SAVED-BEFORE-POLL"
    assert status["requested_periods"][0]["status"] == "IN_PROGRESS"


def test_resume_sqp_keeps_overall_available_when_another_week_has_rows(tmp_path, monkeypatch):
    case = tmp_path / "case.json"
    case.write_text(json.dumps({
        "case_id": "case-1", "marketplace": "US", "own_asin": "B0SYNTH001",
        "competitors": [], "period": {"start": "2026-07-12", "end": "2026-07-25"}
    }), encoding="utf-8")
    for name in ("SP_API_LWA_CLIENT_ID", "SP_API_LWA_CLIENT_SECRET", "SP_API_REFRESH_TOKEN", "SP_API_MARKETPLACE_ID"):
        monkeypatch.setenv(name, "secret-test-value")

    class EmptyFinalWeekClient:
        def __init__(self, *args, **kwargs):
            pass

        def fetch_report_by_id(self, *args, **kwargs):
            return {"dataByAsin": []}

    monkeypatch.setattr("xiyou_skill.cli.SalesTrafficClient", EmptyFinalWeekClient)
    data_dir = tmp_path / "data"
    status_dir = data_dir / "status"
    status_dir.mkdir(parents=True)
    (status_dir / "amazon-search-query-performance.json").write_text(json.dumps({
        "source_name": "AMAZON_SEARCH_QUERY_PERFORMANCE",
        "requested_periods": [{
            "start": "2026-07-12", "end": "2026-07-18", "report_id": "R-NONEMPTY",
            "status": "AVAILABLE", "artifact_id": "ART-NONEMPTY", "records": 9,
        }],
    }), encoding="utf-8")

    result = main([
        "--case", str(case), "--data-dir", str(data_dir), "resume-sqp",
        "--report-id", "R-EMPTY-FINAL", "--period-start", "2026-07-19", "--period-end", "2026-07-25",
    ])

    assert result == 0
    status = json.loads((status_dir / "amazon-search-query-performance.json").read_text(encoding="utf-8"))
    assert status["status"] == "AVAILABLE"
    assert status["covered_complete_weeks"] == 2
    assert set(status["artifact_ids"]) == {"ART-NONEMPTY", status["requested_periods"][1]["artifact_id"]}
