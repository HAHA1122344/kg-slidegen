#!/usr/bin/env python3
r"""Build the arXiv submission package for the KBS manuscript.

Why a separate build rather than uploading the review PDF's source: the journal
build carries line numbers, a 12pt review layout and internal TODO comments, all
of which are wrong for a preprint and two of which (line numbers, TODO text)
would be visible in the public source.  This script derives an arXiv variant
from the single source of truth, so the two never drift.

What it does
    1. rewrites manuscript.tex for arXiv (preprint option, no \linenumbers,
       graphics path flattened, internal TODO blocks dropped)
    2. stages a self-contained tree: the .tex, the .bbl (so arXiv does not have
       to resolve the bibliography), the .bib for provenance, elsarticle.cls and
       elsarticle-num.bst (both are in TeX Live, but pinning them removes the
       one dependency that could break the build a year from now), and the two
       vector figures
    3. compiles it once to prove the staged tree builds on its own
    4. writes kg-slidegen-arxiv-v<TAG>.zip plus an arXiv metadata sheet

The zip is deterministic: fixed timestamps and sorted entries, so re-running it
from the same tree yields the same bytes.

Usage
    python paper/make_arxiv.py            # build the package
    python paper/make_arxiv.py --check    # list what would go in
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "paper" / "latex" / "manuscript.tex"
OUT = ROOT / "paper" / "arxiv"
BUILD = OUT / "build"

TAG = "v1.4"
ZIP_NAME = f"kg-slidegen-arxiv-{TAG}.zip"

FIGURES = ["framework_en.pdf", "graph_contract_en.pdf"]
CLS = ["elsarticle.cls", "elsarticle-num.bst"]


def transformed_source() -> str:
    """manuscript.tex as it should appear to arXiv."""
    text = SRC.read_text(encoding="utf-8")

    # 1. journal options: review -> preprint (no line numbers, no review rules)
    text = text.replace(
        r"\documentclass[review,12pt]{elsarticle}",
        r"\documentclass[preprint,12pt]{elsarticle}",
    )

    # 2. drop the line-number switch wherever it survives as a live command
    text = re.sub(r"(?m)^\s*\\linenumbers\s*$\n?", "", text)
    text = text.replace(r"\linenumbers", "% line numbers omitted in the arXiv version")

    # 3. figures move next to the .tex, so flatten the search path
    text = text.replace(r"\graphicspath{{../figures/}}", r"\graphicspath{{./}}")

    # 4. internal TODO blocks are notes to ourselves, not part of the record:
    #    drop the whole contiguous comment run that each one starts.
    lines = text.split("\n")
    kept: list[str] = []
    skipping = False
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("% TODO(author)"):
            skipping = True
            continue
        if skipping and stripped.startswith("%"):
            continue
        skipping = False
        kept.append(line)
    text = "\n".join(kept)

    header = (
        "% arXiv version of the manuscript submitted to Knowledge-Based Systems.\n"
        "% Built from the same source as the review PDF; line numbers and internal\n"
        "% notes are removed, nothing else differs. Compile: pdflatex, bibtex,\n"
        "% pdflatex, pdflatex.\n"
    )
    return header + text


def stage() -> Path:
    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir(parents=True)

    src_text = transformed_source()
    (BUILD / "manuscript.tex").write_text(src_text, encoding="utf-8")
    shutil.copy2(SRC.parent / "refs.bib", BUILD / "refs.bib")

    # table fragments pulled in with \input{...}: ship them, or the build stops
    # at the first \input and asks for a file name nobody can type.
    for name in sorted(set(re.findall(r"\\input\{([^}]*)\}", src_text))):
        shutil.copy2(SRC.parent / name, BUILD / name)

    for name in FIGURES:
        shutil.copy2(ROOT / "paper" / "figures" / name, BUILD / name)

    for name in CLS:
        out = subprocess.run(
            ["kpsewhich", name], capture_output=True, text=True, check=True
        ).stdout.strip()
        if not out:
            sys.exit(f"!! {name} not found by kpsewhich; install elsarticle first")
        shutil.copy2(out, BUILD / name)

    return BUILD


def compile_tree(build: Path) -> Path:
    """pbtex loop; raises with the log tail on failure."""
    def run(cmd: list[str]) -> None:
        r = subprocess.run(cmd, cwd=build, capture_output=True, text=True)
        if r.returncode != 0:
            log = (build / "manuscript.log")
            tail = log.read_text(errors="ignore")[-2500:] if log.exists() else r.stdout
            sys.exit(f"!! {' '.join(cmd)} failed\n{tail}")

    run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "manuscript.tex"])
    subprocess.run(["bibtex", "manuscript"], cwd=build, capture_output=True, text=True)
    run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "manuscript.tex"])
    run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "manuscript.tex"])

    log = (build / "manuscript.log").read_text(errors="ignore")
    undefined = log.count("undefined")
    overfull = len(re.findall(r"Overfull \\hbox \(([0-9.]+)pt", log))
    pages = re.search(r"Output written on manuscript\.pdf \((\d+) pages?", log)
    print(f"   compile: {pages.group(1) if pages else '?'} pages, "
          f"{undefined} undefined refs, {overfull} overfull boxes")
    if undefined:
        sys.exit("!! staged tree has undefined references")

    pdf = build / "manuscript.pdf"
    shutil.copy2(pdf, OUT / "manuscript-arxiv.pdf")
    return pdf


def make_zip(build: Path) -> Path:
    """Deterministic archive: sorted entries, fixed timestamp."""
    zip_path = OUT / ZIP_NAME
    if zip_path.exists():
        zip_path.unlink()

    # everything the build needed, minus the files pdflatex/bibtex regenerate
    drop_suffix = {".aux", ".log", ".out", ".blg", ".spl"}
    drop_name = {"manuscript.pdf"}  # regenerated by arXiv; figures are kept
    payload: list[tuple[str, Path]] = []
    for path in sorted(build.iterdir()):
        if path.is_dir() or path.suffix in drop_suffix or path.name in drop_name:
            continue
        payload.append((path.name, path))

    required = {"manuscript.tex", "manuscript.bbl", "refs.bib"}
    missing = required - {n for n, _ in payload}
    if missing:
        sys.exit(f"!! missing from the package: {sorted(missing)}")

    # supplementary PDF travels as an ancillary file, outside the compile set
    supp = ROOT / "paper" / "latex" / "supplementary.pdf"
    if supp.exists():
        payload.append(("anc/supplementary.pdf", supp))

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for arcname, path in sorted(payload):
            info = zipfile.ZipInfo(arcname, date_time=(2026, 11, 5, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, path.read_bytes())
    return zip_path


def metadata(build: Path) -> Path:
    tex = (build / "manuscript.tex").read_text(encoding="utf-8")
    title = " ".join(
        re.search(r"\\title\{(.+?)\}\s*\n\n", tex, re.S).group(1).split()
    )
    abstract = re.search(
        r"\\begin\{abstract\}(.*?)\\end\{abstract\}", tex, re.S
    ).group(1)
    abstract = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?", "", abstract)
    abstract = re.sub(r"[{}~]", "", abstract)
    abstract = " ".join(abstract.split())

    body = f"""arXiv submission sheet — {ZIP_NAME}

