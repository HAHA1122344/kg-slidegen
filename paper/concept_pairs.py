"""Concept-level paired test: is the coverage gap carried by a few concepts?

The manuscript reports coverage per deck (n = 9 per condition), which leaves a
reviewer with three clusters and an interval that includes zero once sessions are
resampled. But the deck-level mean throws away the unit the contract is actually
written in: a *concept*. Each session names five or six required concepts, so the
same 54 decks yield ~150 paired concept-level observations, and the question
"does the contract get a concept taught that the baseline leaves out" can be asked
once per concept rather than once per deck.

Two things are computed, both from artefacts already on disk:

1. **Paired concept coverage.** For every (unit, resampling, concept) triple the
   concept is either named or not, under each condition. Comparing ``full`` with a
   baseline on the same triple gives a 2x2 table, and the McNemar exact test asks
   whether the discordant cells are symmetric. Counts are printed beside the test
   so a reader can see how one-directional the effect is.

2. **Leave-one-concept-out.** The deck-level gap is recomputed with each concept
   removed in turn; if the headline gap rested on one easy concept, the range would
   collapse.

No model is called: this is a re-reading of the archived decks.

Usage:
    python paper/concept_pairs.py
    python paper/concept_pairs.py --latex
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from math import comb
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "paper"))

from kgslide.constraints import build_constraints  # noqa: E402
from kgslide.graph import Graph  # noqa: E402
from coverage_sensitivity import covered_ids  # noqa: E402

GRAPH_PATH = ROOT / "data" / "kg_pyds_m4.json"
MAIN = ROOT / "outputs" / "main_v1"
BODY = {"title", "objectives", "summary"}
BASELINES = ["rag_mc", "rag", "placebo", "cot", "zero_shot"]


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar: binomial test on the discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(comb(n, i) for i in range(k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def load_cells() -> dict[tuple[str, str, int], dict[str, bool]]:
    """(unit, mode, rep) -> {concept id: taught?}"""
    graph = Graph.load(GRAPH_PATH)
    cache: dict[str, object] = {}
    cells: dict[tuple[str, str, int], dict[str, bool]] = {}
    for path in sorted(MAIN.glob("*__*__r*.json")):
        unit, mode, rep = path.stem.split("__")
        if unit not in cache:
            cache[unit] = build_constraints(graph, unit)
        constraints = cache[unit]
        payload = json.loads(path.read_text(encoding="utf-8"))
        hit = covered_ids(payload, constraints, graph, BODY)
        cells[(unit, mode, int(rep.lstrip("r")))] = {
            node["id"]: node["id"] in hit for node in constraints.required
        }
    return cells


def paired_rows(cells) -> list[dict]:
    units = sorted({k[0] for k in cells})
    reps = sorted({k[2] for k in cells})
    rows = []
    for base in BASELINES:
        counts = {"both": 0, "full_only": 0, "base_only": 0, "neither": 0}
        per_unit = defaultdict(lambda: [0, 0])
        for unit in units:
            for rep in reps:
                full = cells.get((unit, "full", rep))
                other = cells.get((unit, base, rep))
                if not full or not other:
                    continue
                for concept, taught in full.items():
                    if concept not in other:
                        continue
                    if taught and other[concept]:
                        counts["both"] += 1
                    elif taught:
                        counts["full_only"] += 1
                        per_unit[unit][0] += 1
                    elif other[concept]:
                        counts["base_only"] += 1
                        per_unit[unit][1] += 1
                    else:
                        counts["neither"] += 1
        n = sum(counts.values())
        rows.append(
            {
                "base": base,
                "n": n,
                **counts,
                "rd": (counts["full_only"] - counts["base_only"]) / n if n else 0.0,
                "p": mcnemar_exact(counts["full_only"], counts["base_only"]),
                "per_unit": dict(per_unit),
            }
        )
    return rows


def leave_one_out(cells, base: str = "rag_mc") -> list[dict]:
    units = sorted({k[0] for k in cells})
    reps = sorted({k[2] for k in cells})
    out = []
    for unit in units:
        required = sorted({c for (u, _, _), d in cells.items() if u == unit for c in d})
        for drop in [None] + required:
            keep = [c for c in required if c != drop]
            if not keep:
                continue
            gaps = []
            for rep in reps:
                full = cells.get((unit, "full", rep)) or {}
                other = cells.get((unit, base, rep)) or {}
                if not full or not other:
                    continue
                fh = sum(1 for c in keep if full.get(c))
                bh = sum(1 for c in keep if other.get(c))
                gaps.append((fh - bh) / len(keep))
            out.append(
                {
                    "unit": unit,
                    "drop": drop or "all",
                    "gap": statistics.mean(gaps) if gaps else 0.0,
                    "n": len(gaps),
                }
            )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--latex", action="store_true")
    args = ap.parse_args()

    cells = load_cells()
    units = sorted({k[0] for k in cells})
    n_concepts = {u: len(cells[(u, "full", 1)]) for u in units if (u, "full", 1) in cells}
    print(f"units={units} required concepts per unit={n_concepts}")

    rows = paired_rows(cells)
    print(
        f"\n{'baseline':10s} {'N':>4s} {'both':>5s} {'full+':>6s} {'base+':>6s} "
        f"{'neither':>7s} {'RD':>7s} {'p':>9s}  per-unit full+/base+"
    )
    for r in rows:
        pu = "  ".join(f"{u}:{v[0]}/{v[1]}" for u, v in sorted(r["per_unit"].items()))
        print(
            f"{r['base']:10s} {r['n']:4d} {r['both']:5d} {r['full_only']:6d} "
            f"{r['base_only']:6d} {r['neither']:7d} {r['rd']:+7.3f} {r['p']:9.2e}  {pu}"
        )

    loo = leave_one_out(cells)
    print("\nleave-one-concept-out, deck-level gap vs rag_mc")
    by_unit = defaultdict(list)
    for r in loo:
        by_unit[r["unit"]].append(r)
    for unit, rs in sorted(by_unit.items()):
        base = next(r for r in rs if r["drop"] == "all")
        others = [r["gap"] for r in rs if r["drop"] != "all"]
        print(
            f"  {unit}: all {base['gap']:+.3f}   range over drops "
            f"[{min(others):+.3f}, {max(others):+.3f}]"
        )

    if args.latex:
        def esc(s: str) -> str:
            return s.replace("_", r"\_")

        def sci(p: float) -> str:
            """LaTeX-friendly p value: 9.8e-04 is not typeset as 9.8e-04."""
            if p >= 0.01:
                return f"{p:.3f}"
            mantissa, exponent = f"{p:.1e}".split("e")
            return rf"{mantissa}\times10^{{{int(exponent)}}}"

        lines = [
            r"\begin{tabular}{@{}l rrrr rr@{}}",
            r"\toprule",
            r"Baseline & $N$ & both & \id{full} only & base only & RD & $p$ \\",
            r"\midrule",
        ]
        for r in rows:
            lines.append(
                f"\\id{{{esc(r['base'])}}} & {r['n']} & {r['both']} & "
                f"{r['full_only']} & {r['base_only']} & ${r['rd']:+.3f}$ & "
                f"${sci(r['p'])}$ \\\\"
            )
        lines += [r"\bottomrule", r"\end{tabular}"]
        out = ROOT / "paper" / "latex" / "concept_pairs.tex"
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
