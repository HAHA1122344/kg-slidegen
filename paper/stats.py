"""Confidence intervals, effect sizes and an equivalence test for the paper.

    python paper/stats.py            # console
    python paper/stats.py --latex    # LaTeX rows

Everything is computed from the recorded runs, so the numbers in the manuscript
can be regenerated rather than retyped.

Caveat that the text must carry: runs are nested in three sessions.  The
bootstrap here resamples runs within a condition, which understates uncertainty
relative to a cluster bootstrap over sessions; with three clusters the latter
is uninformative.  We therefore report both the run-level interval and the
three session means, so the nesting is visible rather than hidden.
"""

from __future__ import annotations

import argparse
import csv
import random
import statistics as st
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "outputs/main_v1/results.csv"
ABL = ROOT / "outputs/bench_ablation/results.csv"

METRICS = ["coverage_rate", "oog_rate", "background_rate",
           "prerequisite_violation", "misconception_coverage"]
ORDER = ["full", "rag_mc", "rag", "placebo", "cot", "zero_shot"]
SEED = 20261101


def load(path: Path) -> dict[str, list[dict]]:
    by = defaultdict(list)
    for r in csv.DictReader(path.open(encoding="utf-8")):
        by[r["mode"]].append(r)
    return by


def boot_ci(vals: list[float], reps: int = 4000) -> tuple[float, float]:
    rng = random.Random(SEED)
    n = len(vals)
    means = sorted(st.mean([rng.choice(vals) for _ in range(n)]) for _ in range(reps))
    return means[int(0.025 * reps)], means[int(0.975 * reps) - 1]


def cliffs_delta(a: list[float], b: list[float]) -> float:
    """P(a > b) - P(a < b); +1 means every a exceeds every b."""
    gt = sum(1 for x in a for y in b if x > y)
    lt = sum(1 for x in a for y in b if x < y)
    return (gt - lt) / (len(a) * len(b))


def tost(a: list[float], b: list[float], margin: float) -> tuple[float, float]:
    """Two one-sided tests for equivalence, Welch standard error.

    H0_lower: diff <= -margin;  H0_upper: diff >= +margin.
    Returns (difference, p) with p = max of the two one-sided p-values, so
    p < 0.05 means the difference is shown to lie within +-margin.
    """
    import math

    diff = st.mean(a) - st.mean(b)
    se = math.sqrt(st.variance(a) / len(a) + st.variance(b) / len(b))
    if se == 0:
        return diff, 0.0
    cdf = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))  # noqa: E731
    p_lower = 1 - cdf((diff + margin) / se)
    p_upper = cdf((diff - margin) / se)
    return diff, max(p_lower, p_upper)


def diff_ci(a: list[float], b: list[float], reps: int = 4000) -> tuple[float, float]:
    """Bootstrap CI for mean(a) - mean(b), resampling within each arm."""
    rng = random.Random(SEED)
    out = sorted(
        st.mean([rng.choice(a) for _ in a]) - st.mean([rng.choice(b) for _ in b])
        for _ in range(reps)
    )
    return out[int(0.025 * reps)], out[int(0.975 * reps) - 1]


