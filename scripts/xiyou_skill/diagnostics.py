from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from .models import CaseConfig, MetricRecord
from .source_versions import select_latest_source_artifact


@dataclass(frozen=True)
class DiagnosticMetric:
    value: Any
    unit: str
    formula: str
    source_level: str
    evidence_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DiagnosticStage:
    stage: str
    status: str
    summary: str
    metrics: dict[str, DiagnosticMetric]

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "status": self.status,
            "summary": self.summary,
            "metrics": {key: metric.to_dict() for key, metric in self.metrics.items()},
        }


def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except Exception:
        return None


def _positive(value: Any) -> bool:
    number = _number(value)
    return number is not None and number > 0


def _rank(value: Any) -> Decimal | None:
    number = _number(value)
    return number if number is not None and number > 0 else None


def _covered(record: MetricRecord) -> bool:
    dimensions = record.dimensions
    return any((
        _rank(dimensions.get("organic_rank")) is not None,
        _rank(dimensions.get("sp_ad_rank")) is not None,
        bool(dimensions.get("placements")),
        _positive(dimensions.get("traffic_share_of_asin")),
        _positive(record.value),
    ))


def _metric(
    value: Any, unit: str, formula: str, source_level: str, records: list[MetricRecord]
) -> DiagnosticMetric:
    return DiagnosticMetric(
        value=value, unit=unit, formula=formula, source_level=source_level,
        evidence_ids=tuple(dict.fromkeys(record.evidence_id for record in records)),
    )


def _selected_keywords(case: CaseConfig, records: list[MetricRecord]) -> list[MetricRecord]:
    keyword_records = [record for record in records if record.metric == "xiyou_keyword_traffic_share"]
    exact = (case.period_start.isoformat(), case.period_end.isoformat())
    exact_records = [
        record for record in keyword_records
        if (record.period_start, record.period_end) == exact
    ]
    return exact_records


def _status_reason(source_statuses: dict[str, dict[str, Any]], source: str) -> tuple[str | None, str | None]:
    status = source_statuses.get(source, {})
    return status.get("status"), status.get("reason")


