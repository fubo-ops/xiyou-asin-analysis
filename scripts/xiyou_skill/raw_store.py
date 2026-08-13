from __future__ import annotations

import hashlib
import json
import mimetypes
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .models import CaseConfig, RawArtifact


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class RawStore:
    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self.raw_dir = self.data_dir / "raw"

    def register(
        self,
        source_path: str | Path,
        *,
        source_name: str,
        source_level: str,
        case: CaseConfig,
        asins: tuple[str, ...] | list[str],
        source_period: dict[str, str] | None = None,
    ) -> RawArtifact:
        source_path = Path(source_path)
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        digest = _sha256(source_path)
        source_slug = source_name.lower().replace("_", "-")
        artifact_id = f"ART-{source_slug.upper()}-{digest[:16]}"
        artifact_dir = self.raw_dir / source_slug / artifact_id
        metadata_path = artifact_dir / "metadata.json"
        if metadata_path.exists():
            return self._from_metadata(metadata_path)

        captured_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        artifact_dir.mkdir(parents=True, exist_ok=True)
        stored_path = artifact_dir / source_path.name
        shutil.copy2(source_path, stored_path)
        metadata = {
            "artifact_id": artifact_id,
            "case_id": case.case_id,
            "run_id": case.run_id,
            "source_name": source_name,
            "source_level": source_level,
            "original_file_name": source_path.name,
            "stored_path": stored_path.as_posix(),
            "content_type": mimetypes.guess_type(source_path.name)[0] or "application/octet-stream",
            "sha256": digest,
            "marketplace": case.marketplace,
            "asins": list(asins),
            "period": {"start": case.period_start.isoformat(), "end": case.period_end.isoformat()},
            "analysis_period": {"start": case.period_start.isoformat(), "end": case.period_end.isoformat()},
            "source_period": source_period,
            "captured_at": captured_at,
            "schema_version": "raw-artifact-v1",
        }
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        with (self.raw_dir / "manifest.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(metadata, ensure_ascii=False) + "\n")
        return RawArtifact(
            artifact_id, source_name, source_level, stored_path, metadata_path, digest, captured_at,
            case.case_id, case.run_id,
        )

    @staticmethod
    def _from_metadata(metadata_path: Path) -> RawArtifact:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        return RawArtifact(
            metadata["artifact_id"], metadata["source_name"], metadata["source_level"],
            Path(metadata["stored_path"]), metadata_path, metadata["sha256"], metadata["captured_at"],
            metadata.get("case_id", ""), metadata.get("run_id", metadata.get("case_id", "")),
        )

