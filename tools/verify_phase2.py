from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path


EVIDENCE_PATTERN = re.compile(r"EV-[0-9a-f]{16}")


def read_source_status(path: Path) -> dict:
    if not path.exists():
        return {
            "source_name": "AMAZON_SEARCH_QUERY_PERFORMANCE",
            "status": "MISSING_DATA",
            "reason": "未找到 SQP 状态文件；没有同周期 SQP 请求或结果",
        }
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--diagnostics", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    report_path = Path(args.report)
    diagnostics_path = Path(args.diagnostics)
    metrics_path = data_dir / "normalized" / "metrics.jsonl"
    manifest_path = data_dir / "raw" / "manifest.jsonl"
    status_path = data_dir / "status" / "amazon-search-query-performance.json"

    records = [json.loads(line) for line in metrics_path.read_text(encoding="utf-8").splitlines() if line]
    manifests = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines() if line]
    diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    status = read_source_status(status_path)
    evidence = {record["evidence_id"] for record in records}
    evidence_counts = Counter(record["evidence_id"] for record in records)
    duplicate_evidence_ids = sorted(key for key, count in evidence_counts.items() if count > 1)
    expected_asins = {asin for manifest in manifests for asin in manifest.get("asins", [])}
    unexpected_asins = sorted({record["asin"] for record in records} - expected_asins)
    analysis_period = manifests[0].get("analysis_period", {}) if manifests else {}
    exact_keywords = [
        record for record in records
        if record["metric"] == "xiyou_keyword_traffic_share"
        and record["period_start"] == analysis_period.get("start")
        and record["period_end"] == analysis_period.get("end")
    ]
    keyword_grain = Counter(str(record.get("dimensions", {}).get("keyword")) for record in exact_keywords)
    expected_asin_count = len(expected_asins)
    incomplete_keyword_groups = sorted(
        keyword for keyword, count in keyword_grain.items() if count != expected_asin_count
    )

    report_evidence = set(EVIDENCE_PATTERN.findall(report_path.read_text(encoding="utf-8")))
    diagnostic_evidence: set[str] = set()
    for stage in diagnostics["stages"].values():
        for metric in stage["metrics"].values():
            diagnostic_evidence.update(metric["evidence_ids"])

    raw_checks = []
    for manifest in manifests:
        raw_path = Path(manifest["stored_path"])
        actual = sha256(raw_path) if raw_path.is_file() else None
        raw_checks.append({
            "artifact_id": manifest["artifact_id"],
            "source_name": manifest["source_name"],
            "stored_path": manifest["stored_path"],
            "expected_sha256": manifest["sha256"],
            "actual_sha256": actual,
            "match": actual == manifest["sha256"],
        })

    sources = Counter(record["source_name"] for record in records)
    forbidden = re.compile(r"(?:mock|fixture|test_data|synthetic)", re.IGNORECASE)
    suspicious_paths = sorted({record["raw_path"] for record in records if forbidden.search(record["raw_path"])})
    result = {
        "status": "PASS",
        "data_dir": data_dir.as_posix(),
        "report": report_path.as_posix(),
        "diagnostics": diagnostics_path.as_posix(),
        "record_count": len(records),
        "records_by_source": dict(sources),
        "artifact_count": len(manifests),
        "unique_evidence_count": len(evidence),
        "duplicate_evidence_ids": duplicate_evidence_ids,
        "unexpected_asins": unexpected_asins,
        "exact_period_keyword_records": len(exact_keywords),
        "exact_period_distinct_keywords": len(keyword_grain),
        "expected_asins_per_keyword": expected_asin_count,
        "incomplete_keyword_groups": incomplete_keyword_groups,
        "raw_hash_checks": raw_checks,
        "all_raw_hashes_match": all(item["match"] for item in raw_checks),
        "report_evidence_count": len(report_evidence),
        "unresolved_report_evidence": sorted(report_evidence - evidence),
        "diagnostic_evidence_count": len(diagnostic_evidence),
        "unresolved_diagnostic_evidence": sorted(diagnostic_evidence - evidence),
        "suspicious_mock_or_fixture_paths": suspicious_paths,
        "sqp_status": status,
    }
    failures = [
        not result["all_raw_hashes_match"],
        bool(result["unresolved_report_evidence"]),
        bool(result["unresolved_diagnostic_evidence"]),
        bool(suspicious_paths),
        bool(duplicate_evidence_ids),
        bool(unexpected_asins),
        bool(incomplete_keyword_groups),
    ]
    if any(failures):
        result["status"] = "FAIL"
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": result["status"], "record_count": result["record_count"],
        "records_by_source": result["records_by_source"],
        "artifact_count": result["artifact_count"],
        "report_evidence_count": result["report_evidence_count"],
        "diagnostic_evidence_count": result["diagnostic_evidence_count"],
        "sqp_status": status["status"],
    }, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
