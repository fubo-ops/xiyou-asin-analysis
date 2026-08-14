from datetime import date

import pytest

from xiyou_skill.diagnostics import build_diagnostic_chain
from xiyou_skill.models import CaseConfig, MetricRecord


def case():
    return CaseConfig("case-1", "US", "B0SYNTH001", ("B0SYNTH002",), date(2026, 7, 12), date(2026, 8, 10))


def record(evidence_id, asin, keyword, share, organic_rank=None, sp_ad_rank=None):
    return MetricRecord(
        evidence_id=evidence_id, artifact_id="X1", source_name="XIYOU", source_level="L3",
        marketplace="US", asin=asin, period_start="2026-07-12", period_end="2026-08-10",
        metric="xiyou_keyword_traffic_share", value=share, unit="percent", locator=f"关键词!{evidence_id}",
        raw_path="data/raw/X1/export.xlsx", captured_at="2026-08-11T00:00:00Z",
        dimensions={"keyword": keyword, "organic_rank": organic_rank, "sp_ad_rank": sp_ad_rank},
    )


def test_chain_computes_coverage_and_rank_without_calling_share_ctr():
    records = [
        record("EV-own-1", "B0SYNTH001", "dog wipes", 0.05, organic_rank=18),
        record("EV-peer-1", "B0SYNTH002", "dog wipes", 0.20, organic_rank=4),
        record("EV-own-2", "B0SYNTH001", "pet wipes", 0.0),
        record("EV-peer-2", "B0SYNTH002", "pet wipes", 0.30, organic_rank=7),
    ]

    chain = build_diagnostic_chain(case(), records)

    coverage = chain["coverage"]
    ranking = chain["ranking"]
    click = chain["click"]
    assert coverage.status == "AVAILABLE"
    assert coverage.metrics["own_covered_queries"].value == 1
    assert coverage.metrics["competitor_covered_own_missing"].value == 1
    assert ranking.metrics["own_organic_top20"].value == 1
    assert ranking.metrics["own_behind_best_competitor"].value == 1
    assert click.status == "PROXY_ONLY"
    assert "CTR" not in click.metrics
    assert click.metrics["ranked_queries_with_positive_xiyou_share"].value == 1


def test_chain_uses_real_sqp_for_click_and_purchase_conversion():
    records = [
        MetricRecord(
            evidence_id=f"EV-{metric}", artifact_id="SQP1", source_name="AMAZON_SEARCH_QUERY_PERFORMANCE",
            source_level="L1", marketplace="US", asin="B0SYNTH001", period_start="2026-07-12",
            period_end="2026-07-18", metric=metric, value=value, unit="count", locator=f"/{metric}",
            raw_path="data/raw/SQP1/sqp.json", captured_at="2026-08-11T00:00:00Z",
            dimensions={"search_query": "dog wipes"},
        ) for metric, value in (("sqp_impressions", 100), ("sqp_clicks", 20), ("sqp_purchases", 5))
    ]

    chain = build_diagnostic_chain(case(), records)

    assert chain["click"].status == "AVAILABLE"
    assert chain["click"].metrics["sqp_ctr"].value == 20
    assert chain["conversion"].metrics["sqp_click_purchase_rate"].value == 25
    assert set(chain["click"].metrics["sqp_ctr"].evidence_ids) == {"EV-sqp_impressions", "EV-sqp_clicks"}


