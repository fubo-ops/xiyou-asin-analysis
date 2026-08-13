from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from xiyou_skill.cli import main as core_main  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the fully synthetic end-to-end smoke case")
    parser.add_argument("--work-dir", default=".smoke-run")
    return parser


def _write_xiyou_fixture(definition: Path, output: Path) -> None:
    payload = json.loads(definition.read_text(encoding="utf-8"))
    workbook = Workbook()
    overview = workbook.active
    overview.title = "ASIN数据对比"
    overview_rows = payload["overview"]
    overview.append(list(overview_rows[0]))
    for row in overview_rows:
        overview.append([row.get(key) for key in overview_rows[0]])

    keywords = workbook.create_sheet("2026-01-01~2026-01-30——按指标分组")
    keyword_rows = payload["keywords"]
    keywords.append(list(keyword_rows[0]))
    for row in keyword_rows:
        keywords.append([row.get(key) for key in keyword_rows[0]])
    output.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output)


def _assert_traceability(work_dir: Path, report: Path) -> dict[str, int]:
    metric_files = list((work_dir / "data").rglob("metrics.jsonl"))
    if len(metric_files) != 1:
        raise AssertionError(f"expected one metrics.jsonl, got {len(metric_files)}")
    records = [json.loads(line) for line in metric_files[0].read_text(encoding="utf-8").splitlines() if line]
    if not records:
        raise AssertionError("no normalized records")
    evidence_ids = [record["evidence_id"] for record in records]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise AssertionError("duplicate evidence_id")
    for record in records:
        for required in ("artifact_id", "source_name", "source_level", "asin", "period_start", "period_end", "locator", "raw_path", "captured_at"):
            if record.get(required) in (None, ""):
                raise AssertionError(f"missing {required} in {record.get('evidence_id')}")
        if not Path(record["raw_path"]).exists():
            raise AssertionError(f"missing raw artifact: {record['raw_path']}")

    report_text = report.read_text(encoding="utf-8")
    cited = {evidence_id for evidence_id in evidence_ids if evidence_id in report_text}
    if not cited:
        raise AssertionError("report cites no Evidence ID")
    sidecars = list(report.parent.glob(f"{report.stem}.*.json"))
    if len(sidecars) < 4:
        raise AssertionError(f"expected governance sidecars, got {len(sidecars)}")
    return {"records": len(records), "report_citations": len(cited), "sidecars": len(sidecars)}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    work_dir = Path(args.work_dir).resolve()
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    fixture_dir = ROOT / "cases" / "synthetic-case"
    case_path = work_dir / "case.json"
    amazon_path = work_dir / "amazon-sales-traffic.json"
    xiyou_path = work_dir / "xiyou-export.xlsx"
    shutil.copy2(fixture_dir / "case.json", case_path)
    shutil.copy2(fixture_dir / "amazon-sales-traffic.json", amazon_path)
    _write_xiyou_fixture(fixture_dir / "xiyou-fixture.json", xiyou_path)

    data_dir = work_dir / "data"
    report = work_dir / "reports" / "analysis.md"
    commands = [
        ["--case", str(case_path), "--data-dir", str(data_dir), "ingest-xiyou", "--file", str(xiyou_path), "--source-period-start", "2026-01-01", "--source-period-end", "2026-01-30", "--period-basis", "synthetic_fixture"],
        ["--case", str(case_path), "--data-dir", str(data_dir), "ingest-amazon", "--file", str(amazon_path)],
        ["--case", str(case_path), "--data-dir", str(data_dir), "build-report", "--output", str(report)],
    ]
    for command in commands:
        result = core_main(command)
        if result != 0:
            raise SystemExit(result)
    counts = _assert_traceability(work_dir, report)
    print(json.dumps({"status": "PASS", "synthetic_data": True, "report": str(report), **counts}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
