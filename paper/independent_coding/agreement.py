#!/usr/bin/env python3
"""Agreement between the original rater and an independent second coder.

Inputs are two CSVs in the format of the coding packet's rubric
(``Deck_ID, Coder_ID, Q1..Q5, Overall_Score, Notes``). Outputs, per item:

    exact agreement, agreement within one point, quadratic-weighted kappa,
    ICC(2,1) and ICC(2,3) on the item, and the decks that disagree most.

It also prints Krippendorff's alpha (ordinal) over the pooled items, which is
the number to quote when a reviewer asks for a single agreement statistic.

Usage
    python paper/independent_coding/agreement.py coderA.csv coderB.csv
    python paper/independent_coding/agreement.py --selftest

Nothing here touches the network and nothing writes to the manuscript: the
numbers are printed so that they can be pasted into §7.5 by hand, after checking
them.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

ITEMS = [
    "Q1_Syllabus_Coverage",
    "Q2_Misconception_Correction",
    "Q3_Pedagogical_Logic",
    "Q4_Content_Accuracy",
    "Q5_Classroom_Readiness",
]
SCALE = [1, 2, 3, 4, 5]


def read(path: Path) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            deck = row["Deck_ID"].strip()
            if not deck:
                continue
            rec = {}
            for k, v in row.items():
                if k in ITEMS or k == "Overall_Score":
                    v = (v or "").strip()
                    if v:
                        rec[k] = float(v)
            out[deck] = rec
    return out


def paired(a, b, item):
    """Decks scored by both coders on this item."""
    pairs = [(a[d][item], b[d][item]) for d in sorted(set(a) & set(b))
             if item in a[d] and item in b[d]]
    return pairs


def icc21(pairs) -> tuple[float, float]:
    """ICC(2,1) and ICC(2,3): two-way random effects, absolute agreement."""
    n, k = len(pairs), 2
    if n < 2:
        return float("nan"), float("nan")
    grand = sum(x + y for x, y in pairs) / (n * k)
    # mean squares
    ms_r = k * sum(((x + y) / k - grand) ** 2 for x, y in pairs) / (n - 1)
    col_a = sum(x for x, _ in pairs) / n
    col_b = sum(y for _, y in pairs) / n
    ms_c = n * ((col_a - grand) ** 2 + (col_b - grand) ** 2) / (k - 1)
    ss_e = sum((x - (x + y) / 2) ** 2 + (y - (x + y) / 2) ** 2 for x, y in pairs)
    ms_e = ss_e / ((n - 1) * (k - 1))
    denom1 = ms_r + (k - 1) * ms_e + k * (ms_c - ms_e) / n
    denom3 = ms_r + (ms_c - ms_e) / n
    icc1 = (ms_r - ms_e) / denom1 if denom1 else float("nan")
    icc3 = (ms_r - ms_e) / denom3 if denom3 else float("nan")
    return icc1, icc3


def weighted_kappa(pairs) -> float:
    """Quadratic-weighted kappa over the 1-5 scale."""
    n = len(pairs)
    if n == 0:
        return float("nan")
    obs = Counter(pairs)
    row = Counter(x for x, _ in pairs)
    col = Counter(y for _, y in pairs)
    num = 0.0
    den = 0.0
    for i in SCALE:
        for j in SCALE:
            w = ((i - j) ** 2) / ((len(SCALE) - 1) ** 2)
            num += w * obs[(i, j)] / n
            den += w * (row[i] / n) * (col[j] / n)
    return 1 - num / den if den else float("nan")


def krippendorff_ordinal(unit_scores: list[list[int]]) -> float:
    """Krippendorff's alpha for ordinal data, complete pairs only."""
    pairs = [u for u in unit_scores if len(u) == 2]
    if not pairs:
        return float("nan")
    values = sorted({v for u in pairs for v in u})
    rank = {v: i + 1 for i, v in enumerate(values)}
    n_total = sum(len(u) for u in pairs)

    # coincidence matrix
    o = defaultdict(float)
    for u in pairs:
        m = len(u)
        for i, vi in enumerate(u):
            for j, vj in enumerate(u):
                if i != j:
                    o[(vi, vj)] += 1.0 / (m - 1)

    def delta(v1, v2):  # ordinal difference
        a, b = sorted((rank[v1], rank[v2]))
        s = sum(k for k in range(a, b + 1))
        return (s - (a + b) / 2) ** 2

    num = sum(o[(c, k)] * delta(c, k) for c in values for k in values)
    marg = {v: sum(o[(v, k)] for k in values) for v in values}
    den = sum(marg[c] * marg[k] * delta(c, k) for c in values for k in values) / (n_total - 1)
    return 1 - num / den if den else float("nan")


