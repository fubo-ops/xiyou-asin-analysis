from __future__ import annotations

import gzip
import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from .models import CaseConfig


class SpApiError(RuntimeError):
    def __init__(
        self, message: str, *, report_id: str | None = None,
        processing_status: str | None = None,
    ):
        super().__init__(message)
        self.report_id = report_id
        self.processing_status = processing_status


def complete_sqp_weeks(case: CaseConfig) -> list[tuple[date, date]]:
    """Return complete Sunday-Saturday periods fully contained in the case."""
    start = case.period_start + timedelta(days=(6 - case.period_start.weekday()) % 7)
    periods: list[tuple[date, date]] = []
    while start + timedelta(days=6) <= case.period_end:
        periods.append((start, start + timedelta(days=6)))
        start += timedelta(days=7)
    return periods


class SalesTrafficClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        marketplace_id: str,
        *,
        endpoint: str = "https://sellingpartnerapi-na.amazon.com",
        session=None,
        sleep: Callable[[float], None] = time.sleep,
        poll_interval: float = 10,
        max_polls: int = 60,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.marketplace_id = marketplace_id
        self.endpoint = endpoint.rstrip("/")
        if session is None:
            import requests

            session = requests.Session()
        self.session = session
        self.sleep = sleep
        self.poll_interval = poll_interval
        self.max_polls = max_polls
        self.last_report_id: str | None = None

    def fetch_payload(self, case: CaseConfig) -> dict:
        report_request = {
            "reportType": "GET_SALES_AND_TRAFFIC_REPORT",
            "dataStartTime": f"{case.period_start.isoformat()}T00:00:00Z",
            "dataEndTime": f"{case.period_end.isoformat()}T23:59:59Z",
            "marketplaceIds": [self.marketplace_id],
            "reportOptions": {"dateGranularity": "DAY", "asinGranularity": "CHILD"},
        }
        return self._fetch_report(report_request, "Sales and Traffic")

    def fetch_search_query_performance(
        self, case: CaseConfig, period_start: date, period_end: date,
        *, on_created: Callable[[str], None] | None = None,
    ) -> dict:
        if period_start.weekday() != 6 or period_end != period_start + timedelta(days=6):
            raise ValueError("SQP WEEK 必须是完整的周日至周六")
        if period_start < case.period_start or period_end > case.period_end:
            raise ValueError("SQP 周期必须完全位于 Case 周期内")
        report_request = {
            "reportType": "GET_BRAND_ANALYTICS_SEARCH_QUERY_PERFORMANCE_REPORT",
            "dataStartTime": f"{period_start.isoformat()}T00:00:00Z",
            "dataEndTime": f"{period_end.isoformat()}T23:59:59Z",
            "marketplaceIds": [self.marketplace_id],
            "reportOptions": {"asin": case.own_asin, "reportPeriod": "WEEK"},
        }
        return self._fetch_report(report_request, "Search Query Performance", on_created=on_created)

    def _fetch_report(
        self, report_request: dict, report_label: str,
        *, on_created: Callable[[str], None] | None = None,
    ) -> dict:
        access_token = self._access_token()
        headers = self._headers(access_token)
        created = self._request("post",
            f"{self.endpoint}/reports/2021-06-30/reports", json=report_request, headers=headers, timeout=30
        )
        self._raise(created, f"创建 {report_label} 报告失败")
        report_id = created.json()["reportId"]
        self.last_report_id = report_id
        if on_created:
            on_created(report_id)
        return self.fetch_report_by_id(report_id, report_label=report_label, headers=headers)

    def fetch_report_by_id(
        self, report_id: str, *, report_label: str = "Amazon", headers: dict[str, str] | None = None
    ) -> dict:
        headers = headers or self._headers(self._access_token())
        document_id = self._wait_for_document(report_id, headers)
        document = self._request("get",
            f"{self.endpoint}/reports/2021-06-30/documents/{document_id}", headers=headers, timeout=30
        )
        self._raise(document, "获取报告下载地址失败")
        document_info = document.json()
        downloaded = self._request("get", document_info["url"], timeout=60)
        self._raise(downloaded, f"下载 {report_label} 报告失败")
        content = downloaded.content
        if document_info.get("compressionAlgorithm") == "GZIP" and content[:2] == b"\x1f\x8b":
            content = gzip.decompress(content)
        return json.loads(content.decode("utf-8-sig"))

    def _access_token(self) -> str:
        response = self._request("post",
            "https://api.amazon.com/auth/o2/token",
            data={
                "grant_type": "refresh_token", "refresh_token": self.refresh_token,
                "client_id": self.client_id, "client_secret": self.client_secret,
            },
            timeout=30,
        )
        self._raise(response, "Amazon LWA 授权失败")
        return response.json()["access_token"]

    def _wait_for_document(self, report_id: str, headers: dict[str, str]) -> str:
        for _ in range(self.max_polls):
            response = self._request("get",
                f"{self.endpoint}/reports/2021-06-30/reports/{report_id}", headers=headers, timeout=30
            )
            self._raise(response, "查询报告状态失败")
            state = response.json()
            status = state["processingStatus"]
            if status == "DONE":
                return state["reportDocumentId"]
            if status in {"CANCELLED", "FATAL"}:
                raise SpApiError(
                    f"Amazon 报告处理状态为 {status}",
                    report_id=report_id, processing_status=status,
                )
            self.sleep(self.poll_interval)
        raise SpApiError(
            "Amazon 报告在轮询上限内未完成",
            report_id=report_id, processing_status=status,
        )

    def _request(self, method: str, url: str, **kwargs):
        response = None
        for attempt in range(3):
            response = getattr(self.session, method)(url, **kwargs)
            if response.status_code != 429:
                return response
            if attempt < 2:
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after is not None else float(2**attempt)
                except ValueError:
                    delay = float(2**attempt)
                self.sleep(delay)
        return response

    @staticmethod
    def _headers(access_token: str) -> dict[str, str]:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return {
            "x-amz-access-token": access_token,
            "x-amz-date": timestamp,
            "user-agent": "xiyou-asin-analysis/0.1",
            "content-type": "application/json",
        }

    @staticmethod
    def _raise(response, message: str) -> None:
        if response.status_code >= 400:
            if response.status_code in {401, 403}:
                raise SpApiError(f"{message}：需要检查 API 授权或角色权限（HTTP {response.status_code}）")
            raise SpApiError(f"{message}（HTTP {response.status_code}）")
