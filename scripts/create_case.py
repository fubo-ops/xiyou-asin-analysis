#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from xiyou_skill.models import ASIN_PATTERN


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a validated multi-ASIN diagnostic Case")
    parser.add_argument("--output", required=True)
    parser.add_argument("--marketplace", required=True)
    parser.add_argument("--own-asin", required=True)
    parser.add_argument("--competitor", action="append", default=[])
    parser.add_argument("--period-start", required=True)
    parser.add_argument("--period-end", required=True)
    parser.add_argument("--objective", required=True)
    parser.add_argument("--lifecycle", default="unknown")
    args = parser.parse_args()
    own = args.own_asin.upper()
    competitors = [value.upper() for value in args.competitor]
    if not ASIN_PATTERN.fullmatch(own) or any(not ASIN_PATTERN.fullmatch(value) for value in competitors):
        parser.error("ASIN must contain exactly 10 uppercase letters or digits")
    if own in competitors or len(competitors) != len(set(competitors)):
        parser.error("own ASIN and competitor ASINs must be unique")
    if not 4 <= len(competitors) <= 8:
        parser.error("a real diagnostic Case requires 4 to 8 competitors")
    start, end = date.fromisoformat(args.period_start), date.fromisoformat(args.period_end)
    if start > end:
        parser.error("period start must not be after period end")
    payload = {
        "case_id": f"{own}-{args.marketplace.upper()}-{start:%Y%m%d}-{end:%Y%m%d}",
        "run_id": f"{own}-{args.marketplace.upper()}-{start:%Y%m%d}-{end:%Y%m%d}",
        "marketplace": args.marketplace.upper(),
        "own_asin": own,
        "competitors": competitors,
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "objective": args.objective,
        "lifecycle": args.lifecycle,
        "ruleset_version": "sop-v5.1",
        "competitor_review_status": "PENDING",
        "event_history_status": "MISSING",
        "known_events": [],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