def build_diagnostic_chain(
    case: CaseConfig,
    records: list[MetricRecord],
    source_statuses: dict[str, dict[str, Any]] | None = None,
) -> dict[str, DiagnosticStage]:
    source_statuses = source_statuses or {}
    keyword_records = _selected_keywords(case, records)
    grouped: dict[str, list[MetricRecord]] = {}
    for record in keyword_records:
        keyword = record.dimensions.get("keyword")
        if keyword:
            grouped.setdefault(str(keyword), []).append(record)

    own_by_keyword: dict[str, MetricRecord] = {}
    competitor_by_keyword: dict[str, list[MetricRecord]] = {}
    for keyword, group in grouped.items():
        own = next((record for record in group if record.asin == case.own_asin), None)
        if own:
            own_by_keyword[keyword] = own
        competitor_by_keyword[keyword] = [record for record in group if record.asin in case.competitors]

    own_rows = list(own_by_keyword.values())
    own_covered = [record for record in own_rows if _covered(record)]
    competitor_covered_own_missing: list[MetricRecord] = []
    competitor_gap_evidence: list[MetricRecord] = []
    for keyword, peers in competitor_by_keyword.items():
        own = own_by_keyword.get(keyword)
        covered_peers = [peer for peer in peers if _covered(peer)]
        if covered_peers and (own is None or not _covered(own)):
            if own:
                competitor_covered_own_missing.append(own)
            competitor_gap_evidence.extend(([own] if own else []) + covered_peers)

    coverage_metrics = {
        "keyword_universe": _metric(
            len(grouped), "queries", "count(distinct keyword) in exact Case-period 西柚 rows", "L3", keyword_records
        ),
        "own_covered_queries": _metric(
            len(own_covered), "queries",
            "count(query where organic rank, SP rank, placement, ASIN traffic share, or competitive share is positive)",
            "L3", own_rows,
        ),
        "competitor_covered_own_missing": _metric(
            len(competitor_covered_own_missing), "queries",
            "count(query where any competitor is covered and own ASIN is not covered)",
            "L3", competitor_gap_evidence,
        ),
    }
    coverage = DiagnosticStage(
        "coverage", "AVAILABLE" if keyword_records else "MISSING_DATA",
        (
            f"自身覆盖 {len(own_covered)}/{len(grouped)} 个查询；竞品已覆盖而自身缺失 "
            f"{len(competitor_covered_own_missing)} 个。"
            if keyword_records else "缺少与 Case 周期精确匹配的西柚关键词明细。"
        ), coverage_metrics,
    )

    organic_ranked = [record for record in own_rows if _rank(record.dimensions.get("organic_rank")) is not None]
    ad_ranked = [record for record in own_rows if _rank(record.dimensions.get("sp_ad_rank")) is not None]
    top10 = [record for record in organic_ranked if _rank(record.dimensions.get("organic_rank")) <= 10]
    top20 = [record for record in organic_ranked if _rank(record.dimensions.get("organic_rank")) <= 20]
    behind: list[MetricRecord] = []
    behind_evidence: list[MetricRecord] = []
    for keyword, own in own_by_keyword.items():
        own_rank = _rank(own.dimensions.get("organic_rank"))
        peer_pairs = [
            (peer, _rank(peer.dimensions.get("organic_rank")))
            for peer in competitor_by_keyword.get(keyword, [])
        ]
        peer_pairs = [(peer, rank) for peer, rank in peer_pairs if rank is not None]
        if own_rank is not None and peer_pairs:
            best_peer, best_rank = min(peer_pairs, key=lambda pair: pair[1])
            if own_rank > best_rank:
                behind.append(own)
                behind_evidence.extend((own, best_peer))
    ranking_metrics = {
        "own_organic_ranked": _metric(len(organic_ranked), "queries", "count(organic_rank > 0)", "L3", own_rows),
        "own_ad_ranked": _metric(len(ad_ranked), "queries", "count(SP ad rank > 0)", "L3", own_rows),
        "own_organic_top10": _metric(len(top10), "queries", "count(0 < organic rank <= 10)", "L3", organic_ranked),
        "own_organic_top20": _metric(len(top20), "queries", "count(0 < organic rank <= 20)", "L3", organic_ranked),
        "own_behind_best_competitor": _metric(
            len(behind), "queries", "count(common query where own organic rank > best competitor organic rank)",
            "L3", behind_evidence,
        ),
    }
    ranking = DiagnosticStage(
        "ranking", "AVAILABLE" if keyword_records else "MISSING_DATA",
        (
            f"自身自然排名覆盖 {len(organic_ranked)} 个查询，其中 Top 10 为 {len(top10)}、Top 20 为 {len(top20)}；"
            f"同词落后最优竞品 {len(behind)} 个。"
            if keyword_records else "缺少与 Case 周期精确匹配的西柚排名明细。"
        ), ranking_metrics,
    )

    impressions = [record for record in records if record.source_name == "AMAZON_SEARCH_QUERY_PERFORMANCE" and record.asin == case.own_asin and record.metric == "sqp_impressions"]
    clicks = [record for record in records if record.source_name == "AMAZON_SEARCH_QUERY_PERFORMANCE" and record.asin == case.own_asin and record.metric == "sqp_clicks"]
    purchases = [record for record in records if record.source_name == "AMAZON_SEARCH_QUERY_PERFORMANCE" and record.asin == case.own_asin and record.metric == "sqp_purchases"]
    impression_total = sum((_number(record.value) or Decimal("0") for record in impressions), Decimal("0"))
    click_total = sum((_number(record.value) or Decimal("0") for record in clicks), Decimal("0"))
    purchase_total = sum((_number(record.value) or Decimal("0") for record in purchases), Decimal("0"))

    ranked = list(dict.fromkeys(record.evidence_id for record in organic_ranked + ad_ranked))
    ranked_records = [record for record in own_rows if record.evidence_id in ranked]
    ranked_positive_share = [record for record in ranked_records if _positive(record.value)]
    click_metrics: dict[str, DiagnosticMetric] = {}
    sqp_status, sqp_reason = _status_reason(source_statuses, "AMAZON_SEARCH_QUERY_PERFORMANCE")
    if impressions and clicks:
        click_metrics.update({
            "sqp_impressions": _metric(impression_total, "count", "sum(asinImpressionCount)", "L1", impressions),
            "sqp_clicks": _metric(click_total, "count", "sum(asinClickCount)", "L1", clicks),
            "sqp_ctr": _metric(
                float(click_total / impression_total * 100) if impression_total else None,
                "percent", "sum(asinClickCount) / sum(asinImpressionCount) * 100", "L1", impressions + clicks,
            ),
        })
        click_status = sqp_status if str(sqp_status).startswith("PARTIAL_") else "AVAILABLE"
        partial_note = "；仅基于已返回周，不能代表完整 Case 周期" if click_status.startswith("PARTIAL_") else ""
        click_summary = f"Amazon SQP 曝光 {impression_total}、点击 {click_total}，CTR 按真实计数重算{partial_note}。"
    else:
        click_metrics.update({
            "ranked_queries_with_positive_xiyou_share": _metric(
                len(ranked_positive_share), "queries",
                "count(ranked query where 西柚 competitive traffic share > 0); proxy only",
                "L3", ranked_records,
            ),
            "ranked_queries_with_zero_xiyou_share": _metric(
                len(ranked_records) - len(ranked_positive_share), "queries",
                "count(ranked query where 西柚 competitive traffic share = 0); proxy only",
                "L3", ranked_records,
            ),
        })
        if sqp_status in {
            "BLOCKED_PERMISSION", "FAILED_API", "IN_PROGRESS", "AVAILABLE_EMPTY",
            "PARTIAL_AVAILABLE", "PARTIAL_AVAILABLE_EMPTY",
        }:
            click_status = sqp_status
            click_summary = f"Amazon SQP {sqp_status}：{sqp_reason or '未提供原因'}。西柚流量份额仅作代理。"
        elif keyword_records:
            click_status = "PROXY_ONLY"
            click_summary = "没有 Amazon SQP 点击数据；仅展示西柚排名与流量份额代理。"
        else:
            click_status = "MISSING_DATA"
            click_summary = "没有 Amazon SQP 点击数据，也没有可用的西柚代理数据。"
    click = DiagnosticStage("click", click_status, click_summary, click_metrics)

    conversion_metrics: dict[str, DiagnosticMetric] = {}
    if clicks and purchases:
        conversion_metrics.update({
            "sqp_purchases": _metric(purchase_total, "count", "sum(asinPurchaseCount)", "L1", purchases),
            "sqp_click_purchase_rate": _metric(
                float(purchase_total / click_total * 100) if click_total else None,
                "percent", "sum(asinPurchaseCount) / sum(asinClickCount) * 100", "L1", clicks + purchases,
            ),
        })
        conversion_status = sqp_status if str(sqp_status).startswith("PARTIAL_") else "AVAILABLE"
        partial_note = "；仅基于已返回周，不能代表完整 Case 周期" if conversion_status.startswith("PARTIAL_") else ""
        conversion_summary = f"Amazon SQP 提供查询级点击与购买，可计算点击→购买转化{partial_note}。"
    else:
        _, latest_sales_traffic = select_latest_source_artifact(records, "AMAZON_SALES_TRAFFIC")
        sessions = [record for record in latest_sales_traffic if record.asin == case.own_asin and record.metric == "sessions"]
        units = [record for record in latest_sales_traffic if record.asin == case.own_asin and record.metric == "units_ordered"]
        session_total = sum((_number(record.value) or Decimal("0") for record in sessions), Decimal("0"))
        unit_total = sum((_number(record.value) or Decimal("0") for record in units), Decimal("0"))
        if sessions and units:
            conversion_metrics.update({
                "sales_traffic_sessions": _metric(session_total, "count", "sum(sessions across child-parent components)", "L1", sessions),
                "sales_traffic_units": _metric(unit_total, "count", "sum(unitsOrdered across child-parent components)", "L1", units),
                "unit_session_percentage": _metric(
                    float(unit_total / session_total * 100) if session_total else None,
                    "percent", "sum(unitsOrdered) / sum(sessions) * 100", "L1", sessions + units,
                ),
            })
            conversion_status = "AVAILABLE"
            conversion_summary = "仅有 Sales and Traffic 的 ASIN 级 Sessions→Units；不能归因到查询或点击。"
        else:
            conversion_status = "MISSING_DATA"
            conversion_summary = "缺少 SQP 点击/购买，也缺少完整的 Sales and Traffic Sessions/Units。"
    conversion = DiagnosticStage("conversion", conversion_status, conversion_summary, conversion_metrics)

    return {"coverage": coverage, "ranking": ranking, "click": click, "conversion": conversion}

