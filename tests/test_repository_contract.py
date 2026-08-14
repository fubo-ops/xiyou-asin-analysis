from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _workflow_text() -> str:
    workflow_path = ROOT / ".github" / "workflows" / "verify.yml"
    assert workflow_path.is_file(), "missing .github/workflows/verify.yml"
    return workflow_path.read_text(encoding="utf-8")


def test_canonical_package_is_the_only_source_tree():
    assert (ROOT / "scripts" / "xiyou_skill" / "cli.py").is_file()
    assert not (ROOT / "src" / "asin_analysis").exists()


def test_runtime_and_generated_paths_are_ignored():
    ignored = set((ROOT / ".gitignore").read_text(encoding="utf-8").splitlines())
    required = {".env", ".venv/", "*.egg-info/", "work/", "data/", "reports/", "logs/"}
    assert required <= ignored


def test_ci_runs_all_deterministic_verification_gates():
    workflow = _workflow_text()
    for command in (
        "python -m pytest -q",
        "python scripts/smoke_test.py --work-dir .smoke-ci",
        "python scripts/validate_distribution.py",
        "git diff --check",
    ):
        assert command in workflow


def test_ci_does_not_receive_business_credentials():
    workflow = _workflow_text()
    assert "SP_API_LWA_CLIENT_SECRET" not in workflow
    assert "SP_API_REFRESH_TOKEN" not in workflow
