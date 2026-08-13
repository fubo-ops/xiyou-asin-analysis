from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from .amazon_spapi import SalesTrafficClient, SpApiError, complete_sqp_weeks
from .models import MetricRecord, load_case
from .normalize import normalize_amazon, normalize_search_query_performance
from .raw_store import RawStore
from .report import render_report
from .xiyou import normalize_xiyou_xlsx


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _records_path(data_dir: Path, case=None) -> Path:
    if case is None or case.run_id == case.case_id:
        return data_dir / "normalized" / "metrics.jsonl"
    return data_dir / "runs" / case.case_id / case.run_id / "normalized" / "metrics.jsonl"


def _read_records(path: Path) -> list[MetricRecord]:
    if not path.exists():
        return []
    return [MetricRecord.from_dict(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _append_records(path: Path, records: list[MetricRecord]) -> None:
    existing = {record.evidence_id: record for record in _read_records(path)}
    existing.update({record.evidence_id: record for record in records})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r.to_dict(), ensure_ascii=False) + "\n" for r in existing.values()), encoding="utf-8"
    )


def _source_statuses(data_dir: Path, case=None) -> dict[str, dict]:
    statuses: dict[str, dict] = {}
    status_dir = (
        data_dir / "runs" / case.case_id / case.run_id / "status"
        if case is not None and case.run_id != case.case_id
        else data_dir / "status"
    )
    if not status_dir.exists():
        return statuses
    for path in status_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("source_name"):
            statuses[str(payload["source_name"])] = payload
    return statuses