Title
    {title}

Authors
    Suxing Liu, Byungwon Min, Zhijian Zheng, Jiahao Wang

Primary category
    cs.CL (Computation and Language)

Cross-lists
    cs.AI (Artificial Intelligence), cs.CY (Computers and Society)

Comments
    Main text 44 pages (preprint layout), 9 tables, 2 figures. Supplementary
    material with 12 sections is included as an ancillary PDF (anc/supplementary.pdf).
    Submitted to Knowledge-Based Systems.

Abstract
    {abstract}

Upload
    Upload {ZIP_NAME} as the source package. arXiv compiles manuscript.tex with
    pdflatex; elsarticle.cls and elsarticle-num.bst are bundled, and manuscript.bbl
    is included so the bibliography resolves even if bibtex is skipped.

Licence
    Choose the licence before uploading; the default (arXiv non-exclusive) lets
    the journal version proceed without a waiver.
"""
    path = OUT / "arxiv-metadata.txt"
    path.write_text(body, encoding="utf-8")
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="list the staged files")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    build = stage()
    if args.check:
        for p in sorted(build.iterdir()):
            print(f"   {p.name:34s} {p.stat().st_size:>9,d} bytes")
        return

    print(f"staged {len(list(build.iterdir()))} files in {build.relative_to(ROOT)}")
    compile_tree(build)
    zip_path = make_zip(build)
    meta = metadata(build)
    print(f"wrote {zip_path.relative_to(ROOT)} ({zip_path.stat().st_size:,d} bytes)")
    print(f"wrote {meta.relative_to(ROOT)}")
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            print(f"   {info.filename:34s} {info.file_size:>9,d} bytes")


if __name__ == "__main__":
    main()
