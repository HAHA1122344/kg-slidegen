#!/usr/bin/env python3
"""Build the artefact deposit that the Data-availability section points at.

Reviewers who cannot reach the data cannot check anything, and a repository
name without a resolvable identifier is a desk-reject signal at this journal.
This script assembles a self-contained archive -- code, curriculum graph,
prompts, raw model outputs, teacher ratings, and every script that regenerates
a table -- and writes it next to a Zenodo metadata record.

What is deliberately excluded: the virtual environment, byte-code caches,
built PDFs (reproducible from source), and anything under ``deposit/`` itself.
The archive is written with sorted, fixed-timestamp entries so that rebuilding
it twice yields the same bytes; a deposit whose hash changes for no reason is
hard to cite.

Usage
    python paper/make_deposit.py            # write the archive
    python paper/make_deposit.py --check    # report what would go in
"""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "paper" / "deposit"
ARCHIVE = OUT_DIR / "kg-slidegen-v1.0.zip"

INCLUDE_DIRS = ["src", "data", "tests", "config", "outputs"]
INCLUDE_FILES = [
    "README.md",
    "LICENSE",
    "pyproject.toml",
    "requirements.txt",
    "schema.yaml",
]
INCLUDE_GLOBS = [
    ("paper", "*.py"),
    ("paper", "*.md"),
    ("paper", "*.csv"),
    ("paper/independent_coding", "*.py"),
    ("paper/latex", "*.tex"),
    ("paper/latex", "*.bib"),
    ("docs", "*"),
]

EXCLUDE_PARTS = {".venv", "venv", "__pycache__", ".git", "deposit", ".pytest_cache"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".aux", ".out", ".log", ".blg", ".bbl", ".spl"}
EXCLUDE_NAMES = {".DS_Store", "KBS-预评审-20261102.md", "revision-notes.md",
                 "draft-en.md", "draft-zh.md"}
# Internal review notes and superseded drafts are working documents, not
# artefacts: publishing them would leak the review history into the record.


def selected() -> list[Path]:
    files: set[Path] = set()
    for name in INCLUDE_FILES:
        path = ROOT / name
        if path.is_file():
            files.add(path)
    for dirname in INCLUDE_DIRS:
        base = ROOT / dirname
        if base.is_dir():
            files.update(p for p in base.rglob("*") if p.is_file())
    for dirname, pattern in INCLUDE_GLOBS:
        base = ROOT / dirname
        if base.is_dir():
            files.update(p for p in base.glob(pattern) if p.is_file())

    keep: list[Path] = []
    for path in sorted(files):
        rel = path.relative_to(ROOT)
        if EXCLUDE_PARTS & set(rel.parts):
            continue
        if path.suffix in EXCLUDE_SUFFIXES or path.name in EXCLUDE_NAMES:
            continue
        keep.append(path)
    return keep


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="list contents only")
    args = parser.parse_args()

    files = selected()
    total = sum(p.stat().st_size for p in files)
    print(f"{len(files)} files, {total / 1e6:.1f} MB")

    if args.check:
        for path in files:
            print(f"  {path.relative_to(ROOT)}")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if ARCHIVE.exists():
        ARCHIVE.unlink()

    with zipfile.ZipFile(ARCHIVE, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            arcname = Path("kg-slidegen") / path.relative_to(ROOT)
            info = zipfile.ZipInfo(str(arcname), date_time=(2026, 11, 2, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, path.read_bytes())

    digest = hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
    print(f"wrote {ARCHIVE.relative_to(ROOT)}  sha256={digest[:16]}...")

    meta_path = OUT_DIR / "zenodo.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["metadata"]["sha256"] = digest
        meta["metadata"]["files"] = [{"name": ARCHIVE.name, "size": ARCHIVE.stat().st_size}]
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"updated {meta_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
