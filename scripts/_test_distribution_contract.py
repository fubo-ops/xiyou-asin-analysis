from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from validate_distribution import is_allowed_public_asin


ROOT = Path(__file__).resolve().parents[1]


class DistributionContractTests(unittest.TestCase):
    def test_cli_help_does_not_require_runtime_dependencies(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "build_report.py"), "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_allows_only_explicit_synthetic_asin_namespace(self) -> None:
        self.assertTrue(is_allowed_public_asin("B0SYNTH004"))
        self.assertFalse(is_allowed_public_asin("B0" + "REAL0001"))

    def test_real_case_requires_four_to_eight_competitors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    sys.executable, str(ROOT / "scripts" / "create_case.py"),
                    "--output", str(Path(directory) / "case.json"),
                    "--marketplace", "US", "--own-asin", "B000000001",
                    "--competitor", "B000000002", "--competitor", "B000000003",
                    "--period-start", "2026-01-01", "--period-end", "2026-01-30",
                    "--objective", "diagnose a confirmed traffic decline",
                ],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("4 to 8", result.stderr)

    def test_smoke_refuses_to_delete_existing_work_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            work_dir = Path(directory) / "occupied"
            work_dir.mkdir()
            sentinel = work_dir / "keep.txt"
            sentinel.write_text("keep", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "smoke_test.py"), "--work-dir", str(work_dir)],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(sentinel.exists())


if __name__ == "__main__":
    unittest.main()
