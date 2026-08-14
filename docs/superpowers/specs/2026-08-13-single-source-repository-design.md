# Single-Source Repository Migration Design

## Goal

Make the clean `xiyou-asin-analysis` checkout the only maintained local and remote code baseline for the public Agent Skill, while keeping the existing starter-pack workspace unchanged as a temporary backup.

## Problem

The current development workspace is not a Git repository. Its `src/asin_analysis/` package and tests live outside the nested Git repository at `dist/xiyou-asin-analysis/`, whose `scripts/xiyou_skill/` package is what GitHub publishes. The two packages already differ in governance rules, confidence wording, and request import behavior, yet each validates independently. Real credentials, ASINs, raw data, and reports also live beside the untracked development source.

## Approved Architecture

The clean `xiyou-asin-analysis` clone becomes the canonical repository.

- `scripts/xiyou_skill/` is the only maintained Python implementation.
- Public task scripts continue to import that package through the existing `scripts/_runner.py` entry point.
- Deterministic unit tests move into `tests/` and import `xiyou_skill` from `scripts/`.
- Only the reusable Phase 2 verifier moves into `tools/`; visual-report experiments and private SOP material remain in the backup workspace.
- `cases/synthetic-case/` remains the only committed Case data.
- Credentials, real Cases, raw data, generated reports, logs, and browser evidence stay outside the repository or under ignored runtime directories.
- GitHub Actions runs the same deterministic checks that are available locally; it never calls Amazon, Xiyou, a browser, or a paid API.

## Repository Shape

```text
xiyou-asin-analysis/
├── .github/workflows/verify.yml
├── .env.example
├── .gitignore
├── LICENSE
├── README.md
├── SKILL.md
├── pyproject.toml
├── requirements.txt
├── assets/
├── cases/synthetic-case/
├── references/
├── scripts/
│   ├── xiyou_skill/          # canonical implementation
│   ├── _runner.py
│   ├── smoke_test.py
│   └── validate_distribution.py
├── tests/                    # canonical deterministic test suite
├── tools/verify_phase2.py
└── docs/superpowers/specs/   # migration decision record
```

## Data and Credential Boundary

The repository must ignore at least:

- `.env`, `.venv/`, Python caches, build output, and `*.egg-info/`;
- `work/`, `data/`, `reports/`, `exports/`, `logs/`, and smoke-test output;
- editor, operating-system, test-cache, and coverage files.

`scripts/validate_distribution.py` remains the public-tree safety gate. CI must run it so secret-like values, absolute private paths, real ASINs, invalid frontmatter, broken script help, or missing required Skill assets fail the build.

## Test Migration

The existing 54 deterministic tests are copied from the backup workspace, with imports mechanically changed from `asin_analysis` to `xiyou_skill`. All ASIN fixtures are mechanically remapped into the `B0SYNTH*` namespace before validation; assertions and business behavior remain unchanged. Pytest adds `scripts/` to `sys.path` through `pyproject.toml`, so tests and public entry scripts execute the same files.

The migrated suite must first demonstrate the current public behavior. A dedicated repository-contract test then asserts:

1. the obsolete `src/asin_analysis/` tree does not exist in the canonical repository;
2. the canonical package exists at `scripts/xiyou_skill/`;
3. sensitive runtime paths are covered by `.gitignore`;
4. the CI workflow invokes unit tests, synthetic smoke, and distribution validation.

## CI Verification

The Windows workflow runs on pushes to `main` and on pull requests:

1. check out the repository with read-only contents permission;
2. set up Python 3.12 with pip caching;
3. install `requirements.txt` and the `dev` extra;
4. run `python -m pytest -q`;
5. run `python scripts/smoke_test.py --work-dir .smoke-ci`;
6. run `python scripts/validate_distribution.py`;
7. run `git diff --check`.

The workflow uses concurrency cancellation and a bounded timeout. It does not access credentials or external business systems.

## Migration Safety

- Do not move the nested `.git` directory or rewrite repository history.
- Do not copy `.env`, real Cases, `data/`, `reports/`, evidence, or private SOP documents.
- Do not delete or rename the starter-pack workspace during P0.
- Do not commit, push, tag, release, or change repository settings in this phase.
- If verification fails, the clean clone can be removed later after explicit approval; the backup workspace and remote `main` remain unchanged.

## Non-Goals

- No application feature or diagnostic-rule change.
- No README showcase, marketplace metadata, release automation, or cross-runtime packaging work.
- No split into a private engine repository and a public Skill repository.
- No cleanup of real local data or historical reports.

## Acceptance Criteria

- The clean clone contains one Python implementation and no `src/asin_analysis/` duplicate.
- All migrated unit tests pass against `scripts/xiyou_skill/`.
- Synthetic smoke and distribution validation pass from the clean clone.
- The repository contract test protects the single-source and data-boundary decisions.
- `git status --short` shows only intentional, uncommitted P0 changes.
- The starter-pack workspace and GitHub remote remain unchanged.
