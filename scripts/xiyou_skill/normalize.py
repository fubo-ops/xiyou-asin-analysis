from __future__ import annotations

import hashlib
from typing import Any

from .models import CaseConfig, MetricRecord, RawArtifact


def evidence_id(artifact_id: str, asin: str, metric: str, locator: str) -> str:
    value = f"{artifact_id}|{asin}|{metric}|{locator}".encode("utf-8")
    return "EV-" + hashlib.sha256(value).hexdigest()[:16]


def make_record(
    artifact: RawArtifact,
    case: CaseConfig,
    *,
    asin: str,
    metric: str,
    value: Any,
    unit: str,
    locator: str,
    dimensions: dict[str, Any] | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
) -> MetricRecord:
    return MetricRecord(
        evidence_id=evidence_id(artifact.artifact_id, asin, metric, locator),
        artifact_id=artifact.artifact_id,
        source_name=artifact.source_name,
        source_level=artifact.source_level,
        marketplace=case.marketplace,
        asin=asin,
        period_start=period_start or case.period_start.isoformat(),
        period_end=period_end or case.period_end.isoformat(),
        metric=metric,
        value=value,
        unit=unit,
        locator=locator,
        raw_path=artifact.path.as_posix(),
        captured_at=artifact.captured_at,
        dimensions=dimensions or {},
        case_id=case.case_id,
        run_id=case.run_id,
    )


def normalize_amazon(payload: dict, artifact: RawArtifact, case: CaseConfig) -> list[MetricRecord]:
    records: list[MetricRecord] = []
    rows = payload.get("salesAndTrafficByAsin", [])
    field_map = {
        ("salesByAsin", "unitsOrdered"): ("units_ordered", "count"),
        ("salesByAsin", "totalOrderItems"): ("total_order_items", "count"),
        ("trafficByAsin", "sessions"): ("sessions", "count"),
        ("trafficByAsin", "pageViews"): ("page_views", "count"),
        ("trafficByAsin", "sessionPercentage"): ("session_percentage", "percent"),
        ("trafficByAsin", "pageViewsPercentage"): ("page_views_percentage", "percent"),
        ("trafficByAsin", "buyBoxPercentage"): ("buy_box_percentage", "percent"),
        ("trafficByAsin", "unitSessionPercentage"): ("unit_session_percentage", "percent"),
    }
    for index, row in enumerate(rows):
        asin = row.get("childAsin") or row.get("parentAsin")
        if asin != case.own_asin:
            continue
        dimensions = {
            "parent_asin": row.get("parentAsin"),
            "child_asin": row.get("childAsin"),
            "component_index": index,
        }
        for (section, field), (metric, unit) in field_map.items():
            if field in row.get(section, {}):
                locator = f"/salesAndTrafficByAsin/{index}/{section}/{field}"
                records.append(make_record(
                    artifact, case, asin=asin, metric=metric, value=row[section][field],
                    unit=unit, locator=locator, dimensions=dimensions,
                ))
        sales = row.get("salesByAsin", {}).get("orderedProductSales")
        if isinstance(sales, dict) and "amount" in sales:
            locator = f"/salesAndTrafficByAsin/{index}/salesByAsin/orderedProductSales/amount"
            records.append(make_record(
                artifact, case, asin=asin, metric="ordered_product_sales", value=sales["amount"],
                unit=sales.get("currencyCode", "currency"), locator=locator, dimensions=dimensions,
            ))
    return records


def normalize_search_query_performance(
    payload: dict, artifact: RawArtifact, case: CaseConfig
) -> list[MetricRecord]:
    records: list[MetricRecord] = []
    field_map = {
        ("searchQueryVolume",): ("sqp_query_volume", "count"),
        ("impressionData", "asinImpressionCount"): ("sqp_impressions", "count"),
        ("impressionData", "asinImpressionShare"): ("sqp_impression_share", "percent"),
        ("clickData", "asinClickCount"): ("sqp_clicks", "count"),
        ("clickData", "asinClickShare"): ("sqp_click_share", "percent"),
        ("cartAddData", "asinCartAddCount"): ("sqp_cart_adds", "count"),
        ("cartAddData", "asinCartAddShare"): ("sqp_cart_add_share", "percent"),
        ("purchaseData", "asinPurchaseCount"): ("sqp_purchases", "count"),
        ("purchaseData", "asinPurchaseShare"): ("sqp_purchase_share", "percent"),
    }
    for asin_index, asin_row in enumerate(payload.get("dataByAsin", [])):
        asin = asin_row.get("asin")
        if asin != case.own_asin:
            continue
        period_start = str(asin_row.get("startDate") or case.period_start.isoformat())
        period_end = str(asin_row.get("endDate") or case.period_end.isoformat())
        query_data = asin_row.get("searchQueryData", [])
        if isinstance(query_data, dict):
            query_rows = [({**asin_row, **query_data}, "")]
        else:
            query_rows = [(query_row, f"/searchQueryData/{query_index}") for query_index, query_row in enumerate(query_data)]
        for query_index, (query_row, query_prefix) in enumerate(query_rows):
            dimensions = {
                "search_query": query_row.get("searchQuery"),
                "search_query_score": query_row.get("searchQueryScore"),
                "asin_index": asin_index,
                "query_index": query_index,
            }
            for path, (metric, unit) in field_map.items():
                value: Any = query_row
                for part in path:
                    if not isinstance(value, dict) or part not in value:
                        value = None
                        break
                    value = value[part]
                if value is None:
                    continue
                pointer = "/".join(path)
                locator = f"/dataByAsin/{asin_index}{query_prefix}/{pointer}"
                records.append(make_record(
                    artifact, case, asin=asin, metric=metric, value=value, unit=unit,
                    locator=locator, dimensions=dimensions,
                    period_start=period_start, period_end=period_end,
                ))
    return records

