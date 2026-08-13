from __future__ import annotations

import json
import statistics
from datetime import date
from decimal import Decimal
from pathlib import Path

from .models import CaseConfig, MetricRecord
from .diagnostics import DiagnosticMetric, build_diagnostic_chain
from .source_versions import select_latest_source_artifact, source_artifact_ids
from .governance import build_governance_bundle


def _display(value) -> str:
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def _keyword_opportunities(case: CaseConfig, records: list[MetricRecord]) -> list[tuple[MetricRecord, MetricRecord]]:
    grouped: dict[str, list[MetricRecord]] = {}
    for record in records:
        if record.metric == "xiyou_keyword_traffic_share" and record.dimensions.get("keyword"):
            grouped.setdefault(str(record.dimensions["keyword"]), []).append(record)
    opportunities = []
    for group in grouped.values():
        own = next((record for record in group if record.asin == case.own_asin), None)
        peers = [record for record in group if record.asin in case.competitors and isinstance(record.value, (int, float))]
        if own is None or not peers or not isinstance(own.value, (int, float)):
            continue
        relevance = own.dimensions.get("relevance_score")
        if isinstance(relevance, (int, float)) and relevance < 60:
            continue
        best_peer = max(peers, key=lambda record: record.value)
        if best_peer.value <= own.value:
            continue
        opportunities.append((own, best_peer))
    opportunities.sort(
        key=lambda pair: (
            pair[0].dimensions.get("weekly_search_volume") or 0,
            pair[1].value - pair[0].value,
        ),
        reverse=True,
    )
    return opportunities[:10]


def _select_keyword_period(case: CaseConfig, records: list[MetricRecord]) -> tuple[str, str] | None:
    periods = {(record.period_start, record.period_end) for record in records}
    exact = (case.period_start.isoformat(), case.period_end.isoformat())
    if exact in periods:
        return exact
    if not periods:
        return None

    case_days = (case.period_end - case.period_start).days + 1

    def distance(period: tuple[str, str]) -> tuple[int, int, int]:
        start, end = (date.fromisoformat(value) for value in period)
        period_days = (end - start).days + 1
        overlap_start = max(start, case.period_start)
        overlap_end = min(end, case.period_end)
        overlap_days = max(0, (overlap_end - overlap_start).days + 1)
        return abs(period_days - case_days), -overlap_days, -end.toordinal()

    return min(periods, key=distance)


def _amazon_records(case: CaseConfig, records: list[MetricRecord], metric: str) -> list[MetricRecord]:
    return [
        record for record in records
        if record.source_name == "AMAZON_SALES_TRAFFIC"
        and record.asin == case.own_asin
        and record.metric == metric
        and isinstance(record.value, (int, float))
    ]


def _sum_values(records: list[MetricRecord]) -> Decimal:
    return sum((Decimal(str(record.value)) for record in records), Decimal("0"))


def _evidence_list(records: list[MetricRecord]) -> str:
    return ", ".join(f"`{record.evidence_id}`" for record in records)


def _diagnostic_value(metric: DiagnosticMetric) -> str:
    if metric.value is None:
        return "不可计算"
    if metric.unit == "percent":
        return f"{float(metric.value):.2f}%"
    if isinstance(metric.value, Decimal):
        return f"{metric.value:f}"
    return _display(metric.value)


def _diagnostic_evidence(metric: DiagnosticMetric) -> str:
    if not metric.evidence_ids:
        return "-"
    preview = ", ".join(f"`{value}`" for value in metric.evidence_ids[:3])
    remaining = len(metric.evidence_ids) - 3
    return preview + (f"；另 {remaining} 条见 diagnostics sidecar" if remaining > 0 else "")


