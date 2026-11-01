"""Analyse the teacher blind review in ``human_eval.csv``.

    python paper/human_eval.py            # console summary
    python paper/human_eval.py --latex    # + the LaTeX table used in the paper

Design: 10 decks x 3 raters, five 5-point items plus an unweighted mean
reported by the raters themselves.  Three decks per condition for full,
rag_mc and rag, but only one for placebo -- that asymmetry is reported rather
than smoothed over, and no hypothesis test is run on n = 3.

Agreement is quantified with ICC(2,1) and ICC(2,k) (two-way random effects,
absolute agreement), which is the right family here: the raters are a random
sample of teachers and the decks are scored by all of them.  Confidence
intervals come from resampling decks, not raters, because the deck is the unit
of analysis.
"""

from __future__ import annotations

import argparse
import csv
import statistics as st
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV = Path(__file__).resolve().parent / "human_eval.csv"

ITEMS = [
    ("Q1_Syllabus_Coverage", "Q1", "Syllabus coverage"),
    ("Q2_Misconception_Correction", "Q2", "Misconception correction"),
    ("Q3_Pedagogical_Logic", "Q3", "Pedagogical logic"),
    ("Q4_Content_Accuracy", "Q4", "Content accuracy"),
    ("Q5_Classroom_Readiness", "Q5", "Classroom readiness"),
    ("Overall_Score", "Overall", "Overall"),
]
ORDER = ["full", "rag_mc", "rag", "placebo"]
LABEL_ZH = {"full": "full", "rag_mc": "rag_mc", "rag": "rag", "placebo": "placebo"}
LABEL_EN = {"full": "full (ours)", "rag_mc": "rag\\_mc", "rag": "rag",
            "placebo": "placebo"}


