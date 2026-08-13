#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive an L1/L2/L3 evidence file with lineage metadata")
    parser.add_argument("--case", required=True)
    parser.add_argument("--data-dir", default="work/data")
    parser.add_argument("--file", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--source-level", choices=("L1", "L2", "L3"), required=True)
    parser.add_argument("--purpose", required=True)
    args = parser.parse_args()
    case = json.loads(Path(args.case).read_text(encoding="utf-8"))
    source = Path(args.file)
    if not source.is_file():
        parser.error(f"evidence file not found: {source}")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    artifact_id = "ART-EVIDENCE-" + digest[:16]
    target_dir = Path(args.data_dir) / "runs" / case["case_id"] / case.get("run_id", case["case_id"]) / "evidence" / artifact_id
    target_dir.mkdir(parents=True, exist_ok=True)
    stored = target_dir / source.name
    shutil.copy2(source, stored)
    metadata = {
        "artifact_id": artifact_id,
        "case_id": case["case_id"],
        "run_id": case.get("run_id", case["case_id"]),
        "source": args.source,
        "source_level": args.source_level,
        "purpose": args.purpose,
        "sha256": digest,
        "stored_path": stored.as_posix(),
        "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    (target_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
