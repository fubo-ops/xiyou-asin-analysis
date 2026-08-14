from datetime import date

import pytest

from xiyou_skill.amazon_spapi import SalesTrafficClient, SpApiError, complete_sqp_weeks
from xiyou_skill.models import CaseConfig, RawArtifact
from xiyou_skill.normalize import normalize_amazon, normalize_search_query_performance


class Response:
    def __init__(self, payload, status_code=200, content=b"", headers=None):
        self.payload = payload
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self.text = str(payload)

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.text)


class Session:
    def __init__(self):
        self.calls = []
        self.get_count = 0

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        if "auth/o2/token" in url:
            return Response({"access_token": "short-lived"})
        return Response({"reportId": "R1"})

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if url.endswith("/reports/R1"):
            return Response({"processingStatus": "DONE", "reportDocumentId": "D1"})
        if url.endswith("/documents/D1"):
            return Response({"url": "https://download.example/report"})
        return Response({}, content=b'{"salesAndTrafficByAsin": []}')


class ThrottleOnceSession(Session):
    def __init__(self):
        super().__init__()
        self.throttled = False

    def post(self, url, **kwargs):
        if url.endswith("/reports") and not self.throttled:
            self.throttled = True
            self.calls.append(("POST", url, kwargs))
            return Response({}, status_code=429, headers={"Retry-After": "2"})
        return super().post(url, **kwargs)


class NeverDoneSession(Session):
    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if url.endswith("/reports/R1"):
            return Response({"processingStatus": "IN_PROGRESS"})
        return super().get(url, **kwargs)


def case():
    return CaseConfig("case-1", "US", "B0SYNTH001", ("B0SYNTH002",), date(2026, 7, 12), date(2026, 8, 10))


def test_client_requests_child_granularity_without_logging_credentials():
    session = Session()
    client = SalesTrafficClient("client", "secret", "refresh", "ATVPDKIKX0DER", session=session, sleep=lambda _: None)

    payload = client.fetch_payload(case())

    create = next(call for call in session.calls if call[0] == "POST" and call[1].endswith("/reports"))
    assert create[2]["json"]["reportType"] == "GET_SALES_AND_TRAFFIC_REPORT"
    assert create[2]["json"]["reportOptions"] == {"dateGranularity": "DAY", "asinGranularity": "CHILD"}
    assert payload == {"salesAndTrafficByAsin": []}


def test_client_retries_429_using_retry_after():
    session = ThrottleOnceSession()
    sleeps = []
    client = SalesTrafficClient(
        "client", "secret", "refresh", "ATVPDKIKX0DER", session=session, sleep=sleeps.append
    )

    client.fetch_payload(case())

    assert sleeps == [2.0]
    assert len([call for call in session.calls if call[1].endswith("/reports")]) == 2


def test_complete_sqp_weeks_excludes_partial_week():
    assert complete_sqp_weeks(case()) == [
        (date(2026, 7, 12), date(2026, 7, 18)),
        (date(2026, 7, 19), date(2026, 7, 25)),
        (date(2026, 7, 26), date(2026, 8, 1)),
        (date(2026, 8, 2), date(2026, 8, 8)),
    ]


def test_client_requests_sqp_with_asin_and_week_options():
    session = Session()
    session.download_payload = {
        "dataByAsin": [{"startDate": "2026-07-12", "endDate": "2026-07-18", "asin": "B0SYNTH001"}]
    }
    client = SalesTrafficClient("client", "secret", "refresh", "ATVPDKIKX0DER", session=session, sleep=lambda _: None)

    client.fetch_search_query_performance(case(), date(2026, 7, 12), date(2026, 7, 18))

    create = next(call for call in session.calls if call[0] == "POST" and call[1].endswith("/reports"))
    request = create[2]["json"]
    assert request["reportType"] == "GET_BRAND_ANALYTICS_SEARCH_QUERY_PERFORMANCE_REPORT"
    assert request["reportOptions"] == {"asin": "B0SYNTH001", "reportPeriod": "WEEK"}
    assert request["dataStartTime"] == "2026-07-12T00:00:00Z"
    assert request["dataEndTime"] == "2026-07-18T23:59:59Z"


def test_poll_timeout_preserves_report_id_and_last_remote_status():
    client = SalesTrafficClient(
        "client", "secret", "refresh", "ATVPDKIKX0DER",
        session=NeverDoneSession(), sleep=lambda _: None, max_polls=1,
    )

    with pytest.raises(SpApiError) as caught:
        client.fetch_search_query_performance(case(), date(2026, 7, 12), date(2026, 7, 18))

    assert caught.value.report_id == "R1"
    assert caught.value.processing_status == "IN_PROGRESS"


