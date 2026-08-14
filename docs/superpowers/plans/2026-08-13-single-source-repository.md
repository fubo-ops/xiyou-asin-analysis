# Single-Source Repository Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the clean `xiyou-asin-analysis` clone into the single maintained code baseline with migrated deterministic tests, CI, and repository safety gates.

**Architecture:** Keep the published `scripts/xiyou_skill/` package as the only implementation. Move deterministic tests and the reusable Phase 2 verifier from the read-only starter-pack backup into the canonical repository, then protect the repository shape and data boundary with a contract test and GitHub Actions.

**Tech Stack:** Python 3.12, pytest 8.x, setuptools, GitHub Actions on Windows.

## Global Constraints

- Do not modify, delete, or rename the starter-pack backup workspace.
- Do not copy `.env`, real Cases, raw data, reports, evidence, private SOP documents, or generated visual reports.
- Do not change diagnostic behavior or public command interfaces.
- Do not commit, push, tag, release, or change GitHub repository settings.
- All changes remain uncommitted in the clean canonical checkout.

---

### Task 1: Repository Contract Test

**Files:**
- Create: `tests/test_repository_contract.py`
- Inspect: `.gitignore`
- Inspect: `.github/workflows/verify.yml`

**Interfaces:**
- Consumes: repository paths relative to `tests/test_repository_contract.py`.
- Produces: four pytest checks that define the canonical package, forbidden duplicate tree, ignored runtime paths, and CI commands.

- [ ] **Step 1: Write the failing repository contract tests**

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_canonical_package_is_the_only_source_tree():
    assert (ROOT / "scripts" / "xiyou_skill" / "cli.py").is_file()
    assert not (ROOT / "src" / "asin_analysis").exists()


def test_runtime_and_generated_paths_are_ignored():
    ignored = set((ROOT / ".gitignore").read_text(encoding="utf-8").splitlines())
    required = {".env", ".venv/", "*.egg-info/", "work/", "data/", "reports/", "logs/"}
    assert required <= ignored


def test_ci_runs_all_deterministic_verification_gates():
    workflow = (ROOT / ".github" / "workflows" / "verify.yml").read_text(encoding="utf-8")
    for command in (
        "python -m pytest -q",
        "python scripts/smoke_test.py --work-dir .smoke-ci",
        "python scripts/validate_distribution.py",
        "git diff --check",
    ):
        assert command in workflow


def test_ci_does_not_receive_business_credentials():
    workflow = (ROOT / ".github" / "workflows" / "verify.yml").read_text(encoding="utf-8")
    assert "SP_API_LWA_CLIENT_SECRET" not in workflow
    assert "SP_API_REFRESH_TOKEN" not in workflow
```

- [ ] **Step 2: Run the contract test and verify RED**

Run:

```powershell
python -m pytest tests/test_repository_contract.py -q
```

Expected: the canonical-package test passes; runtime-ignore and CI tests fail because the ignore entries and workflow do not exist yet.

---

### Task 2: Data Boundary and CI

**Files:**
- Modify: `.gitignore`
- Create: `.github/workflows/verify.yml`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: existing `requirements.txt`, public scripts, and the repository contract from Task 1.
- Produces: local pytest configuration and deterministic GitHub verification.

- [ ] **Step 1: Extend `.gitignore` with exact runtime and generated paths**

Add `*.egg-info/`, `build/`, `dist/`, `.coverage`, `htmlcov/`, and `.smoke-ci/`; preserve the existing credential, work, data, report, export, and log exclusions.

- [ ] **Step 2: Add the Windows verification workflow**

Create `.github/workflows/verify.yml` with:

- push-to-main and pull-request triggers;
- `contents: read` permission;
- concurrency cancellation;
- a 20-minute timeout;
- Python 3.12 with pip cache;
- installation of `requirements.txt` and `.[dev]`;
- the four exact commands asserted by the repository contract.

- [ ] **Step 3: Add test configuration and the dev dependency**

Add to `pyproject.toml`:

```toml
[project.optional-dependencies]
dev = ["pytest>=8.3,<9"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["scripts"]
addopts = "-ra"
```

- [ ] **Step 4: Run the contract test and verify GREEN**

Run:

```powershell
python -m pytest tests/test_repository_contract.py -q
```

Expected: `4 passed`.

---

### Task 3: Migrate the Deterministic Test Suite

**Files:**
- Create: `tests/test_amazon.py`
- Create: `tests/test_cli.py`
- Create: `tests/test_diagnostics.py`
- Create: `tests/test_governance.py`
- Create: `tests/test_raw_store.py`
- Create: `tests/test_report.py`
- Create: `tests/test_verify_phase2.py`
- Create: `tests/test_xiyou.py`
- Create: `tools/verify_phase2.py`

**Interfaces:**
- Consumes: the eight Python test files from the starter-pack backup, its `tools/verify_phase2.py`, and the canonical package exposed on pytest's `pythonpath`.
- Produces: the same deterministic behavior suite running directly against `scripts/xiyou_skill/`.

- [ ] **Step 1: Copy only the eight tracked Python test sources and verifier**

Do not copy caches, test output, data, reports, or other tools.

- [ ] **Step 2: Change test imports mechanically**

Replace only these module prefixes in copied test files:

```text
from asin_analysis -> from xiyou_skill
import asin_analysis -> import xiyou_skill
```

Leave test behavior, expected values, and assertions unchanged.

- [ ] **Step 3: Sanitize ASIN fixtures mechanically**

Map every ASIN fixture into a stable `B0SYNTH001` through `B0SYNTH007` identifier. Preserve identity relationships: repeated source identifiers must map to the same synthetic identifier, and distinct source identifiers must remain distinct.

Where a legacy fixture exercised a downstream gate without an objective, add a concrete diagnostic objective so the newer G0 input-completeness gate passes and the original downstream assertion remains isolated.

- [ ] **Step 4: Run all migrated tests**

Run:

```powershell
python -m pytest -q
```

Expected: all 54 migrated behavior tests plus the 4 repository-contract tests pass.

---

### Task 4: Full Local Release Verification

**Files:**
- Verify: all intentional changes in the canonical repository.

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: fresh evidence that the local tree is a valid, cleanly bounded Skill repository.

- [ ] **Step 1: Run unit and contract tests**

```powershell
python -m pytest -q
```

- [ ] **Step 2: Run synthetic end-to-end smoke**

```powershell
python scripts/smoke_test.py --work-dir .smoke-ci
```

- [ ] **Step 3: Run distribution and sanitization validation**

```powershell
python scripts/validate_distribution.py
```

- [ ] **Step 4: Check patch whitespace and repository state**

```powershell
git diff --check
git status --short
git diff --stat
```

Expected: verification commands exit zero; status lists only the design, plan, CI, ignore/config, test, and verifier changes; no runtime or sensitive files appear.

- [ ] **Step 5: Reconfirm the backup and remote remain unchanged**

```powershell
$backupRepo = Resolve-Path '..\xiyou-asin-analysis-starter-pack\dist\xiyou-asin-analysis'
git -C $backupRepo status --short --branch
git rev-parse HEAD
git rev-parse origin/main
```

Expected: backup nested repo remains `main...origin/main`; canonical local `HEAD` still equals `origin/main` because no commit or push occurred.
