import json
from datetime import date

from xiyou_skill.models import CaseConfig, MetricRecord, load_case


def _record(evidence_id, source, metric, value, *, asin="B0SYNTH001", dimensions=None):
    return MetricRecord(
        evidence_id=evidence_id,
        artifact_id=f"ART-{source}",
        source_name=source,
        source_level="L1" if source.startswith("AMAZON") else "L3",
        marketplace="US",
        asin=asin,
        period_start="2026-07-12",
        period_end="2026-08-10",
        metric=metric,
        value=value,
        unit="count",
        locator=f"/{metric}",
        raw_path=f"data/raw/{source}/source.json",
        captured_at="2026-08-11T00:00:00Z",
        dimensions=dimensions or {},
        case_id="case-1",
        run_id="run-2",
    )


def test_load_case_accepts_structured_competitors_and_governance_fields(tmp_path):
    path = tmp_path / "case.json"
    path.write_text(json.dumps({
        "case_id": "case-1",
        "run_id": "run-2",
        "marketplace": "US",
        "own_asin": "B0SYNTH001",
        "competitors": [{"asin": "B0SYNTH002", "tier": "A", "reason": "same use case"}],
        "period": {"start": "2026-07-12", "end": "2026-08-10"},
        "ruleset_version": "sop-v5.1",
        "lifecycle": "growth",
        "objective": "综合诊断",
        "competitor_review_status": "APPROVED",
        "event_history_status": "CONFIRMED",
        "known_events": [{"type": "coupon", "start": "2026-08-01", "end": "2026-08-10"}],
    }), encoding="utf-8")

    case = load_case(path)

    assert case.competitors == ("B0SYNTH002",)
    assert case.run_id == "run-2"
    assert case.ruleset_version == "sop-v5.1"
    assert case.lifecycle == "growth"
    assert case.competitor_metadata[0]["tier"] == "A"
    assert case.known_events[0]["type"] == "coupon"


def test_metric_record_reads_legacy_json_without_case_or_run():
    payload = _record("EV-1", "XIYOU", "xiyou_7d_traffic_score", 46).to_dict()
    payload.pop("case_id")
    payload.pop("run_id")

    record = MetricRecord.from_dict(payload)

    assert record.case_id == ""
    assert record.run_id == ""


def test_governance_builds_traceable_claim_action_and_review_plan():
    from xiyou_skill.governance import build_governance_bundle

    case = CaseConfig(
        "case-1", "US", "B0SYNTH001", ("B0SYNTH002",),
        date(2026, 7, 12), date(2026, 8, 10), run_id="run-2",
        objective="diagnose a confirmed traffic decline",
    )
    records = [
        _record("EV-own", "XIYOU", "xiyou_keyword_traffic_share", 0, dimensions={"keyword": "dog wipes"}),
        _record(
            "EV-peer", "XIYOU", "xiyou_keyword_traffic_share", 0.4,
            asin="B0SYNTH002", dimensions={"keyword": "dog wipes", "organic_rank": 4},
        ),
        _record("EV-sessions", "AMAZON_SALES_TRAFFIC", "sessions", 74),
        _record("EV-units", "AMAZON_SALES_TRAFFIC", "units_ordered", 18),
    ]

    bundle = build_governance_bundle(case, records, {})

    claim = bundle["diagnostic_claims"][0]
    assert claim["stage"] == "coverage"
    assert claim["claim_type"] == "CANDIDATE_ROOT_CAUSE"
    assert {"EV-own", "EV-peer"}.issubset(set(claim["evidence_ids"]))
    assert claim["alternative_causes"]
    assert claim["missing_evidence"]
    assert claim["falsification_condition"]
    assert claim["confidence"] == "LOW"
    action = bundle["action_plan"][0]
    assert action["claim_id"] == claim["claim_id"]
    assert action["approval_status"] == "PENDING_HUMAN_REVIEW"
    assert action["primary_metric"]
    assert action["guardrail_metrics"]
    assert action["stop_condition"]
    assert [item["day"] for item in bundle["review_plan"]] == [7, 14, 30]


