from datetime import date

from xiyou_skill.models import CaseConfig, MetricRecord
from xiyou_skill.report import render_report


def case():
    return CaseConfig("case-1", "US", "B0SYNTH001", ("B0SYNTH002",), date(2026, 7, 12), date(2026, 8, 10))


def test_report_is_explicitly_blocked_without_real_records(tmp_path):
    output = tmp_path / "analysis.md"
    render_report(case(), [], output)
    text = output.read_text(encoding="utf-8")
    assert "BLOCKED" in text
    assert "未获得真实西柚官方导出" in text
    assert "未获得 Amazon Sales and Traffic" in text


def test_report_marks_amazon_only_case_partial_not_blocked(tmp_path):
    amazon_only_case = CaseConfig(
        "amazon-only", "US", "B0SYNTH001", (), date(2026, 7, 12), date(2026, 8, 10)
    )
    record = MetricRecord(
        evidence_id="EV-amazon-only", artifact_id="A1", source_name="AMAZON_SALES_TRAFFIC",
        source_level="L1", marketplace="US", asin="B0SYNTH001", period_start="2026-07-12",
        period_end="2026-08-10", metric="sessions", value=14, unit="count", locator="/sessions",
        raw_path="data/raw/A1.json", captured_at="2026-08-12T00:00:00Z",
    )
    output = tmp_path / "amazon-only.md"

    render_report(amazon_only_case, [record], output)

    text = output.read_text(encoding="utf-8")
    assert "状态：**PARTIAL_AMAZON_ONLY**" in text
    assert "竞品 ASIN：未提供" in text


def test_report_value_has_evidence_and_raw_locator(tmp_path):
    record = MetricRecord(
        evidence_id="EV-abc", artifact_id="A1", source_name="AMAZON_SALES_TRAFFIC", source_level="L1",
        marketplace="US", asin="B0SYNTH001", period_start="2026-07-12", period_end="2026-08-10",
        metric="sessions", value=99, unit="count", locator="/salesAndTrafficByAsin/0/trafficByAsin/sessions",
        raw_path="data/raw/amazon/A1/report.json", captured_at="2026-08-11T00:00:00Z"
    )
    output = tmp_path / "analysis.md"

    render_report(case(), [record], output)

    text = output.read_text(encoding="utf-8")
    assert "99" in text
    assert "EV-abc" in text
    assert "/salesAndTrafficByAsin/0/trafficByAsin/sessions" in text
    assert "data/raw/amazon/A1/report.json" in text


def test_report_marks_xiyou_only_as_partial_and_summarizes_score_gap(tmp_path):
    records = []
    for evidence_id, asin, value in (("EV-own", "B0SYNTH001", 46), ("EV-peer", "B0SYNTH002", 100)):
        records.append(MetricRecord(
            evidence_id=evidence_id, artifact_id="A1", source_name="XIYOU", source_level="L3",
            marketplace="US", asin=asin, period_start="2026-08-03", period_end="2026-08-09",
            metric="xiyou_7d_traffic_score", value=value, unit="score", locator=f"Sheet1!A{len(records)+2}",
            raw_path="data/raw/xiyou/A1/export.xlsx", captured_at="2026-08-11T00:00:00Z",
        ))
    output = tmp_path / "analysis.md"

    render_report(case(), records, output)

    text = output.read_text(encoding="utf-8")
    assert "PARTIAL_XIYOU_ONLY" in text
    assert "-54.0%" in text
    assert "EV-own" in text
    assert "EV-peer" in text


def test_report_lists_traceable_keyword_opportunity(tmp_path):
    records = []
    for evidence_id, asin, value, rank in (
        ("EV-own-key", "B0SYNTH001", 0.0, None),
        ("EV-peer-key", "B0SYNTH002", 0.45, 4),
    ):
        records.append(MetricRecord(
            evidence_id=evidence_id, artifact_id="A2", source_name="XIYOU", source_level="L3",
            marketplace="US", asin=asin, period_start="2026-08-03", period_end="2026-08-09",
            metric="xiyou_keyword_traffic_share", value=value, unit="percent",
            locator=f"关键词!{('G' if asin == 'B0SYNTH001' else 'K')}2",
            raw_path="data/raw/xiyou/A2/keywords.xlsx", captured_at="2026-08-11T00:00:00Z",
            dimensions={
                "keyword": "dog wipes", "translation": "宠物湿巾", "keyword_tag": "机会词",
                "weekly_search_volume": 26741, "organic_rank": rank,
                "field_locators": {"weekly_search_volume": "关键词!H2"},
            },
        ))
    for evidence_id, asin, value in (
        ("EV-own-low", "B0SYNTH001", 0.0),
        ("EV-peer-low", "B0SYNTH002", 1.0),
    ):
        records.append(MetricRecord(
            evidence_id=evidence_id, artifact_id="A2", source_name="XIYOU", source_level="L3",
            marketplace="US", asin=asin, period_start="2026-08-03", period_end="2026-08-09",
            metric="xiyou_keyword_traffic_share", value=value, unit="percent", locator="关键词!Z9",
            raw_path="data/raw/xiyou/A2/keywords.xlsx", captured_at="2026-08-11T00:00:00Z",
            dimensions={
                "keyword": "irrelevant high volume", "weekly_search_volume": 999999,
                "relevance_score": 10, "organic_rank": None,
                "field_locators": {"weekly_search_volume": "关键词!H9"},
            },
        ))
    output = tmp_path / "analysis.md"

    render_report(case(), records, output)

    text = output.read_text(encoding="utf-8")
    assert "dog wipes" in text
    assert "26,741" in text
    assert "EV-own-key" in text
    assert "EV-peer-key" in text
    assert "关键词!H2" in text
    assert "irrelevant high volume" not in text