def _append_diagnostic_chain(
    lines: list[str], case: CaseConfig, records: list[MetricRecord],
    source_statuses: dict[str, dict], sidecar_path: Path,
) -> None:
    chain = build_diagnostic_chain(case, records, source_statuses)
    labels = {
        "coverage": "覆盖", "ranking": "排名", "click": "点击", "conversion": "转化",
        "keyword_universe": "查询词池",
        "own_covered_queries": "自身覆盖查询",
        "competitor_covered_own_missing": "竞品覆盖而自身缺失",
        "own_organic_ranked": "自身有自然排名",
        "own_ad_ranked": "自身有 SP 广告排名",
        "own_organic_top10": "自然排名 Top 10",
        "own_organic_top20": "自然排名 Top 20",
        "own_behind_best_competitor": "同词落后最优竞品",
        "sqp_impressions": "SQP ASIN 曝光",
        "sqp_clicks": "SQP ASIN 点击",
        "sqp_ctr": "SQP CTR",
        "ranked_queries_with_positive_xiyou_share": "有排名且西柚份额>0（代理）",
        "ranked_queries_with_zero_xiyou_share": "有排名但西柚份额=0（代理）",
        "sqp_purchases": "SQP ASIN 购买",
        "sqp_click_purchase_rate": "SQP 点击→购买率",
        "sales_traffic_sessions": "Sales & Traffic Sessions",
        "sales_traffic_units": "Sales & Traffic Units",
        "unit_session_percentage": "Unit Session %",
    }
    sidecar_payload = {
        "case_id": case.case_id,
        "analysis_period": {"start": case.period_start.isoformat(), "end": case.period_end.isoformat()},
        "source_statuses": source_statuses,
        "stages": {key: stage.to_dict() for key, stage in chain.items()},
    }
    sidecar_path.write_text(json.dumps(sidecar_payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    lines += [
        "### 诊断链：覆盖 → 排名 → 点击 → 转化", "",
        "所有计算只使用与 Case 精确匹配的 30 天西柚关键词明细，以及 Amazon 官方报告的实际可用字段。"
        "西柚流量份额不等同 Amazon CTR；西柚“点击转化率(均值)”也不等同自身 ASIN 的真实 CVR。", "",
        f"完整公式与全部输入 Evidence ID：`{sidecar_path.as_posix()}`。", "",
        "| 阶段 | 状态 | 诊断摘要 |", "|---|---|---|",
    ]
    for key in ("coverage", "ranking", "click", "conversion"):
        stage = chain[key]
        lines.append(f"| {labels[key]} | **{stage.status}** | {stage.summary} |")
    lines += ["", "### 指标、公式与证据", "", "| 阶段 | 指标 | 结果 | 来源层级 | 公式/字段口径 | 证据 |", "|---|---|---:|---|---|---|"]
    for key in ("coverage", "ranking", "click", "conversion"):
        stage = chain[key]
        for metric_key, metric in stage.metrics.items():
            lines.append(
                f"| {labels[key]} | {labels.get(metric_key, metric_key)} | {_diagnostic_value(metric)} | "
                f"{metric.source_level} | {metric.formula} | {_diagnostic_evidence(metric)} |"
            )
    lines.append("")

    coverage = chain["coverage"]
    ranking = chain["ranking"]
    if coverage.status == "AVAILABLE" and coverage.metrics["competitor_covered_own_missing"].value:
        lines += [
            "最早可确认的缺口出现在**覆盖**：存在竞品已覆盖而自身未覆盖的查询。"
            "下游点击权限或数据缺失时，不能进一步声称主图、价格或 Listing 导致点击问题。", "",
        ]
    elif ranking.status == "AVAILABLE" and ranking.metrics["own_behind_best_competitor"].value:
        lines += [
            "最早可确认的缺口出现在**排名**：自身在部分共同查询上落后最优竞品。"
            "这不自动等于广告、Listing 或价格问题。", "",
        ]


def _append_amazon_summary(lines: list[str], case: CaseConfig, records: list[MetricRecord]) -> None:
    versions = source_artifact_ids(records, "AMAZON_SALES_TRAFFIC")
    latest_artifact, latest_records = select_latest_source_artifact(records, "AMAZON_SALES_TRAFFIC")
    amazon = [record for record in latest_records if record.asin == case.own_asin]
    if not amazon:
        return

    metric_specs = (
        ("units_ordered", "订单件数", "count", 0),
        ("total_order_items", "订单项", "count", 0),
        ("ordered_product_sales", "销售额", None, 2),
        ("sessions", "Sessions", "count", 0),
        ("page_views", "Page Views", "count", 0),
    )
    lines += [
        "### Amazon Sales and Traffic（L1）", "",
        f"保留 {len(versions)} 个 Sales and Traffic 原始版本；计算采用最新采集版本 `{latest_artifact}`。"
        "原始与标准化旧版本不删除、不跨版本相加。", "",
        "以下为同一 child ASIN 各 parent 分组的可加指标合计；百分比未直接相加。", "",
        "| 指标 | Case 周期结果 | 单位 | 证据 |", "|---|---:|---|---|",
    ]
    by_metric: dict[str, list[MetricRecord]] = {}
    for metric, label, default_unit, decimals in metric_specs:
        metric_records = _amazon_records(case, amazon, metric)
        by_metric[metric] = metric_records
        if not metric_records:
            continue
        value = _sum_values(metric_records)
        rendered = f"{value:.{decimals}f}"
        unit = default_unit or metric_records[0].unit
        lines.append(f"| {label} | {rendered} | {unit} | {_evidence_list(metric_records)} |")

    units = by_metric.get("units_ordered", [])
    sessions = by_metric.get("sessions", [])
    session_total = _sum_values(sessions)
    if units and sessions and session_total:
        units_total = _sum_values(units)
        conversion = units_total / session_total * Decimal("100")
        conversion_evidence = [*units, *sessions]
        lines.append(
            f"| Unit Session %（{units_total:.0f} ÷ {session_total:.0f}） | {conversion:.2f}% | derived | "
            f"{_evidence_list(conversion_evidence)} |"
        )
    lines.append("")

    parents = sorted({
        str(record.dimensions.get("parent_asin"))
        for record in amazon if record.dimensions.get("parent_asin")
    })
    if len(parents) > 1:
        parent_evidence: list[MetricRecord] = []
        for parent in parents:
            record = next(record for record in amazon if str(record.dimensions.get("parent_asin")) == parent)
            parent_evidence.append(record)
        lines += [
            f"同一 child ASIN `{case.own_asin}` 在原报表中出现于 {len(parents)} 个 parent 分组："
            f"{', '.join(f'`{parent}`' for parent in parents)}。这说明报告期内存在多种父体归属/分组，"
            f"但仅凭该报表不能断定具体变体变更时间；需核查店铺变体历史。证据：{_evidence_list(parent_evidence)}。",
            "",
        ]


def render_report(
    case: CaseConfig, records: list[MetricRecord], output: str | Path,
    *, source_statuses: dict[str, dict] | None = None,
) -> Path:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    source_statuses = source_statuses or {}
    has_xiyou = any(r.source_name == "XIYOU" for r in records)
    has_amazon = any(r.source_name == "AMAZON_SALES_TRAFFIC" for r in records)
    keyword_records = [r for r in records if r.metric == "xiyou_keyword_traffic_share"]
    latest_sales_artifact, _ = select_latest_source_artifact(records, "AMAZON_SALES_TRAFFIC")
    summary_records = [
        r for r in records
        if r.metric != "xiyou_keyword_traffic_share"
        and r.source_name != "AMAZON_SEARCH_QUERY_PERFORMANCE"
        and (r.source_name != "AMAZON_SALES_TRAFFIC" or r.artifact_id == latest_sales_artifact)
    ]
    selected_keyword_period = _select_keyword_period(case, keyword_records)
    report_keyword_records = [
        record for record in keyword_records
        if (record.period_start, record.period_end) == selected_keyword_period
    ]
    opportunities = _keyword_opportunities(case, report_keyword_records)
    status = (
        "READY_FOR_REVIEW" if has_xiyou and has_amazon
        else "PARTIAL_XIYOU_ONLY" if has_xiyou
        else "PARTIAL_AMAZON_ONLY" if has_amazon
        else "BLOCKED"
    )
    sqp = source_statuses.get("AMAZON_SEARCH_QUERY_PERFORMANCE", {})
    sqp_status = sqp.get(
        "status", "AVAILABLE" if any(r.source_name == "AMAZON_SEARCH_QUERY_PERFORMANCE" for r in records) else "MISSING_DATA"
    )
    chain = build_diagnostic_chain(case, records, source_statuses)
    score_rows = [r for r in records if r.metric == "xiyou_7d_traffic_score"]
    own_score = next((r for r in score_rows if r.asin == case.own_asin and isinstance(r.value, (int, float))), None)
    peer_scores = [r for r in score_rows if r.asin in case.competitors and isinstance(r.value, (int, float))]
    score_gap = None
    score_evidence = []
    if own_score and peer_scores:
        peer_median = statistics.median(r.value for r in peer_scores)
        score_gap = (own_score.value / peer_median - 1) * 100 if peer_median else 0
        score_evidence = [own_score, *peer_scores]

    lines = [
        "# 多 ASIN 竞品分析报告（SOP V5.1）", "",
        "## 1. 基础信息", "",
        f"- Case：`{case.case_id}`；状态：**{status}**；站点：`{case.marketplace}`。",
        f"- 自身 ASIN：`{case.own_asin}`；竞品 ASIN：{', '.join(f'`{v}`' for v in case.competitors) or '未提供'}。",
        f"- 分析周期：`{case.period_start.isoformat()}` 至 `{case.period_end.isoformat()}`；生命周期：**待验证**。",
        f"- 西柚官方导出（L3）：{'已获得' if has_xiyou else '未获得真实西柚官方导出'}。",
        f"- Amazon Sales and Traffic（L1）：{'已获得' if has_amazon else '未获得 Amazon Sales and Traffic'}。",
        f"- Amazon SQP（L1）：**{sqp_status}**；{sqp.get('reason') or '无补充原因'}。",
        "- 证据等级：L1=Amazon 后台/API；L2=前台事实快照；L3=西柚估算；L4=基于证据的推断。", "",
        "## 2. 一句话结论", "",
    ]
    if not has_xiyou:
        lines += ["关键竞品来源未齐，当前不能形成真实竞品结论；仅保留已获得的 Amazon 事实。", ""]
    elif score_gap is not None:
        lines += [
            f"当前最先被证据确认的差距在覆盖/排名层；西柚 L3 的 7 天流量得分相对竞品中位数为 {score_gap:+.1f}%"
            f"（只作相对趋势，不等同 Sessions）。证据：{', '.join(r.evidence_id for r in score_evidence)}。", "",
        ]
    else:
        lines += ["当前最先被证据确认的差距在覆盖/排名层；其后的点击归因仍受 SQP 完整性限制。", ""]

    lines += ["## 3. 宏观诊断", ""]
    if score_gap is not None:
        lines.append(
            f"- 流量规模（L3）：自身 7 天流量得分 `{own_score.value}`，相对竞品中位数 {score_gap:+.1f}%；"
            f"证据：{_evidence_list(score_evidence)}。"
        )
    else:
        lines.append("- 流量规模：缺少可比西柚流量得分，MISSING_DATA。")
    lines += [
        f"- 覆盖：{chain['coverage'].summary}",
        f"- 排名：{chain['ranking'].summary}",
        f"- 点击：{chain['click'].summary}",
        f"- 转化：{chain['conversion'].summary}",
        "- 西柚流量份额不等同 Amazon CTR；西柚点击转化估算不等同自身真实 CVR。", "",
    ]
    sidecar_path = output.with_suffix(".diagnostics.json")
    _append_diagnostic_chain(lines, case, records, source_statuses, sidecar_path)
    _append_amazon_summary(lines, case, records)

    lines += ["## 4. 关键词机会", ""]
    if keyword_records:
        periods = sorted({f"{r.period_start}~{r.period_end}" for r in keyword_records})
        selected_period = "~".join(selected_keyword_period) if selected_keyword_period else "-"
        lines += [
            f"关键词明细可用周期：{', '.join(f'`{value}`' for value in periods)}。", "",
            f"关键词明细采用周期：`{selected_period}`；优先精确匹配 Case 周期，否则选择时长最接近且重叠最多的单一周期。不同周期不混算。", "",
            "S/A 为当前候选优先级：S=相关度≥80 且自身明显缺口，A=其他相关度≥60 的高量差距词；缺少业务词根确认时均需复核。", "",
            "| 关键词 | 翻译/标签 | 周搜索量 | 自身份额 | 最强竞品及份额 | 自身自然位 | 证据 | 级别 |",
            "|---|---|---:|---:|---|---:|---|---|",
        ]
        for own, peer in opportunities:
            dimensions = own.dimensions
            translation = dimensions.get("translation") or "-"
            tag = dimensions.get("keyword_tag") or "-"
            search_volume = dimensions.get("weekly_search_volume")
            rendered_search_volume = f"{search_volume:,.0f}" if isinstance(search_volume, (int, float)) else "-"
            search_locator = (dimensions.get("field_locators") or {}).get("weekly_search_volume") or "-"
            own_rank = dimensions.get("organic_rank") if dimensions.get("organic_rank") is not None else "-"
            tier = "S（待复核）" if (dimensions.get("relevance_score") or 0) >= 80 else "A（待复核）"
            lines.append(
                f"| {dimensions['keyword']} | {translation} / {tag} | {rendered_search_volume} | "
                f"{own.value:.2%} | {peer.asin} / {peer.value:.2%} | {own_rank} | "
                f"`{own.evidence_id}`, `{peer.evidence_id}`；搜索量 `{search_locator}` | {tier} |"
            )
        if not opportunities:
            lines.append("| - | - | - | - | - | - | 当前字段未形成可排序机会项 | - |")
    else:
        lines.append("MISSING_DATA：没有真实西柚关键词明细，不能生成机会词、缺口词、掉位词或优势保护词。")
    lines += ["", "掉位词需要至少两个可比时间快照；当前导出为各周期聚合结果，不能据此推断掉位。", ""]

    lines += ["## 5. 产品差距", "", "MISSING_DATA：未采集竞品功能、规格、材质、配件及差评主题的结构化证据，因此不作产品归因。", ""]
    lines += ["## 6. Listing 差距", "", "MISSING_DATA：当前 Case 未形成竞品主图、标题、五点、图片、视频、A+、QA 的同口径快照，因此不作 Listing 归因。", ""]

    lines += ["## 7. 价格评价", ""]
    price_metrics = [r for r in summary_records if r.metric in {"xiyou_price", "xiyou_review_rating", "xiyou_review_count"}]
    if price_metrics:
        lines += ["以下仅为西柚导出中的 L3 快照，不代表全周期价格、Coupon 或 Deal 历史。", "", "| ASIN | 售价 | Rating | Review | 证据 |", "|---|---:|---:|---:|---|"]
        for asin in case.all_asins:
            asin_rows = [r for r in price_metrics if r.asin == asin]
            def metric_value(name: str):
                row = next((r for r in asin_rows if r.metric == name), None)
                return (row.value if row else "-"), row
            price, price_row = metric_value("xiyou_price")
            rating, rating_row = metric_value("xiyou_review_rating")
            reviews, reviews_row = metric_value("xiyou_review_count")
            evidence_rows = [r for r in (price_row, rating_row, reviews_row) if r]
            lines.append(f"| {asin} | {price} | {rating} | {reviews} | {_evidence_list(evidence_rows) or '-'} |")
    else:
        lines.append("MISSING_DATA：没有同口径价格、Coupon、Rating、Review 数据。")
    lines += ["", "Deal、Coupon、调价和差评主题未获得周期历史，不能判断其对点击或转化的影响。", ""]

    lines += ["## 8. 广告差距", ""]
    ad_metrics = [r for r in summary_records if r.metric in {"xiyou_ad_traffic_score", "xiyou_ad_keyword_count", "xiyou_7d_ad_traffic_score_share"}]
    if ad_metrics:
        lines += ["西柚 L3 仅支持广告覆盖/结构代理；真实曝光、CTR、CVR、CPC、ACOS/TACOS 未接入。", "", "| ASIN | 广告流量得分 | 广告词数 | 7天广告流量占比 | 证据 |", "|---|---:|---:|---:|---|"]
        for asin in case.all_asins:
            asin_rows = [r for r in ad_metrics if r.asin == asin]
            values = {}
            for name in ("xiyou_ad_traffic_score", "xiyou_ad_keyword_count", "xiyou_7d_ad_traffic_score_share"):
                row = next((r for r in asin_rows if r.metric == name), None)
                values[name] = row.value if row else "-"
            lines.append(
                f"| {asin} | {values['xiyou_ad_traffic_score']} | {values['xiyou_ad_keyword_count']} | "
                f"{values['xiyou_7d_ad_traffic_score_share']} | {_evidence_list(asin_rows) or '-'} |"
            )
    else:
        lines.append("MISSING_DATA：没有广告覆盖或绩效数据。")
    lines += ["", "没有 Amazon Ads 报告，不能对广告 CTR/CVR/CPC/ACOS/TACOS 作归因。", ""]

    missing_queries = chain["coverage"].metrics["competitor_covered_own_missing"].value
    behind_queries = chain["ranking"].metrics["own_behind_best_competitor"].value
    lines += ["## 9. 根因", ""]
    if chain["coverage"].status == "AVAILABLE" and missing_queries:
        lines.append(f"- 最早观测断点（低置信度，L3）：西柚估算提示关键词覆盖缺口，竞品覆盖而自身缺失 `{missing_queries}` 个查询；这不是已验证根因，完整 Evidence ID 见诊断 sidecar。")
    elif chain["ranking"].status == "AVAILABLE" and behind_queries:
        lines.append(f"- 最早观测断点（低置信度，L3）：西柚估算提示共同查询排名落后，落后最优竞品 `{behind_queries}` 个查询；这不是已验证根因。")
    else:
        lines.append("- 主要根因：证据不足，尚不能确认。")
    lines += [
        "- 次要可能性（低置信度、待验证）：产品、Listing、价格、促销或广告效率；当前没有相应证据，不作归因。",
        f"- 点击层状态：`{chain['click'].status}`。SQP 空文档/部分空文档不得解释为零曝光或零点击。", "",
        "## 10. 优先级", "",
        "- S：先核实并补齐高相关、高需求、竞品已覆盖而自身缺失的词；商业影响暂不可量化，需 SQP 查询级数据确认。",
        "- A：提升已有覆盖但自然排名落后的核心词，避免把排名问题误判成点击问题。",
        "- B：补采竞品产品/Listing/评价证据后再决定页面改动。",
        "- C：低相关或证据不足的词暂不投入。", "",
        "## 11. 行动方案", "",
        "| 动作 | 负责人 | 风险 | 周期 | 验证 |", "|---|---|---|---|---|",
        "| 复核前 10 个 S/A 候选词的产品相关性与搜索意图，不直接改广告或 Listing | 运营 | 误收低相关词 | 1–2 天 | 形成确认/排除清单并保留 Evidence ID |",
        "| 对确认词核查自身收录、自然位与 SP 覆盖，建立词级基线 | 运营 | 西柚估算偏差 | 7 天 | 覆盖数、Top20 数、落后词数 |",
        "| 补采竞品页面与评价主题后再设计最小 Listing 实验 | 运营+内容 | 同期多变量导致无法归因 | 14 天 | 单变量测试记录 |",
        "| 补齐 SQP/广告报告权限与周期数据 | 数据负责人 | API 延迟或空报告 | 30 天 | 查询级曝光、点击、购买及广告绩效可用性 |", "",
        "## 12. 验证方案", "",
        "- 7 天：确认 S/A 词相关性；复测覆盖数、自然 Top20、共同词落后数。",
        "- 14 天：比较同口径词级排名变化；若有完整 SQP，再比较查询级曝光与 CTR。",
        "- 30 天：比较 Sessions、Units、Unit Session %；若有 Ads 报告，再比较 CPC/ACOS/TACOS。",
        "- 所有周期只做同口径、同站点、同 ASIN 比较；促销/断货/调价/变体事件单独标注。", "",
        "## 13. 待验证项", "",
        "- 产品生命周期、报告期内断货、Deal、Coupon、调价及变体调整历史。",
        "- 竞品产品规格、差评主题、Listing 全模块的同口径快照。",
        f"- SQP 当前状态 `{sqp_status}`：{sqp.get('reason') or '缺少完整查询级数据'}；空报告不得当成零值。",
        "- Amazon Ads 搜索词/投放/广告位报告及 CPC、ACOS/TACOS。",
        "- 稳定 Parent ASIN 与报告期内父子体归属变化。", "",
        "## 14. 复盘结论", "",
        "本报告是受控多 Case 的真实基线，不是改动后的复盘。已能稳定定位覆盖与排名缺口；点击层取决于 SQP 完整返回，产品、Listing、广告归因仍待证据。下一轮重点是用同口径 7/14/30 天数据验证差距是否缩小。", "",
        "## 附录 A：已验证原始分组指标", "", "| ASIN | 指标 | 值 | 单位 | 维度 | 数据周期 | 来源层级 | 证据 |", "|---|---|---:|---|---|---|---|---|",
    ]
    for record in summary_records:
        parent = record.dimensions.get("parent_asin")
        dimension = f"parent={parent}" if parent else "-"
        lines.append(
            f"| {record.asin} | {record.metric} | {_display(record.value)} | {record.unit} | {dimension} | "
            f"{record.period_start}~{record.period_end} | {record.source_level} | `{record.evidence_id}` |"
        )
    if not summary_records:
        lines.append("| - | - | - | - | - | - | - | - |")

    lines += ["", "## 附录 B：Evidence Ledger", "", "| Evidence ID | 原始文件 | 定位器 | 采集时间 |", "|---|---|---|---|"]
    ledger_records = list(summary_records)
    for own, peer in opportunities:
        ledger_records.extend((own, peer))
    ledger_records = list({record.evidence_id: record for record in ledger_records}.values())
    for record in ledger_records:
        lines.append(f"| `{record.evidence_id}` | `{record.raw_path}` | `{record.locator}` | `{record.captured_at}` |")
    if not ledger_records:
        lines.append("| - | - | - | - |")
    lines += ["", f"诊断公式与完整输入 Evidence ID：`{sidecar_path.as_posix()}`。", ""]
    governance = build_governance_bundle(case, records, source_statuses)
    claim = governance["diagnostic_claims"][0]
    action = governance["action_plan"][0]
    lines += [
        "## 附录 C：G0–G7 质量门", "",
        "质量门不以全绿为目标；缺失权限、人工审批或运营事件时保持 REVIEW_REQUIRED/BLOCKED。", "",
        "| 门 | 名称 | 状态 | 问题 |", "|---|---|---|---|",
    ]
    for gate in governance["quality_gates"]:
        lines.append(
            f"| {gate['gate_id']} | {gate['name']} | {gate['status']} | "
            f"{'；'.join(gate['issues']) or '-'} |"
        )
    lines += [
        "", "## 附录 D：结构化决策状态", "",
        f"- 候选根因 `{claim['claim_id']}`：{claim['claim']}；置信度 **{claim['confidence']}**。",
        f"- 行动 `{action['action_id']}`：审批状态 **{action['approval_status']}**；负责人：{action['owner']}。",
        "- D7/D14/D30 复盘计划已经登记，但尚未冻结 baseline，不能写成已执行或有效。", "",
    ]
    output.write_text("\n".join(lines), encoding="utf-8")
    sidecars = {
        ".quality-gates.json": {key: governance[key] for key in ("schema_version", "case_id", "run_id", "ruleset_version", "quality_gates")},
        ".claims.json": {key: governance[key] for key in ("schema_version", "case_id", "run_id", "ruleset_version", "diagnostic_claims")},
        ".action-plan.json": {key: governance[key] for key in ("schema_version", "case_id", "run_id", "ruleset_version", "action_plan")},
        ".review-plan.json": {key: governance[key] for key in ("schema_version", "case_id", "run_id", "ruleset_version", "review_plan")},
    }
    for suffix, payload in sidecars.items():
        output.with_suffix(suffix).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return output