def load() -> list[dict]:
    with CSV.open(encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        for key, _, _ in ITEMS:
            r[key] = float(r[key])
    return rows


def matrix(rows: list[dict], key: str) -> tuple[list[list[float]], list[str]]:
    """Deck x rater matrix, decks sorted by id so every item uses the same layout."""
    decks = sorted({r["Deck_ID"] for r in rows})
    raters = sorted({r["Rater_ID"] for r in rows})
    lookup = {(r["Deck_ID"], r["Rater_ID"]): r[key] for r in rows}
    return [[lookup[(d, t)] for t in raters] for d in decks], decks


def icc(m: list[list[float]]) -> dict:
    """ICC(2,1) and ICC(2,k), two-way random effects, absolute agreement."""
    n, k = len(m), len(m[0])
    grand = sum(sum(row) for row in m) / (n * k)
    row_mean = [sum(row) / k for row in m]
    col_mean = [sum(m[i][j] for i in range(n)) / n for j in range(k)]

    ss_row = k * sum((r - grand) ** 2 for r in row_mean)
    ss_col = n * sum((c - grand) ** 2 for c in col_mean)
    ss_tot = sum((m[i][j] - grand) ** 2 for i in range(n) for j in range(k))
    ss_err = ss_tot - ss_row - ss_col

    ms_row = ss_row / (n - 1)
    ms_col = ss_col / (k - 1)
    ms_err = ss_err / ((n - 1) * (k - 1))

    denom1 = ms_row + (k - 1) * ms_err + k * (ms_col - ms_err) / n
    single = (ms_row - ms_err) / denom1 if denom1 else float("nan")
    denom_k = ms_row + (ms_col - ms_err) / n
    average = (ms_row - ms_err) / denom_k if denom_k else float("nan")
    f = ms_row / ms_err if ms_err else float("inf")
    return {"icc1": single, "icck": average, "F": f,
            "df": ((n - 1), (n - 1) * (k - 1)), "n": n, "k": k}


def bootstrap_icck(rows: list[dict], key: str, reps: int = 2000) -> tuple[float, float]:
    """Percentile CI for ICC(2,k) by resampling decks with replacement."""
    import random

    decks = sorted({r["Deck_ID"] for r in rows})
    by_deck = defaultdict(list)
    for r in rows:
        by_deck[r["Deck_ID"]].append(r[key])
    rng = random.Random(20261101)
    vals = []
    for _ in range(reps):
        pick = [rng.choice(decks) for _ in decks]
        m = [by_deck[d] for d in pick]
        v = icc(m)["icck"]
        if v == v:                       # skip the degenerate resamples
            vals.append(v)
    vals.sort()
    lo = vals[int(0.025 * len(vals))]
    hi = vals[int(0.975 * len(vals)) - 1]
    return lo, hi


def describe(rows: list[dict], key: str, cond: str) -> tuple[float, float, int, int]:
    vals = [r[key] for r in rows if r["Condition"] == cond]
    decks = {r["Deck_ID"] for r in rows if r["Condition"] == cond}
    return st.mean(vals), (st.stdev(vals) if len(vals) > 1 else 0.0), len(vals), len(decks)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--latex", action="store_true")
    args = ap.parse_args()

    rows = load()
    decks = sorted({r["Deck_ID"] for r in rows})
    print(f"decks={len(decks)}  raters={len({r['Rater_ID'] for r in rows})}  "
          f"ratings={len(rows)}")

    # --- integrity: is the reported Overall really the unweighted item mean?
    worst = 0.0
    for r in rows:
        m = sum(r[k] for k, _, _ in ITEMS[:5]) / 5
        worst = max(worst, abs(m - r["Overall_Score"]))
    print(f"max |mean(Q1..Q5) - Overall| = {worst:.4f}")

    # --- agreement
    print("\nagreement (two-way random, absolute agreement)")
    print(f"{'item':<26}{'ICC(2,1)':>10}{'ICC(2,3)':>10}{'95% CI':>18}{'F':>9}")
    icc_rows = []
    for key, short, name in ITEMS:
        m, _ = matrix(rows, key)
        r = icc(m)
        lo, hi = bootstrap_icck(rows, key)
        icc_rows.append((short, name, r, (lo, hi)))
        print(f"{short + ' ' + name:<26}{r['icc1']:>10.3f}{r['icck']:>10.3f}"
              f"{f'[{lo:.3f}, {hi:.3f}]':>18}{r['F']:>9.2f}")

    # --- per-condition descriptives
    print("\nmean (sd) over ratings, and decks per condition")
    head = f"{'item':<26}" + "".join(f"{c:>18}" for c in ORDER)
    print(head)
    stats = {}
    for key, short, _ in ITEMS:
        line = f"{short:<26}"
        for c in ORDER:
            mu, sd, nr, nd = describe(rows, key, c)
            stats[(short, c)] = (mu, sd, nr, nd)
            line += f"{f'{mu:.2f} ({sd:.2f})':>18}"
        print(line)
    line = f"{'decks (n)':<26}" + "".join(
        f"{describe(rows, 'Overall_Score', c)[3]:>18}" for c in ORDER)
    print(line)
    line = f"{'ratings (n)':<26}" + "".join(
        f"{describe(rows, 'Overall_Score', c)[2]:>18}" for c in ORDER)
    print(line)

    # --- where does the effect live?
    print("\nper-item spread across conditions (max - min of means)")
    for key, short, _ in ITEMS:
        mus = [stats[(short, c)][0] for c in ORDER]
        print(f"  {short:<10} spread={max(mus) - min(mus):.2f}   "
              f"best={ORDER[mus.index(max(mus))]}")

    if args.latex:
        print("\n% ---- LaTeX table ----")
        print("\\begin{table}[t]")
        print("\\caption{Teacher blind review on a five-point scale, mean")
        print("  (standard deviation) over ratings. Three decks per condition except")
        print("  \\id{placebo} ($n=1$ deck, descriptive only). ICC$(2,3)$ is the")
        print("  agreement of the average of three raters; the last column repeats it")
        print("  per item.}")
        print("\\label{tab:human}")
        print("\\footnotesize")
        print("\\setlength{\\tabcolsep}{4pt}")
        print("\\begin{tabularx}{\\linewidth}{@{}L{3.6cm}*{4}{>{\\centering\\arraybackslash}X}c@{}}")
        print("\\toprule")
        print("Item & " + " & ".join(LABEL_EN[c] for c in ORDER) + " & ICC$(2,3)$ \\\\")
        print("\\midrule")
        for key, short, name in ITEMS:
            cells = " & ".join(
                f"{stats[(short, c)][0]:.2f} ({stats[(short, c)][1]:.2f})" for c in ORDER)
            ic = next(r for s, _, r, _ in icc_rows if s == short)
            label = f"\\textbf{{{name}}}" if short == "Overall" else name
            print(f"{label} & {cells} & {ic['icck']:.2f} \\\\")
        print("\\midrule")
        print("Decks & " + " & ".join(str(stats[("Overall", c)][3]) for c in ORDER) + " & \\\\")
        print("Ratings & " + " & ".join(str(stats[("Overall", c)][2]) for c in ORDER) + " & \\\\")
        print("\\bottomrule")
        print("\\end{tabularx}")
        print("\\end{table}")


if __name__ == "__main__":
    main()