def test_report_does_not_mix_keyword_periods_and_prefers_exact_case_period(tmp_path):
    records = []
    periods = (
        ("7d", "2026-08-03", "2026-08-09", 0.00, 0.99, 999999),
        ("30d", "2026-07-12", "2026-08-10", 0.20, 0.30, 26741),
        ("6m", "2026-02-10", "2026-08-10", 0.80, 0.90, 888888),
    )
    for label, period_start, period_end, own_share, peer_share, search_volume in periods:
        for asin, share in (("B0SYNTH001", own_share), ("B0SYNTH002", peer_share)):
            records.append(MetricRecord(
                evidence_id=f"EV-{label}-{asin}", artifact_id=f"A-{label}",
                source_name="XIYOU", source_level="L3", marketplace="US", asin=asin,
                period_start=period_start, period_end=period_end,
                metric="xiyou_keyword_traffic_share", value=share, unit="percent",
                locator=f"{label}!A1", raw_path=f"data/raw/xiyou/{label}.xlsx",
                captured_at="2026-08-11T00:00:00Z",
                dimensions={"keyword": "dog wipes", "weekly_search_volume": search_volume},
            ))
    output = tmp_path / "analysis.md"

    render_report(case(), records, output)

    text = output.read_text(encoding="utf-8")
    assert "关键词明细采用周期：`2026-07-12~2026-08-10`" in text
    assert "26,741" in text
    assert "EV-30d-B0SYNTH001" in text
    assert "EV-30d-B0SYNTH002" in text
    assert "EV-7d-B0SYNTH001" not in text
    assert "EV-6m-B0SYNTH001" not in text


def test_report_renders_missing_weekly_search_volume_without_crashing(tmp_path):
    records = []
    for asin, share in (("B0SYNTH001", 0.0), ("B0SYNTH002", 0.5)):
        records.append(MetricRecord(
            evidence_id=f"EV-missing-volume-{asin}", artifact_id="A-missing-volume",
            source_name="XIYOU", source_level="L3", marketplace="US", asin=asin,
            period_start="2026-07-12", period_end="2026-08-10",
            metric="xiyou_keyword_traffic_share", value=share, unit="percent",
            locator="关键词!A2", raw_path="data/raw/xiyou/missing-volume.xlsx",
            captured_at="2026-08-11T00:00:00Z",
            dimensions={"keyword": "keyword without volume", "weekly_search_volume": None},
        ))
    output = tmp_path / "analysis.md"

    render_report(case(), records, output)

    text = output.read_text(encoding="utf-8")
    assert "| keyword without volume | - / - | - |" in text


def test_report_aggregates_additive_amazon_components_and_recomputes_conversion(tmp_path):
    records = [MetricRecord(
        evidence_id="EV-xiyou", artifact_id="X1", source_name="XIYOU", source_level="L3",
        marketplace="US", asin="B0SYNTH001", period_start="2026-08-03", period_end="2026-08-09",
        metric="xiyou_7d_traffic_score", value=46, unit="score", locator="ASIN数据对比!B2",
        raw_path="data/raw/xiyou/X1/export.xlsx", captured_at="2026-08-11T00:00:00Z",
    )]
    components = (
        ("B0SYNTH001", 17, 640.83, 50, 75),
        ("B0SYNTH003", 1, 19.99, 24, 58),
    )
    for index, (parent, units, sales, sessions, page_views) in enumerate(components):
        for metric, value, unit in (
            ("units_ordered", units, "count"),
            ("ordered_product_sales", sales, "USD"),
            ("sessions", sessions, "count"),
            ("page_views", page_views, "count"),
        ):
            records.append(MetricRecord(
                evidence_id=f"EV-{metric}-{index}", artifact_id="A1", source_name="AMAZON_SALES_TRAFFIC", source_level="L1",
                marketplace="US", asin="B0SYNTH001", period_start="2026-07-12", period_end="2026-08-10",
                metric=metric, value=value, unit=unit, locator=f"/salesAndTrafficByAsin/{index}/{metric}",
                raw_path="data/raw/amazon/A1/report.json", captured_at="2026-08-11T00:00:00Z",
                dimensions={"parent_asin": parent, "child_asin": "B0SYNTH001", "component_index": index},
            ))
    output = tmp_path / "analysis.md"

    render_report(case(), records, output)

    text = output.read_text(encoding="utf-8")
    assert "READY_FOR_REVIEW" in text
    assert "660.82" in text
    assert "74" in text
    assert "133" in text
    assert "24.32%" in text
    assert "B0SYNTH001" in text
    assert "B0SYNTH003" in text
    assert "EV-units_ordered-0" in text
    assert "EV-units_ordered-1" in text
    assert "EV-sessions-0" in text
    assert "EV-sessions-1" in text


