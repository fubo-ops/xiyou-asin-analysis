from __future__ import annotations

import subprocess
import sys
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


if __name__ == "__main__":
    unittest.main()
