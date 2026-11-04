"""The 2x2 the paper said it did not have: misconception text crossed with structure.

Section 6.2 stated that the factors are never crossed, so interactions are not
estimable, and the review asked for exactly that crossing.  The four cells were
already run -- they are two conditions of the main grid and two conditions of the
ablation batch -- so this is a re-analysis, not a new sweep:

    structure + text   full                 outputs/main_v1
    structure, no text no_misconception     outputs/bench_ablation
    text, no structure rag_mc               outputs/main_v1
    neither            rag                  outputs/main_v1

The outcome is misconception_coverage, the metric the slot exists to move.

Statistics, and why they are this simple.  Runs are nested in sessions and there
are three sessions, so the unit of inference is the session, not the run: nine
runs per cell is three independent observations and six resamples.  The
interaction is therefore computed twice -- as a difference of cell means over
runs, for the table, and as a mean of per-unit interactions, for the inference --
and the interval comes from a bootstrap that resamples sessions with replacement.
The p-value is an exact sign-flip test over the three per-unit interactions,
which is the strongest test three clusters admit: with 2^3 = 8 sign patterns the
smallest attainable p is 0.125, so this design can show a consistent interaction
and cannot show a significant one.  Saying so is the point.

    python paper/factorial.py            # print the table and the intervals
    python paper/factorial.py --latex    # write paper/latex/factorial.tex
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# cell -> (label, directory, mode)
CELLS = {
    "S+T": ("structure + text", "outputs/main_v1", "full"),
    "S": ("structure only", "outputs/bench_ablation", "no_misconception"),
    "T": ("text only", "outputs/main_v1", "rag_mc"),
    "0": ("neither", "outputs/main_v1", "rag"),
}
METRIC = "misconception_coverage"
UNITS = ("U10", "U11", "U12")


def load_cell(directory: str, mode: str) -> dict[str, list[float]]:
    """unit -> every run's metric value for one cell."""
    out: dict[str, list[float]] = {}
    for path in sorted((ROOT / directory).glob(f"*__{mode}__r*.json")):
        unit = path.stem.split("__")[0]
        report = path.with_suffix(".report.md")
        values = _metric_from_report(report)
        if values is None:
            values = _metric_from_payload(path, unit)
        out.setdefault(unit, []).append(values)
    return out


def _metric_from_report(path: Path) -> float | None:
    """Read the metric off the stored report rather than re-scoring.

    Re-scoring would silently pick up later changes to the metric code and stop
    the table from describing the run that was made.
    """
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"| {METRIC} |"):
            try:
                return float(line.split("|")[2])
            except (IndexError, ValueError):
                return None
    return None


def _metric_from_payload(path: Path, unit: str) -> float:
    raise SystemExit(f"{path.name}: no report beside the payload; cannot score {unit} offline")


def cell_stats(cell: dict[str, list[float]]) -> dict[str, float]:
    runs = [v for values in cell.values() for v in values]
    per_unit = [statistics.mean(values) for values in cell.values() if values]
    return {
        "n": len(runs),
        "mean": statistics.mean(runs),
        "sd": statistics.stdev(runs) if len(runs) > 1 else 0.0,
        "units": len(per_unit),
        "unit_mean": statistics.mean(per_unit),
    }


def interaction_per_unit(cells: dict[str, dict[str, list[float]]]) -> dict[str, float]:
    """(S+T - S) - (T - 0), computed inside one session.

    Pairing on the session removes the between-session variance, which is the
    dominant term here: sessions differ in how many misconceptions they carry
    (U10 has one, U11 one, U12 two), so an unpaired contrast would be dominated
    by which session a run happened to be.
    """
    out: dict[str, float] = {}
    for unit in UNITS:
        try:
            st = statistics.mean(cells["S+T"][unit])
            s = statistics.mean(cells["S"][unit])
            t = statistics.mean(cells["T"][unit])
            z = statistics.mean(cells["0"][unit])
        except (KeyError, statistics.StatisticsError):
            continue
        out[unit] = (st - s) - (t - z)
    return out


