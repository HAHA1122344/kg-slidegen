"""Sensitivity of the coverage metric to the preview-page convention.

The paper scores coverage on teaching slides only, excluding ``title``,
``objectives`` and ``summary`` pages.  A reviewer objected that this can
penalise a deck that defines a concept on the title slide, and that whether a
title-page definition counts as "teaching" is a matter of pedagogical
convention rather than fact.

This script recomputes coverage under three conventions and reports whether
the conclusions move:

    body    title, objectives and summary excluded   (the shipped metric)
    title   objectives and summary excluded, title kept
    all     every slide counted

Matching reuses the validator's own helpers, so the only thing that changes
between variants is which slides are fed to the matcher.

Usage:
    python paper/coverage_sensitivity.py
    python paper/coverage_sensitivity.py --latex
"""

from __future__ import annotations

import argparse
import itertools
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kgslide.constraints import build_constraints  # noqa: E402
from kgslide.graph import Graph  # noqa: E402
from kgslide.validator import (  # noqa: E402
    _present,
    _slide_text,
    _surface_forms,
    _vocabulary,
)

GRAPH_PATH = ROOT / "data" / "kg_pyds_m4.json"
RUNS = [
    ROOT / "outputs" / "main_v1",
    ROOT / "outputs" / "bench_ablation",
]

VARIANTS = {
    "body": {"title", "objectives", "summary"},
    "title": {"objectives", "summary"},
    "all": set(),
}


def covered_ids(payload, constraints, graph, exclude: set[str], forms_fn=None) -> set[str]:
    """Required concept IDs that the deck teaches, under one convention."""
    forms_fn = forms_fn or _surface_forms
    slides = [s for s in payload.get("slides", []) if s.get("layout") not in exclude]
    if not slides:  # a deck made only of preview pages: fall back to all of it
        slides = payload.get("slides", [])
    corpus = "\n".join(_slide_text(s) for s in slides)
    vocabulary = _vocabulary(graph, constraints)

    mentioned = {cid for s in slides for cid in (s.get("concept_ids") or [])}
    for node in constraints.required:
        if _present(forms_fn(node), corpus, vocabulary):
            mentioned.add(node["id"])
    return mentioned


def name_only(node: dict) -> list[str]:
    """Surface forms with the alias list dropped: the counterfactual matcher."""
    return [node.get("name") or ""] if node.get("name") else []