def report(a_path: Path, b_path: Path) -> int:
    a, b = read(a_path), read(b_path)
    shared = sorted(set(a) & set(b))
    if not shared:
        print("no deck IDs in common -- are the two files from the same packet?")
        return 2
    print(f"decks: {len(shared)}   coders: {a_path.name} vs {b_path.name}\n")
    print(f"{'item':30} {'exact':>6} {'±1':>6} {'κw':>6} {'ICC(2,1)':>9} {'ICC(2,3)':>9}")
    pooled = []
    for item in ITEMS + ["Overall_Score"]:
        pairs = paired(a, b, item)
        if not pairs:
            continue
        exact = sum(1 for x, y in pairs if x == y) / len(pairs)
        within = sum(1 for x, y in pairs if abs(x - y) <= 1) / len(pairs)
        icc1, icc3 = icc21(pairs)
        print(f"{item:30} {exact:6.2f} {within:6.2f} "
              f"{weighted_kappa(pairs):6.2f} {icc1:9.2f} {icc3:9.2f}")
        pooled.extend([[int(x), int(y)] for x, y in pairs])

    print(f"\nKrippendorff alpha (ordinal, all items pooled): "
          f"{krippendorff_ordinal(pooled):.3f}")

    worst = []
    for deck in shared:
        common = [i for i in ITEMS if i in a[deck] and i in b[deck]]
        if common:
            gap = sum(abs(a[deck][i] - b[deck][i]) for i in common) / len(common)
            worst.append((gap, deck))
    worst.sort(reverse=True)
    print("\nlargest disagreements (mean absolute item gap):")
    for gap, deck in worst[:3]:
        print(f"  {deck}: {gap:.2f}  "
              f"A={[int(a[deck][i]) for i in ITEMS if i in a[deck]]} "
              f"B={[int(b[deck][i]) for i in ITEMS if i in b[deck]]}")
    return 0


def selftest() -> int:
    # perfect agreement on a varying scale: alpha and kappa must both be 1
    perfect = [[1, 1], [3, 3], [4, 4], [5, 5]]
    assert abs(krippendorff_ordinal(perfect) - 1.0) < 1e-12
    assert abs(weighted_kappa([(x, y) for x, y in perfect]) - 1.0) < 1e-12
    # one deck off by one point out of four: alpha drops but stays positive
    mixed = [[4, 4], [3, 4], [5, 5], [2, 2]]
    assert 0.5 < krippendorff_ordinal(mixed) < 1.0, krippendorff_ordinal(mixed)
    # no variance at all: kappa is undefined rather than 1
    flat = weighted_kappa([(3, 3)] * 6)
    assert flat != flat, flat
    icc1, icc3 = icc21([(2, 2), (3, 4), (4, 4), (5, 5)])
    assert 0.5 < icc1 < 1.0 and icc3 > icc1, (icc1, icc3)
    print("selftest ok")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("coder_a", nargs="?", type=Path)
    ap.add_argument("coder_b", nargs="?", type=Path)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if not (args.coder_a and args.coder_b):
        ap.print_help()
        return 2
    return report(args.coder_a, args.coder_b)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