def bootstrap_interval(
    cells: dict[str, dict[str, list[float]]], draws: int = 20000, seed: int = 20261104
) -> tuple[float, float, float]:
    """Percentile interval for the paired interaction, resampling sessions."""
    rng = random.Random(seed)
    per_cell_unit = {k: {u: statistics.mean(v) for u, v in cell.items() if v} for k, cell in cells.items()}
    units = sorted(set.intersection(*(set(v) for v in per_cell_unit.values())))
    point = statistics.mean(
        (per_cell_unit["S+T"][u] - per_cell_unit["S"][u])
        - (per_cell_unit["T"][u] - per_cell_unit["0"][u])
        for u in units
    )
    values = []
    for _ in range(draws):
        sample = [rng.choice(units) for _ in units]
        values.append(
            statistics.mean(
                (per_cell_unit["S+T"][u] - per_cell_unit["S"][u])
                - (per_cell_unit["T"][u] - per_cell_unit["0"][u])
                for u in sample
            )
        )
    values.sort()
    lo = values[int(0.025 * draws)]
    hi = values[int(0.975 * draws) - 1]
    return point, lo, hi


def sign_flip_p(per_unit: dict[str, float]) -> float:
    """Exact two-sided sign-flip test on the mean of the per-unit interactions.

    With three units there are eight sign patterns; the smallest p this can
    return is 2/8 = 0.25 one-sided, 0.125 for the two-sided statistic below.
    """
    observed = abs(statistics.mean(per_unit.values()))
    values = list(per_unit.values())
    hits = 0
    total = 0
    for signs in itertools.product((1, -1), repeat=len(values)):
        flipped = statistics.mean(s * v for s, v in zip(signs, values))
        total += 1
        if abs(flipped) >= observed - 1e-12:
            hits += 1
    return hits / total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latex", action="store_true", help="write paper/latex/factorial.tex")
    args = parser.parse_args(argv)

    cells = {key: load_cell(directory, mode) for key, (_l, directory, mode) in CELLS.items()}
    stats = {key: cell_stats(cell) for key, cell in cells.items()}
    per_unit = interaction_per_unit(cells)
    point, lo, hi = bootstrap_interval(cells)
    p = sign_flip_p(per_unit)

    effects = {
        "structure": (stats["S+T"]["unit_mean"] + stats["S"]["unit_mean"]) / 2
        - (stats["T"]["unit_mean"] + stats["0"]["unit_mean"]) / 2,
        "text": (stats["S+T"]["unit_mean"] + stats["T"]["unit_mean"]) / 2
        - (stats["S"]["unit_mean"] + stats["0"]["unit_mean"]) / 2,
        "interaction": point,
    }

    print(f"{'cell':<24}{'n':>4}{'mean':>8}{'sd':>8}")
    for key, (label, _d, _m) in CELLS.items():
        s = stats[key]
        print(f"{label:<24}{s['n']:>4}{s['mean']:>8.3f}{s['sd']:>8.3f}")
    print()
    print(f"main effect, structure : {effects['structure']:+.3f}")
    print(f"main effect, text      : {effects['text']:+.3f}")
    print(f"interaction            : {point:+.3f}  95% CI [{lo:+.3f}, {hi:+.3f}]  exact p = {p:.3f}")
    print(f"per-session interaction: " + ", ".join(f"{u} {v:+.3f}" for u, v in per_unit.items()))

    (ROOT / "outputs" / "factorial.json").write_text(
        json.dumps(
            {
                "cells": {k: stats[k] | {"label": CELLS[k][0]} for k in CELLS},
                "effects": effects,
                "interaction_ci": [lo, hi],
                "interaction_p": p,
                "per_unit": per_unit,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    if args.latex:
        st, s_only = stats["S+T"], stats["S"]
        t_only, zero = stats["T"], stats["0"]
        # Not an f-string: the tabular preamble is mostly braces, and doubling
        # every one of them to satisfy the parser is how the column spec gets
        # silently corrupted.
        tex = "\n".join(
            [
                "% Generated by paper/factorial.py --latex. Do not edit by hand.",
                "\\begin{tabular}{@{}lcc@{}}",
                "\\toprule",
                " & \\multicolumn{2}{c}{misconception text} \\\\",
                "\\cmidrule(lr){2-3}",
                " & present & absent \\\\",
                "\\midrule",
                f"contract structure & {st['mean']:.3f} ({st['sd']:.3f}) & {s_only['mean']:.3f} ({s_only['sd']:.3f}) \\\\",
                f"no contract structure & {t_only['mean']:.3f} ({t_only['sd']:.3f}) & {zero['mean']:.3f} ({zero['sd']:.3f}) \\\\",
                "\\bottomrule",
                "\\end{tabular}",
            ]
        )
        (ROOT / "paper" / "latex" / "factorial.tex").write_text(tex + "\n", encoding="utf-8")
        print("\nwrote paper/latex/factorial.tex")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
