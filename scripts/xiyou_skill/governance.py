from __future__ import annotations

from typing import Any

from .diagnostics import build_diagnostic_chain
from .models import CaseConfig, MetricRecord


def _gate(gate_id: str, name: str, status: str, issues: list[str]) -> dict[str, Any]:
    return {"gate_id": gate_id, "name": name, "status": status, "issues": issues}


def _claim(case: CaseConfig, chain: dict, records: list[MetricRecord]) -> dict[str, Any]:
    coverage = chain["coverage"]
    ranking = chain["ranking"]
    missing = coverage.metrics["competitor_covered_own_missing"]
    behind = ranking.metrics["own_behind_best_competitor"]
    if coverage.status == "AVAILABLE" and missing.value:
        stage = "coverage"
        summary = f"竞品已覆盖而自身缺失 {missing.value} 个查询，是当前最早可确认的诊断断点。"
        evidence_ids = list(missing.evidence_ids)
        falsification = "补齐经人工确认的高相关词后，连续 14 天同口径覆盖数仍未改善。"
    elif ranking.status == "AVAILABLE" and behind.value:
        stage = "ranking"
        summary = f"自身在 {behind.value} 个共同查询上落后最优竞品，是当前最早可确认的诊断断点。"
        evidence_ids = list(behind.evidence_ids)
        falsification = "保持其他主要变量不变后，连续 14 天共同词排名差距仍未改善。"
    else:
        stage = "unknown"
        summary = "现有证据不足以确认主要诊断断点。"
        evidence_ids = []
        falsification = "补齐缺失数据后仍不能定位覆盖、排名、点击或转化的首个异常环节。"
    levels = {record.source_level for record in records if record.evidence_id in evidence_ids}
    confidence = "MEDIUM" if "L1" in levels and len(levels) > 1 else "LOW"
    return {
        "claim_id": f"CL-{case.run_id}-01",
        "claim_type": "CANDIDATE_ROOT_CAUSE",
        "stage": stage,
        "claim": summary,
        "evidence_ids": evidence_ids,
        "alternative_causes": ["生命周期积累不足", "库存、促销、价格或变体事件污染了比较窗口"],
        "missing_evidence": ["人工确认的竞品 A/B/C 分层", "完整 SQP 与 Amazon Ads 查询级数据", "报告期运营事件历史"],
        "falsification_condition": falsification,
        "confidence": confidence,
    }


def _action(case: CaseConfig, claim: dict[str, Any]) -> dict[str, Any]:
    return {
        "action_id": f"AC-{case.run_id}-01",
        "claim_id": claim["claim_id"],
        "change_scope": "人工复核前 10 个高相关覆盖/排名候选词，并建立同口径词级基线；本产物不自动修改广告或 Listing。",
        "owner": "运营（待指派）",
        "approval_status": "PENDING_HUMAN_REVIEW",
        "risk": "错误纳入低相关词，或同期多变量变化导致无法归因",
        "period_days": 14,
        "primary_metric": "confirmed_high_relevance_coverage_count",
        "guardrail_metrics": ["unit_session_percentage", "acos_if_available", "inventory_status"],
        "stop_condition": "相关曝光或覆盖改善但连续 14 天无有效点击，或护栏指标明显恶化。",
        "evidence_ids": claim["evidence_ids"],
    }