def cluster_interval(rows_a: list[dict], rows_b: list[dict], metric: str) -> tuple[float, float, int]:
    """Exact session-cluster bootstrap for mean(a) - mean(b).

    Runs are nested in three sessions, so resampling runs (as ``diff_ci`` does)
    treats nine correlated draws as independent and understates uncertainty.
    With three clusters the honest alternative is to resample *sessions*: there
    are only 3^3 = 27 ordered resamples, so we enumerate all of them instead of
    sampling, and report the 2.5th/97.5th percentile of the resulting
    distribution. The interval is coarse by construction -- 27 points cannot
    support a smooth percentile -- and the paper says so rather than quoting the
    narrower run-level interval as if it were the whole story.
    """
    sessions = sorted({r["unit"] for r in rows_a} | {r["unit"] for r in rows_b})
    index_a = {s: [] for s in sessions}
    index_b = {s: [] for s in sessions}
    for r in rows_a:
        index_a[r["unit"]].append(float(r[metric]))
    for r in rows_b:
        index_b[r["unit"]].append(float(r[metric]))

    diffs = []
    for draw in __import__("itertools").product(sessions, repeat=len(sessions)):
        a = [v for s in draw for v in index_a[s]]
        b = [v for s in draw for v in index_b[s]]
        if a and b:
            diffs.append(st.mean(a) - st.mean(b))
    diffs.sort()
    return diffs[int(0.025 * len(diffs))], diffs[-1 - int(0.025 * len(diffs))], len(diffs)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--latex", action="store_true")
    args = ap.parse_args()

    main_rows = load(MAIN)
    abl_rows = load(ABL)

    print("== run-level bootstrap 95% CI, and the three session means ==")
    for m in METRICS:
        print(f"\n{m}")
        for c in ORDER:
            vals = [float(r[m]) for r in main_rows[c]]
            lo, hi = boot_ci(vals)
            per_unit = defaultdict(list)
            for r in main_rows[c]:
                per_unit[r["unit"]].append(float(r[m]))
            us = " ".join(f"{u}={st.mean(v):.3f}" for u, v in sorted(per_unit.items()))
            print(f"  {c:<10} {st.mean(vals):.3f} [{lo:.3f}, {hi:.3f}]   {us}")

    print("\n== Cliff's delta, full vs baseline, run level (n=9 each) ==")
    for m in METRICS:
        row = []
        a = [float(r[m]) for r in main_rows["full"]]
        for c in ORDER[1:]:
            b = [float(r[m]) for r in main_rows[c]]
            row.append(f"{c}={cliffs_delta(a, b):+.2f}")
        print(f"  {m:<24} " + "  ".join(row))

    print("\n== equivalence test: ordering constraint (ablation, n=6 each) ==")
    a = [float(r["prerequisite_violation"]) for r in abl_rows["full"]]
    b = [float(r["prerequisite_violation"]) for r in abl_rows["no_order"]]
    lo, hi = diff_ci(a, b)
    print(f"  full - no_order = {st.mean(a) - st.mean(b):+.3f}  95% CI [{lo:+.3f}, {hi:+.3f}]")
    for margin in (0.02, 0.05):
        diff, p = tost(a, b, margin)
        print(f"  TOST margin {margin}: p = {p:.3f}"
              f"  -> {'equivalent within margin' if p < 0.05 else 'NOT shown equivalent'}")
    print(f"  full={a}  no_order={b}")

    print("\n== main matrix: full - rag_mc, with CI ==")
    for m in METRICS:
        a = [float(r[m]) for r in main_rows["full"]]
        b = [float(r[m]) for r in main_rows["rag_mc"]]
        lo, hi = diff_ci(a, b)
        clo, chi, n_draws = cluster_interval(main_rows["full"], main_rows["rag_mc"], m)
        print(f"  {m:<24} {st.mean(a) - st.mean(b):+.3f}  run-level [{lo:+.3f}, {hi:+.3f}]"
              f"   session-cluster [{clo:+.3f}, {chi:+.3f}] over {n_draws} draws")

    print("\n  same contrast, by session (the quantity a cluster bootstrap resamples):")
    for s in sorted({r["unit"] for r in main_rows["full"]}):
        a = [float(r["coverage_rate"]) for r in main_rows["full"] if r["unit"] == s]
        b = [float(r["coverage_rate"]) for r in main_rows["rag_mc"] if r["unit"] == s]
        am = [float(r["misconception_coverage"]) for r in main_rows["full"] if r["unit"] == s]
        bm = [float(r["misconception_coverage"]) for r in main_rows["rag_mc"] if r["unit"] == s]
        print(f"    {s}: coverage {st.mean(a) - st.mean(b):+.3f}"
              f"   misconception {st.mean(am) - st.mean(bm):+.3f}")

    print("\n== pass rate, with run-level bootstrap CI ==")
    for c in ORDER:
        flags = [1.0 if r["passed"] == "True" else 0.0 for r in main_rows[c]]
        lo, hi = boot_ci(flags)
        print(f"  {c:<10} {sum(flags):.0f}/{len(flags)}  [{lo:.2f}, {hi:.2f}]")

    if args.latex:
        print("\n% ---- LaTeX rows: mean [95% CI] ----")
        for c in ORDER:
            cells = []
            for m in METRICS:
                vals = [float(r[m]) for r in main_rows[c]]
                lo, hi = boot_ci(vals)
                cells.append(f"{st.mean(vals):.3f} [{lo:.3f}, {hi:.3f}]")
            print(f"\\id{{{c.replace('_', chr(92) + '_')}}} & " + " & ".join(cells) + " \\\\")


if __name__ == "__main__":
    main()