def _write_source_status(data_dir: Path, filename: str, payload: dict) -> Path:
    status_dir = data_dir / "status"
    status_dir.mkdir(parents=True, exist_ok=True)
    path = status_dir / filename
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _amazon_client() -> SalesTrafficClient:
    return SalesTrafficClient(
        os.environ["SP_API_LWA_CLIENT_ID"], os.environ["SP_API_LWA_CLIENT_SECRET"],
        os.environ["SP_API_REFRESH_TOKEN"], os.environ["SP_API_MARKETPLACE_ID"],
        endpoint=os.getenv("SP_API_ENDPOINT", "https://sellingpartnerapi-na.amazon.com"),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="可追溯的多 ASIN 竞品分析 MVP")
    parser.add_argument("--case", default="case.json")
    parser.add_argument("--data-dir", default="data")
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest-xiyou", help="登记并清洗西柚官方 xlsx 导出")
    ingest.add_argument("--file", required=True)
    ingest.add_argument("--source-period-start")
    ingest.add_argument("--source-period-end")
    ingest.add_argument("--period-basis", default="workbook_or_filename")
    ingest.add_argument("--archive-only", action="store_true")
    ingest_amazon = sub.add_parser("ingest-amazon", help="登记并清洗已有的 Amazon Sales and Traffic JSON")
    ingest_amazon.add_argument("--file", required=True)
    sub.add_parser("fetch-amazon", help="通过 SP-API 获取 Sales and Traffic")
    sub.add_parser("fetch-sqp", help="通过 SP-API 获取 Search Query Performance 完整周报告")
    resume = sub.add_parser("resume-sqp", help="只按现有 reportId 恢复 SQP 轮询，不创建新报告")
    resume.add_argument("--report-id", required=True)
    resume.add_argument("--period-start", required=True)
    resume.add_argument("--period-end", required=True)
    report = sub.add_parser("build-report", help="从已清洗记录生成 Markdown 报告")
    report.add_argument("--output", default="reports/analysis.md")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    case = load_case(args.case)
    data_dir = Path(args.data_dir)
    store = RawStore(data_dir)
    metrics_path = _records_path(data_dir, case)
    legacy_metrics_path = _records_path(data_dir)

    if args.command == "ingest-xiyou":
        if bool(args.source_period_start) != bool(args.source_period_end):
            print("source period 必须同时提供 start 和 end", file=sys.stderr)
            return 2
        source_period = None
        source_period_metadata = None
        if args.source_period_start:
            source_period = (date.fromisoformat(args.source_period_start), date.fromisoformat(args.source_period_end))
            source_period_metadata = {
                "start": args.source_period_start,
                "end": args.source_period_end,
                "basis": args.period_basis,
            }
        artifact = store.register(
            args.file, source_name="XIYOU", source_level="L3", case=case, asins=case.all_asins,
            source_period=source_period_metadata,
        )
        if args.archive_only:
            print(json.dumps({"artifact_id": artifact.artifact_id, "records": 0, "warnings": [], "archive_only": True}, ensure_ascii=False))
            return 0
        records, warnings = normalize_xiyou_xlsx(
            artifact.path, artifact, case, source_period=source_period, period_basis=args.period_basis
        )
        _append_records(metrics_path, records)
        print(json.dumps({"artifact_id": artifact.artifact_id, "records": len(records), "warnings": warnings}, ensure_ascii=False))
        return 0

    if args.command == "ingest-amazon":
        source_path = Path(args.file)
        payload = json.loads(source_path.read_text(encoding="utf-8-sig"))
        artifact = store.register(
            source_path, source_name="AMAZON_SALES_TRAFFIC", source_level="L1",
            case=case, asins=(case.own_asin,),
            source_period={
                "start": case.period_start.isoformat(), "end": case.period_end.isoformat(),
                "basis": "SP_API_REPORT_SPECIFICATION",
            },
        )
        normalized = normalize_amazon(payload, artifact, case)
        _append_records(metrics_path, normalized)
        print(json.dumps({"artifact_id": artifact.artifact_id, "records": len(normalized)}, ensure_ascii=False))
        return 0

    if args.command in {"fetch-amazon", "fetch-sqp", "resume-sqp"}:
        _load_env(Path(".env"))
        required = ["SP_API_LWA_CLIENT_ID", "SP_API_LWA_CLIENT_SECRET", "SP_API_REFRESH_TOKEN", "SP_API_MARKETPLACE_ID"]
        missing = [name for name in required if not os.getenv(name)]
        if missing:
            print("缺少 Amazon SP-API 本地凭据变量：" + ", ".join(missing), file=sys.stderr)
            return 2
        client = _amazon_client()

    if args.command == "fetch-amazon":
        try:
            payload = client.fetch_payload(case)
        except SpApiError as exc:
            print(str(exc), file=sys.stderr)
            return 3
        inbox = data_dir / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        downloaded = inbox / f"amazon-sales-traffic-{case.case_id}.json"
        downloaded.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        artifact = store.register(
            downloaded, source_name="AMAZON_SALES_TRAFFIC", source_level="L1", case=case, asins=(case.own_asin,)
        )
        _append_records(metrics_path, normalize_amazon(payload, artifact, case))
        print(json.dumps({"artifact_id": artifact.artifact_id}, ensure_ascii=False))
        return 0

    if args.command == "resume-sqp":
        period_start = date.fromisoformat(args.period_start)
        period_end = date.fromisoformat(args.period_end)
        if period_start < case.period_start or period_end > case.period_end or (period_end - period_start).days != 6:
            print("恢复的 SQP 周期必须是 Case 内完整的 7 天", file=sys.stderr)
            return 2
        resumed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        previous = _source_statuses(data_dir).get("AMAZON_SEARCH_QUERY_PERFORMANCE", {})
        requested_periods = list(previous.get("requested_periods", []))
        requested = {
            "start": period_start.isoformat(), "end": period_end.isoformat(),
            "report_id": args.report_id,
        }
        requested_periods = [
            item for item in requested_periods
            if (item.get("start"), item.get("end")) != (requested["start"], requested["end"])
        ]
        try:
            payload = client.fetch_report_by_id(args.report_id, report_label="Search Query Performance")
        except SpApiError as exc:
            requested.update({
                "status": "BLOCKED_PERMISSION" if "权限" in str(exc) or "HTTP 403" in str(exc) else "FAILED_API",
                "processing_status": exc.processing_status,
            })
            requested_periods.append(requested)
            status = {
                **previous,
                "source_name": "AMAZON_SEARCH_QUERY_PERFORMANCE",
                "report_type": "GET_BRAND_ANALYTICS_SEARCH_QUERY_PERFORMANCE_REPORT",
                "resumed_at": resumed_at,
                "requested_periods": requested_periods,
                "status": requested["status"],
                "reason": str(exc),
            }
            _write_source_status(data_dir, "amazon-search-query-performance.json", status)
            print(str(exc), file=sys.stderr)
            return 3
        inbox = data_dir / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        downloaded = inbox / f"amazon-sqp-{case.own_asin}-{period_start}-{period_end}.json"
        downloaded.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        artifact = store.register(
            downloaded, source_name="AMAZON_SEARCH_QUERY_PERFORMANCE", source_level="L1",
            case=case, asins=(case.own_asin,),
            source_period={"start": period_start.isoformat(), "end": period_end.isoformat(), "basis": "SP_API_WEEK"},
        )
        normalized = normalize_search_query_performance(payload, artifact, case)
        _append_records(metrics_path, normalized)
        availability = "AVAILABLE" if normalized else "AVAILABLE_EMPTY"
        empty_reason = None if normalized else "Amazon 报告下载成功，但 dataByAsin 为空或没有可清洗查询记录"
        requested.update({"status": availability, "artifact_id": artifact.artifact_id, "records": len(normalized)})
        requested_periods.append(requested)
        expected_complete_weeks = len(complete_sqp_weeks(case))
        terminal_periods = [
            item for item in requested_periods
            if item.get("status") in {"AVAILABLE", "AVAILABLE_EMPTY"}
        ]
        covered_complete_weeks = len({
            (item.get("start"), item.get("end"))
            for item in terminal_periods
        })
        any_nonempty = any(item.get("status") == "AVAILABLE" for item in terminal_periods)
        overall_status = "AVAILABLE" if any_nonempty else "AVAILABLE_EMPTY"
        if covered_complete_weeks < expected_complete_weeks:
            overall_status = f"PARTIAL_{overall_status}"
        coverage_reason = (
            f"仅覆盖 {covered_complete_weeks}/{expected_complete_weeks} 个 Case 内完整 SQP 周；"
            + ("已有周含查询数据" if any_nonempty else empty_reason or "已有周为空")
            if covered_complete_weeks < expected_complete_weeks else (
                None if any_nonempty else empty_reason
            )
        )
        artifact_ids = list(dict.fromkeys(
            item["artifact_id"] for item in terminal_periods if item.get("artifact_id")
        ))
        status = {
            **previous,
            "source_name": "AMAZON_SEARCH_QUERY_PERFORMANCE",
            "report_type": "GET_BRAND_ANALYTICS_SEARCH_QUERY_PERFORMANCE_REPORT",
            "resumed_at": resumed_at,
            "requested_periods": requested_periods,
            "status": overall_status,
            "reason": coverage_reason,
            "covered_complete_weeks": covered_complete_weeks,
            "expected_complete_weeks": expected_complete_weeks,
            "artifact_ids": artifact_ids,
        }
        _write_source_status(data_dir, "amazon-search-query-performance.json", status)
        print(json.dumps({
            "report_id": args.report_id, "artifact_id": artifact.artifact_id, "records": len(normalized)
        }, ensure_ascii=False))
        return 0

    if args.command == "fetch-sqp":
        periods = complete_sqp_weeks(case)
        attempted_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        status = {
            "source_name": "AMAZON_SEARCH_QUERY_PERFORMANCE",
            "report_type": "GET_BRAND_ANALYTICS_SEARCH_QUERY_PERFORMANCE_REPORT",
            "attempted_at": attempted_at,
            "analysis_period": {"start": case.period_start.isoformat(), "end": case.period_end.isoformat()},
            "requested_periods": [],
        }
        previous_status = _source_statuses(data_dir).get("AMAZON_SEARCH_QUERY_PERFORMANCE", {})
        previous_requests = {
            (item.get("start"), item.get("end")): item
            for item in previous_status.get("requested_periods", [])
        }
        if not periods:
            status.update({"status": "MISSING_DATA", "reason": "Case 周期内没有完整的周日至周六"})
            _write_source_status(data_dir, "amazon-search-query-performance.json", status)
            print(status["reason"], file=sys.stderr)
            return 4
        artifacts = []
        had_error = False
        def put_requested(item: dict) -> None:
            key = (item.get("start"), item.get("end"))
            status["requested_periods"] = [
                existing for existing in status["requested_periods"]
                if (existing.get("start"), existing.get("end")) != key
            ]
            status["requested_periods"].append(dict(item))

        for period_start, period_end in periods:
            requested = {"start": period_start.isoformat(), "end": period_end.isoformat()}
            previous = previous_requests.get((requested["start"], requested["end"]), {})
            if previous.get("status") in {"AVAILABLE", "AVAILABLE_EMPTY"}:
                put_requested(previous)
                if previous.get("artifact_id"):
                    artifacts.append(previous["artifact_id"])
                continue
            try:
                if previous.get("report_id") and previous.get("status") in {
                    "FAILED_API", "IN_PROGRESS", "IN_QUEUE"
                }:
                    requested["report_id"] = previous["report_id"]
                    payload = client.fetch_report_by_id(
                        previous["report_id"], report_label="Search Query Performance"
                    )
                else:
                    def persist_created(report_id: str) -> None:
                        requested.update({
                            "report_id": report_id,
                            "status": "IN_PROGRESS",
                            "processing_status": "IN_QUEUE",
                        })
                        put_requested(requested)
                        _write_source_status(data_dir, "amazon-search-query-performance.json", status)

                    payload = client.fetch_search_query_performance(
                        case, period_start, period_end, on_created=persist_created
                    )
                    if getattr(client, "last_report_id", None):
                        requested["report_id"] = client.last_report_id
            except SpApiError as exc:
                reason = str(exc)
                blocked = "权限" in reason or "HTTP 401" in reason or "HTTP 403" in reason
                still_processing = exc.processing_status in {"IN_QUEUE", "IN_PROGRESS"}
                requested["status"] = (
                    "BLOCKED_PERMISSION" if blocked else "IN_PROGRESS" if still_processing else "FAILED_API"
                )
                if exc.report_id:
                    requested["report_id"] = exc.report_id
                if exc.processing_status:
                    requested["processing_status"] = exc.processing_status
                requested["reason"] = reason
                put_requested(requested)
                status.update({"status": requested["status"], "reason": reason})
                _write_source_status(data_dir, "amazon-search-query-performance.json", status)
                print(reason, file=sys.stderr)
                had_error = True
                if blocked:
                    break
                continue
            inbox = data_dir / "inbox"
            inbox.mkdir(parents=True, exist_ok=True)
            downloaded = inbox / f"amazon-sqp-{case.own_asin}-{period_start}-{period_end}.json"
            downloaded.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            artifact = store.register(
                downloaded, source_name="AMAZON_SEARCH_QUERY_PERFORMANCE", source_level="L1",
                case=case, asins=(case.own_asin,),
                source_period={"start": period_start.isoformat(), "end": period_end.isoformat(), "basis": "SP_API_WEEK"},
            )
            normalized = normalize_search_query_performance(payload, artifact, case)
            _append_records(metrics_path, normalized)
            availability = "AVAILABLE" if normalized else "AVAILABLE_EMPTY"
            requested.update({"status": availability, "artifact_id": artifact.artifact_id, "records": len(normalized)})
            put_requested(requested)
            artifacts.append(artifact.artifact_id)
            _write_source_status(data_dir, "amazon-search-query-performance.json", status)

        terminal = [
            item for item in status["requested_periods"]
            if item.get("status") in {"AVAILABLE", "AVAILABLE_EMPTY"}
        ]
        expected_complete_weeks = len(periods)
        covered_complete_weeks = len({(item.get("start"), item.get("end")) for item in terminal})
        if covered_complete_weeks == expected_complete_weeks:
            overall_status = "AVAILABLE" if any(item.get("status") == "AVAILABLE" for item in terminal) else "AVAILABLE_EMPTY"
            reason = None if overall_status == "AVAILABLE" else "所有完整 SQP 周均下载成功，但没有可清洗查询记录；不得解释为零曝光或零点击"
        else:
            pending = next((
                item for item in status["requested_periods"]
                if item.get("status") not in {"AVAILABLE", "AVAILABLE_EMPTY"}
            ), None)
            pending_status = pending.get("status") if pending else "MISSING_DATA"
            overall_status = f"PARTIAL_{pending_status}" if covered_complete_weeks else pending_status
            reason = pending.get("reason") if pending else "仍有完整 SQP 周尚未请求"
        status.update({
            "status": overall_status,
            "reason": reason,
            "artifact_ids": list(dict.fromkeys(artifacts)),
            "covered_complete_weeks": covered_complete_weeks,
            "expected_complete_weeks": expected_complete_weeks,
        })
        status_path = _write_source_status(data_dir, "amazon-search-query-performance.json", status)
        print(json.dumps({"artifact_ids": artifacts, "status_path": status_path.as_posix()}, ensure_ascii=False))
        return 3 if had_error else 0

    records = _read_records(metrics_path)
    if not records and case.run_id == case.case_id:
        records = _read_records(legacy_metrics_path)
    output = render_report(case, records, args.output, source_statuses=_source_statuses(data_dir, case))
    print(output)
    return 0