def test_report_renders_four_stage_chain_and_diagnostic_sidecar(tmp_path):
    records = [MetricRecord(
        evidence_id="EV-own-key", artifact_id="X1", source_name="XIYOU", source_level="L3",
        marketplace="US", asin="B0SYNTH001", period_start="2026-07-12", period_end="2026-08-10",
        metric="xiyou_keyword_traffic_share", value=0.1, unit="percent", locator="关键词!A2",
        raw_path="data/raw/X1/export.xlsx", captured_at="2026-08-11T00:00:00Z",
        dimensions={"keyword": "dog wipes", "organic_rank": 9},
    )]
    output = tmp_path / "analysis.md"

    render_report(case(), records, output, source_statuses={
        "AMAZON_SEARCH_QUERY_PERFORMANCE": {"status": "BLOCKED_PERMISSION", "reason": "HTTP 403"}
    })

    text = output.read_text(encoding="utf-8")
    assert "覆盖 → 排名 → 点击 → 转化" in text
    assert "BLOCKED_PERMISSION" in text
    assert "Xiyou" not in text
    assert "西柚流量份额不等同 Amazon CTR" in text
    sidecar = output.with_suffix(".diagnostics.json")
    assert sidecar.exists()
    assert "EV-own-key" in sidecar.read_text(encoding="utf-8")


def test_report_declares_latest_capture_rule_for_sales_traffic_versions(tmp_path):
    records = []
    for artifact, captured_at, sessions in (
        ("A-OLD", "2026-08-11T09:39:17Z", 59),
        ("A-NEW", "2026-08-11T10:00:00Z", 74),
    ):
        records.append(MetricRecord(
            evidence_id=f"EV-{artifact}", artifact_id=artifact, source_name="AMAZON_SALES_TRAFFIC",
            source_level="L1", marketplace="US", asin="B0SYNTH001", period_start="2026-07-12",
            period_end="2026-08-10", metric="sessions", value=sessions, unit="count",
            locator="/sessions", raw_path=f"data/raw/{artifact}.json", captured_at=captured_at,
        ))
    output = tmp_path / "analysis.md"

    render_report(case(), records, output)

    text = output.read_text(encoding="utf-8")
    assert "保留 2 个 Sales and Traffic 原始版本" in text
    assert "采用最新采集版本 `A-NEW`" in text
    assert "| Sessions | 74 |" in text
    assert "| Sessions | 118 |" not in text


def test_amazon_summary_uses_case_period_label_not_hardcoded_30_days(tmp_path):
    short_case = CaseConfig(
        "case-7d", "US", "B0SYNTH001", ("B0SYNTH002",),
        date(2026, 8, 3), date(2026, 8, 9),
    )
    record = MetricRecord(
        evidence_id="EV-short", artifact_id="A-SHORT", source_name="AMAZON_SALES_TRAFFIC",
        source_level="L1", marketplace="US", asin="B0SYNTH001", period_start="2026-08-03",
        period_end="2026-08-09", metric="sessions", value=36, unit="count", locator="/sessions",
        raw_path="data/raw/A-SHORT.json", captured_at="2026-08-11T10:00:00Z",
    )
    output = tmp_path / "analysis.md"

    render_report(short_case, [record], output)

    text = output.read_text(encoding="utf-8")
    assert "| 指标 | Case 周期结果 | 单位 | 证据 |" in text
    assert "| 指标 | 30 天结果 |" not in text


def test_report_contains_all_sop_v51_modules_and_evidence_boundaries(tmp_path):
    record = MetricRecord(
        evidence_id="EV-real", artifact_id="A-REAL", source_name="AMAZON_SALES_TRAFFIC",
        source_level="L1", marketplace="US", asin="B0SYNTH001", period_start="2026-07-12",
        period_end="2026-08-10", metric="sessions", value=109, unit="count",
        locator="/salesAndTrafficByAsin/0/trafficByAsin/sessions",
        raw_path="data/raw/amazon/A-REAL/report.json", captured_at="2026-08-11T10:00:00Z",
    )
    output = tmp_path / "analysis.md"

    render_report(case(), [record], output, source_statuses={
        "AMAZON_SEARCH_QUERY_PERFORMANCE": {
            "status": "PARTIAL_AVAILABLE_EMPTY", "reason": "1/4 weeks returned empty"
        }
    })

    text = output.read_text(encoding="utf-8")
    modules = (
        "基础信息", "一句话结论", "宏观诊断", "关键词机会", "产品差距", "Listing 差距",
        "价格评价", "广告差距", "根因", "优先级", "行动方案", "验证方案", "待验证项", "复盘结论",
    )
    for index, title in enumerate(modules, 1):
        assert f"## {index}. {title}" in text
    assert "L1" in text and "L3" in text
    assert "不得解释为零曝光或零点击" in text
    assert "不作归因" in text
    assert "EV-real" in text