def test_chain_marks_real_sqp_metrics_partial_when_week_coverage_is_incomplete():
    records = [
        MetricRecord(
            evidence_id=f"EV-{metric}", artifact_id="SQP-PARTIAL",
            source_name="AMAZON_SEARCH_QUERY_PERFORMANCE", source_level="L1",
            marketplace="US", asin="B0SYNTH001", period_start="2026-07-26",
            period_end="2026-08-01", metric=metric, value=value, unit="count",
            locator=f"/{metric}", raw_path="data/raw/SQP-PARTIAL/sqp.json",
            captured_at="2026-08-12T00:00:00Z", dimensions={"search_query": "idesea"},
        ) for metric, value in (("sqp_impressions", 15), ("sqp_clicks", 3), ("sqp_purchases", 2))
    ]

    chain = build_diagnostic_chain(case(), records, {
        "AMAZON_SEARCH_QUERY_PERFORMANCE": {
            "status": "PARTIAL_AVAILABLE", "covered_complete_weeks": 3,
            "expected_complete_weeks": 4, "reason": "仅覆盖 3/4 周",
        }
    })

    assert chain["click"].status == "PARTIAL_AVAILABLE"
    assert "仅基于已返回周" in chain["click"].summary
    assert chain["conversion"].status == "PARTIAL_AVAILABLE"
    assert "仅基于已返回周" in chain["conversion"].summary


def test_chain_preserves_permission_block_instead_of_guessing():
    chain = build_diagnostic_chain(case(), [], {
        "AMAZON_SEARCH_QUERY_PERFORMANCE": {
            "status": "BLOCKED_PERMISSION", "reason": "requires Brand Analytics role"
        }
    })

    assert chain["click"].status == "BLOCKED_PERMISSION"
    assert "requires Brand Analytics role" in chain["click"].summary
    assert chain["conversion"].status == "MISSING_DATA"


def test_chain_reports_sqp_processing_failure_while_retaining_only_proxy_metrics():
    records = [record("EV-own-1", "B0SYNTH001", "dog wipes", 0.05, organic_rank=18)]

    chain = build_diagnostic_chain(case(), records, {
        "AMAZON_SEARCH_QUERY_PERFORMANCE": {
            "status": "FAILED_API", "reason": "Amazon report remained IN_PROGRESS"
        }
    })

    assert chain["click"].status == "FAILED_API"
    assert "remained IN_PROGRESS" in chain["click"].summary
    assert "ranked_queries_with_positive_xiyou_share" in chain["click"].metrics


def test_chain_uses_latest_sales_traffic_artifact_without_summing_versions():
    records = []
    for artifact, captured_at, sessions in (
        ("A-OLD", "2026-08-11T09:39:17Z", 59),
        ("A-NEW", "2026-08-11T10:00:00Z", 74),
    ):
        for metric, value in (("sessions", sessions), ("units_ordered", 18)):
            records.append(MetricRecord(
                evidence_id=f"EV-{artifact}-{metric}", artifact_id=artifact,
                source_name="AMAZON_SALES_TRAFFIC", source_level="L1", marketplace="US",
                asin="B0SYNTH001", period_start="2026-07-12", period_end="2026-08-10",
                metric=metric, value=value, unit="count", locator=f"/{metric}",
                raw_path=f"data/raw/{artifact}.json", captured_at=captured_at,
            ))

    chain = build_diagnostic_chain(case(), records)

    conversion = chain["conversion"].metrics
    assert conversion["sales_traffic_sessions"].value == 74
    assert conversion["sales_traffic_units"].value == 18
    assert conversion["unit_session_percentage"].value == pytest.approx(24.3243, rel=1e-4)
    assert set(conversion["sales_traffic_sessions"].evidence_ids) == {"EV-A-NEW-sessions"}


def test_chain_ignores_amazon_records_from_other_case_asins():
    records = []
    for asin, sessions, units in (("B0SYNTH001", 10, 2), ("B0SYNTH007", 1000, 900)):
        for metric, value in (("sessions", sessions), ("units_ordered", units)):
            records.append(MetricRecord(
                evidence_id=f"EV-{asin}-{metric}", artifact_id="A-SHARED",
                source_name="AMAZON_SALES_TRAFFIC", source_level="L1", marketplace="US",
                asin=asin, period_start="2026-07-12", period_end="2026-08-10",
                metric=metric, value=value, unit="count", locator=f"/{asin}/{metric}",
                raw_path="data/raw/shared.json", captured_at="2026-08-12T00:00:00Z",
            ))

    chain = build_diagnostic_chain(case(), records)

    assert chain["conversion"].metrics["sales_traffic_sessions"].value == 10
    assert chain["conversion"].metrics["sales_traffic_units"].value == 2
