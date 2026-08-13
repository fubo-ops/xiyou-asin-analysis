from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_ROOT_FILES = {"SKILL.md", "README.md", "LICENSE"}
REQUIRED_DIRS = {"scripts", "references", "assets", "cases"}
TEXT_SUFFIXES = {".md", ".py", ".json", ".toml", ".txt", ".example", ".gitignore"}
ASIN_RE = re.compile(r"\bB0[A-Z0-9]{8}\b")
ABSOLUTE_PATTERNS = (
    re.compile(r"[A-Za-z]:\\"),
    re.compile(r"(?<![\w~.])/(?:Users|home)/"),
)
SECRET_PATTERNS = (
    re.compile(r"github_pat_[A-Za-z0-9_]+"),
    re.compile(r"gh[opusr]_[A-Za-z0-9]+"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"amzn1\.application-oa2-client\.[A-Za-z0-9]+"),
)


def is_allowed_public_asin(asin: str) -> bool:
    return asin.startswith("B0SYNTH") or asin in {"B000000001", "B000000002"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate Agent Skill structure, syntax, and sanitization")
    parser.add_argument("--root", default=str(ROOT))
    return parser


def _text_files(root: Path):
    ignored = {".git", ".venv", "__pycache__", ".smoke-run"}
    for path in root.rglob("*"):
        if not path.is_file() or any(part in ignored for part in path.parts):
            continue
        if path.suffix in TEXT_SUFFIXES or path.name in {"LICENSE", ".gitignore"}:
            yield path


def _fail(errors: list[str], message: str) -> None:
    errors.append(message)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    errors: list[str] = []

    for name in REQUIRED_ROOT_FILES:
        if not (root / name).is_file():
            _fail(errors, f"missing root file: {name}")
    for name in REQUIRED_DIRS:
        if not (root / name).is_dir():
            _fail(errors, f"missing root directory: {name}")

    skill = (root / "SKILL.md").read_text(encoding="utf-8") if (root / "SKILL.md").exists() else ""
    lines = skill.splitlines()
    if len(lines) >= 500:
        _fail(errors, f"SKILL.md must be <500 lines, got {len(lines)}")
    frontmatter = re.match(r"^---\n(.*?)\n---\n", skill, re.DOTALL)
    if not frontmatter:
        _fail(errors, "SKILL.md has no valid YAML frontmatter")
    else:
        values = {}
        for line in frontmatter.group(1).splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                values[key.strip()] = value.strip()
        if values.get("name") != root.name:
            _fail(errors, f"frontmatter name must equal directory name: {root.name}")
        description = values.get("description", "")
        if not description.startswith("Use this skill when"):
            _fail(errors, "description must start with 'Use this skill when'")
        if len(description) > 1024:
            _fail(errors, "description exceeds 1024 characters")
        extra = set(values) - {"name", "description"}
        if extra:
            _fail(errors, f"unsupported frontmatter fields: {sorted(extra)}")

    references = root / "references"
    if references.exists():
        nested = [path for path in references.iterdir() if path.is_dir()]
        if nested:
            _fail(errors, "references must contain no subdirectories")

    if (root / ".env").exists():
        _fail(errors, "real .env is forbidden")
    forbidden_names = [path for path in root.rglob("*") if path.is_file() and path.name.lower() in {"cookies.txt", "cookie.json", "credentials.json"}]
    if forbidden_names:
        _fail(errors, "credential/cookie files found")

    synthetic_asins: set[str] = set()
    for case_file in (root / "cases").rglob("case.json") if (root / "cases").exists() else []:
        payload = json.loads(case_file.read_text(encoding="utf-8"))
        synthetic_asins.add(payload["own_asin"])
        for value in payload.get("competitors", []):
            synthetic_asins.add(value["asin"] if isinstance(value, dict) else value)
    if not synthetic_asins or any(not asin.startswith("B0SYNTH") for asin in synthetic_asins):
        _fail(errors, "all replay-case ASINs must use the B0SYNTH synthetic namespace")

    for path in _text_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            _fail(errors, f"non-UTF-8 text file: {path.relative_to(root)}")
            continue
        for pattern in ABSOLUTE_PATTERNS:
            if pattern.search(text):
                _fail(errors, f"absolute local path found: {path.relative_to(root)}")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                _fail(errors, f"secret-like value found: {path.relative_to(root)}")
        for asin in ASIN_RE.findall(text):
            if not is_allowed_public_asin(asin):
                _fail(errors, f"non-synthetic ASIN found in {path.relative_to(root)}: {asin}")
        if path.suffix == ".py":
            try:
                ast.parse(text, filename=str(path))
            except SyntaxError as exc:
                _fail(errors, f"Python syntax error in {path.relative_to(root)}: {exc}")

    public_scripts = [path for path in (root / "scripts").glob("*.py") if not path.name.startswith("_")]
    for script in public_scripts:
        result = subprocess.run([sys.executable, str(script), "--help"], cwd=root, capture_output=True, text=True)
        if result.returncode != 0:
            _fail(errors, f"--help failed for {script.name}: {result.stderr.strip()}")

    if errors:
        print(json.dumps({"status": "FAIL", "errors": errors}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"status": "PASS", "skill_lines": len(lines), "public_scripts": len(public_scripts), "synthetic_asins": sorted(synthetic_asins)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