def test_quality_gates_do_not_pass_missing_approvals_ads_or_event_history():
    from xiyou_skill.governance import build_governance_bundle

    case = CaseConfig(
        "case-1", "US", "B0SYNTH001", ("B0SYNTH002",),
        date(2026, 7, 12), date(2026, 8, 10), run_id="run-2",
        objective="diagnose a confirmed traffic decline",
    )
    records = [
        _record("EV-own", "XIYOU", "xiyou_keyword_traffic_share", 0, dimensions={"keyword": "dog wipes"}),
        _record(
            "EV-peer", "XIYOU", "xiyou_keyword_traffic_share", 0.4,
            asin="B0SYNTH002", dimensions={"keyword": "dog wipes", "organic_rank": 4},
        ),
        _record("EV-sessions", "AMAZON_SALES_TRAFFIC", "sessions", 74),
        _record("EV-units", "AMAZON_SALES_TRAFFIC", "units_ordered", 18),
    ]

    gates = {gate["gate_id"]: gate for gate in build_governance_bundle(case, records, {})["quality_gates"]}

    assert gates["G0"]["status"] == "PASS"
    assert gates["G1"]["status"] == "REVIEW_REQUIRED"
    assert gates["G2"]["status"] == "PASS"
    assert gates["G3"]["status"] == "REVIEW_REQUIRED"
    assert gates["G4"]["status"] == "PASS"
    assert gates["G5"]["status"] == "REVIEW_REQUIRED"
    assert gates["G6"]["status"] == "PASS"
    assert gates["G7"]["status"] == "REVIEW_REQUIRED"
    assert "Amazon Ads" in " ".join(gates["G3"]["issues"])


def test_report_writes_governance_sidecars(tmp_path):
    from xiyou_skill.report import render_report

    case = CaseConfig(
        "case-1", "US", "B0SYNTH001", ("B0SYNTH002",),
        date(2026, 7, 12), date(2026, 8, 10), run_id="run-2",
    )
    records = [
        _record("EV-own", "XIYOU", "xiyou_keyword_traffic_share", 0, dimensions={"keyword": "dog wipes"}),
        _record(
            "EV-peer", "XIYOU", "xiyou_keyword_traffic_share", 0.4,
            asin="B0SYNTH002", dimensions={"keyword": "dog wipes", "organic_rank": 4},
        ),
        _record("EV-sessions", "AMAZON_SALES_TRAFFIC", "sessions", 74),
        _record("EV-units", "AMAZON_SALES_TRAFFIC", "units_ordered", 18),
    ]
    output = tmp_path / "analysis.md"

    render_report(case, records, output)

    expected = {
        "analysis.quality-gates.json",
        "analysis.claims.json",
        "analysis.action-plan.json",
        "analysis.review-plan.json",
    }
    assert expected.issubset({path.name for path in tmp_path.iterdir()})
    claims = json.loads((tmp_path / "analysis.claims.json").read_text(encoding="utf-8"))
    assert claims["case_id"] == "case-1"
    assert claims["run_id"] == "run-2"
    assert claims["diagnostic_claims"][0]["evidence_ids"]
    report = output.read_text(encoding="utf-8")
    assert "G0–G7 质量门" in report
    assert "| G1 | 竞品可比性 | REVIEW_REQUIRED |" in report
    assert "PENDING_HUMAN_REVIEW" in report


def test_cli_explicit_runs_do_not_share_normalized_records(tmp_path):
    from xiyou_skill.cli import main

    source = tmp_path / "sales.json"
    source.write_text(json.dumps({"salesAndTrafficByAsin": [{
        "parentAsin": "B0SYNTH001", "childAsin": "B0SYNTH001",
        "trafficByAsin": {"sessions": 74},
    }]}), encoding="utf-8")
    cases = []
    for run_id in ("run-a", "run-b"):
        path = tmp_path / f"{run_id}.json"
        path.write_text(json.dumps({
            "case_id": "case-1", "run_id": run_id, "marketplace": "US",
            "own_asin": "B0SYNTH001", "competitors": [],
            "period": {"start": "2026-07-12", "end": "2026-08-10"},
        }), encoding="utf-8")
        cases.append(path)
    data_dir = tmp_path / "data"

    assert main([
        "--case", str(cases[0]), "--data-dir", str(data_dir),
        "ingest-amazon", "--file", str(source),
    ]) == 0
    global_status = data_dir / "status"
    global_status.mkdir(parents=True)
    (global_status / "amazon-search-query-performance.json").write_text(json.dumps({
        "source_name": "AMAZON_SEARCH_QUERY_PERFORMANCE", "status": "AVAILABLE",
    }), encoding="utf-8")
    output = tmp_path / "run-b.md"
    assert main([
        "--case", str(cases[1]), "--data-dir", str(data_dir),
        "build-report", "--output", str(output),
    ]) == 0

    assert "状态：**BLOCKED**" in output.read_text(encoding="utf-8")
    assert "Amazon SQP（L1）：**MISSING_DATA**" in output.read_text(encoding="utf-8")
    assert (data_dir / "runs" / "case-1" / "run-a" / "normalized" / "metrics.jsonl").exists()
    assert not (data_dir / "runs" / "case-1" / "run-b" / "normalized" / "metrics.jsonl").exists()