def _review_plan(case: CaseConfig, action: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = {
        7: ["confirmed_high_relevance_coverage_count", "organic_top20_count"],
        14: ["organic_top20_count", "sqp_impressions_if_available", "sqp_ctr_if_available"],
        30: ["sessions", "units_ordered", "unit_session_percentage", "acos_if_available"],
    }
    return [{
        "review_id": f"RV-{case.run_id}-{day}",
        "action_id": action["action_id"],
        "day": day,
        "status": "NOT_STARTED",
        "baseline_status": "PENDING_ACTION_APPROVAL",
        "metrics": metrics[day],
        "comparison_rule": "同站点、同 ASIN、同口径；断货/促销/调价/变体事件必须单独标注。",
    } for day in (7, 14, 30)]


def build_governance_bundle(
    case: CaseConfig,
    records: list[MetricRecord],
    source_statuses: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    source_statuses = source_statuses or {}
    chain = build_diagnostic_chain(case, records, source_statuses)
    claim = _claim(case, chain, records)
    action = _action(case, claim)
    review_plan = _review_plan(case, action)
    evidence_ids = [record.evidence_id for record in records]
    unique_evidence = len(evidence_ids) == len(set(evidence_ids))
    traceable = all(record.raw_path and record.locator and record.captured_at for record in records)
    source_levels_valid = all(
        (record.source_name.startswith("AMAZON") and record.source_level == "L1")
        or (record.source_name == "XIYOU" and record.source_level == "L3")
        or record.source_name not in {"XIYOU", "AMAZON_SALES_TRAFFIC", "AMAZON_SEARCH_QUERY_PERFORMANCE"}
        for record in records
    )
    g0_issues = []
    synthetic_case = all(asin.startswith("B0SYNTH") for asin in case.all_asins)
    if not synthetic_case and not 4 <= len(case.competitors) <= 8:
        g0_issues.append("真实 Case 必须包含 4–8 个竞品")
    if not case.objective.strip() or case.objective.strip() == "综合诊断":
        g0_issues.append("缺少具体、可验证的业务问题")
    if not any(record.source_name == "XIYOU" for record in records):
        g0_issues.append("缺少西柚真实数据")
    if not any(record.source_name == "AMAZON_SALES_TRAFFIC" for record in records):
        g0_issues.append("缺少 Amazon Sales and Traffic")
    g1_issues = [] if case.competitor_review_status == "APPROVED" else ["竞品池尚未完成人工 A/B/C 分层审批"]
    g3_issues = []
    if case.event_history_status != "CONFIRMED":
        g3_issues.append("报告期断货、促销、调价和变体事件历史未确认")
    if not any(record.source_name == "AMAZON_ADS" for record in records):
        g3_issues.append("Amazon Ads 真实报告缺失，广告点击与成本结论受限")
    claim_complete = all(claim.get(key) for key in (
        "alternative_causes", "missing_evidence", "falsification_condition", "confidence"
    )) and set(claim["evidence_ids"]).issubset(set(evidence_ids))
    quality_gates = [
        _gate("G0", "范围与输入完整性", "PASS" if not g0_issues else "BLOCKED", g0_issues),
        _gate("G1", "竞品可比性", "PASS" if not g1_issues else "REVIEW_REQUIRED", g1_issues),
        _gate("G2", "来源真实性", "PASS" if source_levels_valid else "BLOCKED", [] if source_levels_valid else ["来源层级映射不一致"]),
        _gate("G3", "样本与异常", "PASS" if not g3_issues else "REVIEW_REQUIRED", g3_issues),
        _gate("G4", "根因完整性与因果语言", "PASS" if claim_complete else "BLOCKED", [] if claim_complete else ["根因对象缺少证据、备选原因或反证条件"]),
        _gate("G5", "动作可验收", "REVIEW_REQUIRED", ["行动仍待人工审批和负责人确认"]),
        _gate("G6", "数值可追溯", "PASS" if unique_evidence and traceable else "BLOCKED", [] if unique_evidence and traceable else ["Evidence ID 重复或原始定位信息缺失"]),
        _gate("G7", "复盘口径一致", "REVIEW_REQUIRED", ["尚未审批动作并冻结 baseline，D7/D14/D30 仅为计划"]),
    ]
    return {
        "schema_version": "governance-bundle-v1",
        "case_id": case.case_id,
        "run_id": case.run_id,
        "ruleset_version": case.ruleset_version,
        "quality_gates": quality_gates,
        "diagnostic_claims": [claim],
        "action_plan": [action],
        "review_plan": review_plan,
    }
