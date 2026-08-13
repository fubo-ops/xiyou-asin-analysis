from __future__ import annotations

import argparse
import sys

from xiyou_skill.cli import main as core_main


def _base(command: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=f"xiyou-asin-analysis: {command}")
    parser.add_argument("--case", required=True)
    parser.add_argument("--data-dir", default="work/data")
    return parser


def run(command: str, argv: list[str] | None = None) -> int:
    parser = _base(command)
    if command == "ingest-xiyou":
        parser.add_argument("--file", required=True)
        parser.add_argument("--source-period-start")
        parser.add_argument("--source-period-end")
        parser.add_argument("--period-basis", default="workbook_or_filename")
        parser.add_argument("--archive-only", action="store_true")
    elif command == "ingest-amazon":
        parser.add_argument("--file", required=True)
    elif command == "resume-sqp":
        parser.add_argument("--report-id", required=True)
        parser.add_argument("--period-start", required=True)
        parser.add_argument("--period-end", required=True)
    elif command == "build-report":
        parser.add_argument("--output", default="work/report.md")
    args = parser.parse_args(argv)
    core = ["--case", args.case, "--data-dir", args.data_dir, command]
    for name in (
        "file", "source_period_start", "source_period_end", "period_basis",
        "report_id", "period_start", "period_end", "output",
    ):
        value = getattr(args, name, None)
        if value is not None:
            core.extend(["--" + name.replace("_", "-"), str(value)])
    if getattr(args, "archive_only", False):
        core.append("--archive-only")
    return core_main(core)


def entry(command: str) -> None:
    raise SystemExit(run(command, sys.argv[1:]))