def test_normalize_amazon_filters_own_asin_and_keeps_json_pointer_lineage(tmp_path):
    artifact = RawArtifact("A1", "AMAZON_SALES_TRAFFIC", "L1", tmp_path / "raw.json", tmp_path / "raw.metadata.json", "abc", "2026-08-11T00:00:00Z")
    payload = {"salesAndTrafficByAsin": [
        {"childAsin": "B0SYNTH001", "salesByAsin": {"unitsOrdered": 7, "orderedProductSales": {"amount": 123.45, "currencyCode": "USD"}}, "trafficByAsin": {"sessions": 99, "unitSessionPercentage": 7.07}},
        {"childAsin": "B0SYNTH006", "salesByAsin": {"unitsOrdered": 50}, "trafficByAsin": {"sessions": 500}},
    ]}

    records = normalize_amazon(payload, artifact, case())

    assert {r.metric for r in records} >= {"units_ordered", "ordered_product_sales", "sessions", "unit_session_percentage"}
    assert {r.asin for r in records} == {"B0SYNTH001"}
    sessions = next(r for r in records if r.metric == "sessions")
    assert sessions.locator == "/salesAndTrafficByAsin/0/trafficByAsin/sessions"
    assert sessions.source_level == "L1"


def test_normalize_amazon_preserves_parent_group_for_duplicate_child_rows(tmp_path):
    artifact = RawArtifact("A1", "AMAZON_SALES_TRAFFIC", "L1", tmp_path / "raw.json", tmp_path / "raw.metadata.json", "abc", "2026-08-11T00:00:00Z")
    payload = {"salesAndTrafficByAsin": [
        {"parentAsin": "B0SYNTH001", "childAsin": "B0SYNTH001", "trafficByAsin": {"sessions": 50}},
        {"parentAsin": "B0SYNTH003", "childAsin": "B0SYNTH001", "trafficByAsin": {"sessions": 24}},
    ]}

    records = normalize_amazon(payload, artifact, case())

    sessions = [record for record in records if record.metric == "sessions"]
    assert {record.dimensions["parent_asin"] for record in sessions} == {"B0SYNTH001", "B0SYNTH003"}
    assert {record.dimensions["child_asin"] for record in sessions} == {"B0SYNTH001"}
    assert {record.dimensions["component_index"] for record in sessions} == {0, 1}


def test_normalize_sqp_maps_query_funnel_and_lineage(tmp_path):
    artifact = RawArtifact(
        "SQP1", "AMAZON_SEARCH_QUERY_PERFORMANCE", "L1", tmp_path / "sqp.json",
        tmp_path / "sqp.metadata.json", "abc", "2026-08-11T00:00:00Z",
    )
    payload = {"dataByAsin": [{
        "startDate": "2026-07-12", "endDate": "2026-07-18", "asin": "B0SYNTH001",
        "searchQueryData": [{
            "searchQuery": "dog wipes", "searchQueryScore": 1, "searchQueryVolume": 1000,
            "impressionData": {"asinImpressionCount": 120, "asinImpressionShare": 0.12},
            "clickData": {"asinClickCount": 24, "asinClickShare": 0.08},
            "purchaseData": {"asinPurchaseCount": 6, "asinPurchaseShare": 0.05},
        }],
    }]}

    records = normalize_search_query_performance(payload, artifact, case())

    assert {record.metric for record in records} >= {"sqp_impressions", "sqp_clicks", "sqp_purchases"}
    clicks = next(record for record in records if record.metric == "sqp_clicks")
    assert clicks.value == 24
    assert clicks.period_start == "2026-07-12"
    assert clicks.period_end == "2026-07-18"
    assert clicks.dimensions["search_query"] == "dog wipes"
    assert clicks.locator == "/dataByAsin/0/searchQueryData/0/clickData/asinClickCount"


def test_normalize_sqp_maps_flat_query_rows_returned_by_amazon(tmp_path):
    artifact = RawArtifact(
        "SQP2", "AMAZON_SEARCH_QUERY_PERFORMANCE", "L1", tmp_path / "sqp-flat.json",
        tmp_path / "sqp-flat.metadata.json", "def", "2026-08-12T00:00:00Z",
    )
    payload = {"dataByAsin": [{
        "startDate": "2026-07-26", "endDate": "2026-08-01", "asin": "B0SYNTH001",
        "searchQueryData": {
            "searchQuery": "idesea", "searchQueryScore": 1, "searchQueryVolume": 15,
        },
        "impressionData": {"asinImpressionCount": 13, "asinImpressionShare": 13.54},
        "clickData": {"asinClickCount": 1, "asinClickShare": 16.67},
        "cartAddData": {"asinCartAddCount": 1, "asinCartAddShare": 100.0},
        "purchaseData": {"asinPurchaseCount": 1, "asinPurchaseShare": 100.0},
    }]}

    records = normalize_search_query_performance(payload, artifact, case())

    assert {record.metric for record in records} == {
        "sqp_query_volume", "sqp_impressions", "sqp_impression_share", "sqp_clicks",
        "sqp_click_share", "sqp_cart_adds", "sqp_cart_add_share", "sqp_purchases",
        "sqp_purchase_share",
    }
    clicks = next(record for record in records if record.metric == "sqp_clicks")
    assert clicks.value == 1
    assert clicks.dimensions["search_query"] == "idesea"
    assert clicks.locator == "/dataByAsin/0/clickData/asinClickCount"