def collect() -> list[dict]:
    graph = Graph.load(GRAPH_PATH)
    cache: dict[str, object] = {}
    rows = []
    for directory in RUNS:
        for path in sorted(directory.glob("*__*__r*.json")):
            unit, mode, rep = path.stem.split("__")
            key = (unit, mode)
            if key not in cache:
                cache[key] = build_constraints(graph, unit)
            constraints = cache[key]
            required = [c["id"] for c in constraints.required]
            payload = json.loads(path.read_text(encoding="utf-8"))

            row = {
                "dir": directory.name,
                "unit": unit,
                "mode": mode,
                "rep": int(rep.lstrip("r")),
                "n_required": len(required),
            }
            for name, exclude in VARIANTS.items():
                hit = covered_ids(payload, constraints, graph, exclude)
                row[name] = len([c for c in required if c in hit]) / len(required)
            hit = covered_ids(payload, constraints, graph, VARIANTS["body"], name_only)
            row["noalias"] = len([c for c in required if c in hit]) / len(required)
            rows.append(row)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--latex", action="store_true", help="emit a LaTeX table")
    ap.add_argument("--csv", type=Path, default=None, help="write the per-run table")
    args = ap.parse_args()

    rows = collect()

    if args.csv:
        header = ["dir", "unit", "mode", "rep", "n_required", *VARIANTS]
        lines = [",".join(header)]
        for r in rows:
            lines.append(
                ",".join(
                    str(r[k]) if k not in VARIANTS else f"{r[k]:.4f}" for k in header
                )
            )
        args.csv.write_text("\n".join(lines) + "\n", encoding="utf-8")

    main_rows = [r for r in rows if r["dir"] == "main_v1"]
    modes = sorted({r["mode"] for r in main_rows})

    print(f"runs: {len(rows)}  (main {len(main_rows)}, ablation {len(rows) - len(main_rows)})")
    print()
    print(f"{'condition':<12}{'n':>4}" + "".join(f"{v:>9}" for v in VARIANTS))
    means: dict[str, dict[str, float]] = {}
    for mode in modes:
        cells = [r for r in main_rows if r["mode"] == mode]
        means[mode] = {v: statistics.fmean(r[v] for r in cells) for v in VARIANTS}
        print(
            f"{mode:<12}{len(cells):>4}"
            + "".join(f"{means[mode][v]:>9.3f}" for v in VARIANTS)
        )

    print()
    print("Per-run change, body -> title convention:")
    changed = [r for r in main_rows if abs(r["title"] - r["body"]) > 1e-9]
    print(f"  runs whose coverage changed: {len(changed)} / {len(main_rows)}")
    for r in changed:
        print(
            f"  {r['unit']}/{r['mode']}/r{r['rep']}: "
            f"{r['body']:.3f} -> {r['title']:.3f} (+{r['title'] - r['body']:.3f})"
        )

    # Does the ranking of conditions survive the switch?
    def ranks(values: dict[str, float]) -> dict[str, int]:
        order = sorted(values, key=lambda m: values[m])
        return {m: i for i, m in enumerate(order)}

    def spearman(a: dict[str, float], b: dict[str, float]) -> float:
        ra, rb = ranks(a), ranks(b)
        n = len(ra)
        d2 = sum((ra[m] - rb[m]) ** 2 for m in ra)
        return 1 - 6 * d2 / (n * (n * n - 1))

    for v in ("title", "all"):
        print(f"  rank correlation body vs {v}: rho = {spearman({m: means[m]['body'] for m in modes}, {m: means[m][v] for m in modes}):.2f}")

    # The two headline contrasts.
    print()
    print("Headline contrasts under each convention (mean difference in coverage):")
    for a, b in [("full", "rag_mc"), ("full", "zero_shot"), ("full", "placebo")]:
        if a in means and b in means:
            cells = "  ".join(
                f"{v}: {means[a][v] - means[b][v]:+.3f}" for v in VARIANTS
            )
            print(f"  {a} - {b}: {cells}")

    if args.latex:
        print()
        print("% --- generated by paper/coverage_sensitivity.py ---")
        print(r"\begin{tabular}{@{}lccc@{}}")
        print(r"\toprule")
        print(
            r"Condition & Body slides & Title kept & All slides \\"
        )
        print(r"\midrule")
        for mode in modes:
            cells = " & ".join(f"{means[mode][v]:.3f}" for v in VARIANTS)
            label = r"\id{" + mode.replace("_", r"\_") + "}"
            print(f"{label} & {cells} \\\\")
        print(r"\bottomrule")
        print(r"\end{tabular}")

    # ---------------------------------------------------------- alias check
    print()
    print("Alias matching: coverage with graph aliases vs name-only matching")
    print(f"{'condition':<12}{'with':>8}{'without':>9}{'delta':>8}")
    for mode in modes:
        cells = [r for r in main_rows if r["mode"] == mode]
        with_alias = statistics.fmean(r["body"] for r in cells)
        without = statistics.fmean(r["noalias"] for r in cells)
        print(f"{mode:<12}{with_alias:>8.3f}{without:>9.3f}{without - with_alias:>+8.3f}")
    changed = [r for r in main_rows if abs(r["noalias"] - r["body"]) > 1e-9]
    print(f"  runs affected: {len(changed)} / {len(main_rows)}")
    for r in sorted(changed, key=lambda r: r["noalias"] - r["body"])[:12]:
        print(
            f"  {r['unit']}/{r['mode']}/r{r['rep']}: "
            f"{r['body']:.3f} -> {r['noalias']:.3f} ({r['noalias'] - r['body']:+.3f})"
        )


if __name__ == "__main__":
    main()
