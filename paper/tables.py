"""Turn ``results.csv`` into the tables the manuscript needs.

    python paper/tables.py            # main, ablation and per-lecture tables
    python paper/tables.py --latex    # also emit LaTeX

Numbers are reported as ``mean (sd)`` over the re-sampling runs, because a
single run of the constrained condition is guaranteed to look perfect (the
concept list is in the prompt).  The spread across runs is the evidence.
"""

from __future__ import annotations

import argparse
import csv
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

METRICS = [
    ("coverage_rate", "Coverage ↑"),
    ("oog_rate", "Off-graph ↓"),
    ("background_rate", "Background ↓"),
    ("prerequisite_violation", "Order viol. ↓"),
    ("misconception_coverage", "Misconception ↑"),
    ("editability", "Editable ↑"),
]

ORDER = ["full", "rag_mc", "rag", "placebo", "cot", "zero_shot",
         "no_order", "no_misconception", "no_forbidden"]

LABEL = {
    "full": "**full (ours)**",
    "rag_mc": "rag_mc",
    "rag": "rag",
    "placebo": "placebo (length-matched)",
    "cot": "cot",
    "zero_shot": "zero_shot",
    "no_order": "− ordering",
    "no_misconception": "− misconception",
    "no_forbidden": "− forbidden list",
}


def load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for key, _ in METRICS:
            row[key] = float(row[key])
        row["passed"] = row["passed"] in ("True", "true", "1")
        row["completion_tokens"] = int(float(row.get("completion_tokens") or 0))
        row["latency_s"] = float(row.get("latency_s") or 0.0)
    return rows


def fmt(values: list[float]) -> str:
    mean = statistics.mean(values)
    sd = statistics.stdev(values) if len(values) > 1 else 0.0
    return f"{mean:.3f} ({sd:.3f})"


def grouped(rows: list[dict]) -> dict[str, list[dict]]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        buckets[row["mode"]].append(row)
    return buckets


def summary_markdown(rows: list[dict], title: str) -> str:
    buckets = grouped(rows)
    head = "| Condition | n | " + " | ".join(label for _, label in METRICS) + " | Pass rate | Output tok |"
    sep = "| --- | :-: | " + " | ".join(":-:" for _ in METRICS) + " | :-: | :-: |"
    lines = [f"**{title}**", "", head, sep]
    for mode in ORDER:
        if mode not in buckets:
            continue
        subset = buckets[mode]
        cells = [fmt([r[key] for r in subset]) for key, _ in METRICS]
        rate = sum(1 for r in subset if r["passed"]) / len(subset)
        tokens = statistics.mean(r["completion_tokens"] for r in subset)
        tok_cell = f"{tokens:.0f}" if tokens else "—"
        lines.append(
            f"| {LABEL[mode]} | {len(subset)} | " + " | ".join(cells)
            + f" | {rate:.0%} | {tok_cell} |"
        )
    return "\n".join(lines)


def per_unit_markdown(rows: list[dict], modes: tuple[str, ...]) -> str:
    head = "| Lecture | Condition | n | " + " | ".join(label for _, label in METRICS) + " |"
    sep = "| :-: | --- | :-: | " + " | ".join(":-:" for _ in METRICS) + " |"
    lines = ["**Per lecture**", "", head, sep]
    units = sorted({r["unit"] for r in rows})
    for unit in units:
        for mode in modes:
            subset = [r for r in rows if r["unit"] == unit and r["mode"] == mode]
            if not subset:
                continue
            cells = [fmt([r[key] for r in subset]) for key, _ in METRICS]
            lines.append(f"| {unit} | {LABEL[mode]} | {len(subset)} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def cost_markdown(rows: list[dict]) -> str:
    buckets = grouped(rows)
    lines = [
        "**Cost and latency**",
        "",
        "| Condition | Input tok | Output tok | reasoning tok | Latency (s) |",
        "| --- | :-: | :-: | :-: | :-: |",
    ]
    for mode in ORDER:
        if mode not in buckets:
            continue
        subset = buckets[mode]
        cells = [
            f"{statistics.mean(float(r.get('prompt_tokens') or 0) for r in subset):.0f}",
            f"{statistics.mean(r['completion_tokens'] for r in subset):.0f}",
            f"{statistics.mean(float(r.get('reasoning_tokens') or 0) for r in subset):.0f}",
            f"{statistics.mean(r['latency_s'] for r in subset):.1f}",
        ]
        lines.append(f"| {LABEL[mode]} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def to_latex(rows: list[dict], title: str, label: str) -> str:
    buckets = grouped(rows)
    cols = "l" + "c" * len(METRICS) + "cc"
    lines = [
        r"\begin{table}[t]",
        r"\centering",
        rf"\caption{{{title}}}",
        rf"\label{{{label}}}",
        rf"\begin{{tabular}}{{{cols}}}",
        r"\toprule",
        "Condition & " + " & ".join(label for _, label in METRICS) + r" & Pass rate & Output tok \\",
        r"\midrule",
    ]
    for mode in ORDER:
        if mode not in buckets:
            continue
        subset = buckets[mode]
        cells = [fmt([r[key] for r in subset]) for key, _ in METRICS]
        rate = sum(1 for r in subset if r["passed"]) / len(subset)
        tokens = statistics.mean(r["completion_tokens"] for r in subset)
        name = LABEL[mode].replace("**", "")
        lines.append(
            f"{name} & " + " & ".join(cells) + f" & {rate:.0%} & {tokens:.0f} \\\\"
        )
    lines += [r"\bottomrule", r"\end{tabular}", r"\end{table}"]
    return "\n".join(lines)


def cross_model_markdown(
    base_rows: list[dict],
    other_rows: list[dict],
    base_label: str = "DeepSeek V4",
    other_label: str = "Kimi K3",
) -> str:
    """Same six conditions under a second backbone, side by side.

    The question this table answers is not "which model is better" -- the two
    ran at different temperatures because one vendor pins sampling -- but
    whether the *contrast* that carries the paper's claim (``full`` minus
    ``rag_mc`` on misconception coverage) keeps its sign.
    """
    metrics = ["coverage_rate", "oog_rate", "prerequisite_violation",
               "misconception_coverage"]
    labels = dict(METRICS)
    head = (
        "| Condition | Backbone | n | "
        + " | ".join(labels[m] for m in metrics)
        + " | Pass rate |"
    )
    sep = "| --- | --- | :-: | " + " | ".join(":-:" for _ in metrics) + " | :-: |"
    lines = ["**Cross-model replication**", "", head, sep]

    def block(rows: list[dict], label: str) -> None:
        buckets = grouped(rows)
        for mode in ORDER[:6]:
            subset = buckets.get(mode)
            if not subset:
                continue
            cells = [fmt([r[m] for r in subset]) for m in metrics]
            rate = sum(1 for r in subset if r["passed"]) / len(subset)
            lines.append(
                f"| {LABEL[mode]} | {label} | {len(subset)} | "
                + " | ".join(cells)
                + f" | {rate:.0%} |"
            )

    block(base_rows, base_label)
    block(other_rows, other_label)

    lines += ["", "**Key contrast: full − rag_mc (misconception coverage / coverage)**", "",
              "| Backbone | Δ misconception | Δ coverage |", "| --- | :-: | :-: |"]
    for rows, label in ((base_rows, base_label), (other_rows, other_label)):
        buckets = grouped(rows)
        if "full" not in buckets or "rag_mc" not in buckets:
            continue
        delta_mc = (
            statistics.mean(r["misconception_coverage"] for r in buckets["full"])
            - statistics.mean(r["misconception_coverage"] for r in buckets["rag_mc"])
        )
        delta_cov = (
            statistics.mean(r["coverage_rate"] for r in buckets["full"])
            - statistics.mean(r["coverage_rate"] for r in buckets["rag_mc"])
        )
        lines.append(f"| {label} | {delta_mc:+.3f} | {delta_cov:+.3f} |")
    return "\n".join(lines)


def cross_model_latex(
    base_rows: list[dict],
    other_rows: list[dict],
    base_label: str = "DeepSeek V4",
    other_label: str = "Kimi K3",
) -> str:
    """LaTeX for supplementary Table S4, same content as the markdown block."""
    metrics = ["coverage_rate", "oog_rate", "prerequisite_violation",
               "misconception_coverage"]
    header = {
        "coverage_rate": "Coverage $\\uparrow$",
        "oog_rate": "Out-of-graph $\\downarrow$",
        "prerequisite_violation": "Order viol. $\\downarrow$",
        "misconception_coverage": "Misconception $\\uparrow$",
    }
    lines = [
        r"\begin{tabular}{@{}l cccc c@{}}",
        r"\toprule",
        "Condition & " + " & ".join(header[m] for m in metrics) + r" & Pass \\",
        r"\midrule",
        rf"\multicolumn{{6}}{{@{{}}l}}{{\emph{{{base_label}}}}} \\",
    ]
    for rows, label, sep in (
        (base_rows, base_label, r"\midrule"),
        (other_rows, other_label, None),
    ):
        buckets = grouped(rows)
        for mode in ORDER[:6]:
            subset = buckets.get(mode)
            if not subset:
                continue
            cells = [fmt([row[metric] for row in subset]) for metric in metrics]
            rate = sum(1 for r in subset if r["passed"]) / len(subset)
            name = LABEL[mode].replace("**", "").replace(" (ours)", "")
            name = name.replace(" (length-matched)", "").replace("_", r"\_")
            # "67%" would comment out the row terminator in LaTeX.
            pct = f"{rate * 100:.0f}\\%"
            lines.append(
                f"\\id{{{name}}} & "
                + " & ".join(cells)
                + f" & {pct} \\\\"
            )
        if sep:
            lines.append(sep)
            lines.append(rf"\multicolumn{{6}}{{@{{}}l}}{{\emph{{{other_label}}}}} \\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines)


def attribution_latex(rows: list[dict], floor: float = 0.03) -> str:
    """One row per (removed block, metric that moves), for Table 5.

    The ablation is read as an attribution problem rather than as a second set
    of condition means: each block is deleted alone and every metric is
    re-measured, so a block's contribution is the movement in the metric it was
    built to govern.  Secondary movement above ``floor`` is printed too, which
    is why the misconception slot contributes two rows -- it also organises the
    key points, and hiding that would overstate the cleanliness of the method.

    ``floor`` is 0.03.  It has to sit above the amplitude of a sampling
    accident -- a single violating run contributes 1/9 of its own rate to the
    batch mean -- and below the slot's real spillover onto coverage, which is
    0.037 once both arms carry nine runs.  At nine runs per arm the forbidden
    list's secondary movement is 0.026 and stays out; the slot's does not.
    """
    buckets = grouped(rows)
    if "full" not in buckets:
        raise SystemExit("attribution needs the `full` arm in the same batch")
    target = {
        "no_misconception": "misconception_coverage",
        "no_forbidden": "oog_rate",
        "no_order": "prerequisite_violation",
    }
    header = {
        "coverage_rate": "Coverage $\\uparrow$",
        "oog_rate": "Out-of-graph $\\downarrow$",
        "prerequisite_violation": "Order viol. $\\downarrow$",
        "misconception_coverage": "Misconception $\\uparrow$",
    }
    name = {
        "no_misconception": "Misconception slot",
        "no_forbidden": "Forbidden list",
        "no_order": "Ordering block",
    }
    base = {key: statistics.mean(r[key] for r in buckets["full"]) for key in header}
    lines = [
        r"\begin{tabular}{@{}l l cc r@{}}",
        r"\toprule",
        r"Block removed & Metric & \id{full} & Without & $\Delta$ \\",
        r"\midrule",
    ]
    for arm in ("no_misconception", "no_forbidden", "no_order"):
        subset = buckets.get(arm)
        if not subset:
            continue
        deltas = {
            key: statistics.mean(r[key] for r in subset) - base[key] for key in header
        }
        order = sorted(header, key=lambda k: (k != target[arm], -abs(deltas[k])))
        for key in order:
            primary = key == target[arm]
            if not primary and abs(deltas[key]) < floor:
                continue
            value = fmt([r[key] for r in subset])
            lines.append(
                f"{name[arm]} & {header[key]}{'' if primary else ' (side)'} "
                f"& {fmt([r[key] for r in buckets['full']])} & {value} "
                f"& ${deltas[key]:+.3f}$ \\\\"
            )
    lines += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines)


def course_b_latex(rows: list[dict]) -> str:
    """Table for the second-course replication (three conditions, four metrics).

    Kept separate from ``to_latex`` because the second course has no ablation
    arms and no ``rag``/``cot``/``placebo`` baselines: a table that borrows the
    main one's column set would print three empty conditions and invite a reader
    to compare cells across courses, which is exactly what the text says not to
    do.
    """
    metrics = ["coverage_rate", "oog_rate", "prerequisite_violation",
               "misconception_coverage"]
    header = {
        "coverage_rate": "Coverage $\\uparrow$",
        "oog_rate": "Out-of-graph $\\downarrow$",
        "prerequisite_violation": "Order viol. $\\downarrow$",
        "misconception_coverage": "Misconception $\\uparrow$",
    }
    buckets = grouped(rows)
    lines = [
        r"\begin{tabular}{@{}l cccc@{}}",
        r"\toprule",
        "Condition & " + " & ".join(header[m] for m in metrics) + r" \\",
        r"\midrule",
    ]
    for mode in ("full", "rag_mc", "zero_shot"):
        subset = buckets.get(mode)
        if not subset:
            continue
        cells = [fmt([row[m] for row in subset]) for m in metrics]
        name = LABEL[mode].replace("**", "")
        lines.append(f"{name.replace('_', chr(92) + '_')} & " + " & ".join(cells) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines)


def sweep_latex(specs: list[tuple[str, str, list[dict]]]) -> str:
    """One row per (backbone, course) cell: the two paired contrasts and the
    dispersion of the constrained arm.

    This is the table that separates "the course changed" from "the backbone
    changed". Three of the rows hold the course, graph, prompts and validator
    fixed and vary only the endpoint; the fourth holds the endpoint fixed and
    varies the course. If the slot's advantage tracked the course, the first
    three rows would agree and the fourth would not.
    """
    lines = [
        r"\begin{tabular}{@{}l l cc r@{}}",
        r"\toprule",
        r"Backbone & Course & $\Delta$ coverage & $\Delta$ misconception"
        r" & \id{full}'s misconception \\",
        r"\midrule",
    ]
    for backbone, course, rows in specs:
        buckets = grouped(rows)
        if "full" not in buckets or "rag_mc" not in buckets:
            continue
        cf = statistics.mean(r["coverage_rate"] for r in buckets["full"])
        cr = statistics.mean(r["coverage_rate"] for r in buckets["rag_mc"])
        mf = statistics.mean(r["misconception_coverage"] for r in buckets["full"])
        mr = statistics.mean(r["misconception_coverage"] for r in buckets["rag_mc"])
        sd = (
            statistics.stdev([r["misconception_coverage"] for r in buckets["full"]])
            if len(buckets["full"]) > 1
            else 0.0
        )
        lines.append(
            f"{backbone} & {course} & ${cf - cr:+.3f}$ & ${mf - mr:+.3f}$"
            f" & {mf:.3f} ({sd:.3f}) \\\\"
        )
    lines += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines)


def sweep_markdown(specs: list[tuple[str, str, list[dict]]]) -> str:
    lines = [
        "**Backbone × course: the two paired differences**",
        "",
        "| Backbone | Course | n(full) | "
        "Δ coverage (full−rag_mc) | Δ misconception | "
        "full's misconception, mean (sd) |",
        "| --- | --- | :-: | :-: | :-: | :-: |",
    ]
    for backbone, course, rows in specs:
        buckets = grouped(rows)
        if "full" not in buckets or "rag_mc" not in buckets:
            continue
        cf = statistics.mean(r["coverage_rate"] for r in buckets["full"])
        cr = statistics.mean(r["coverage_rate"] for r in buckets["rag_mc"])
        mf = statistics.mean(r["misconception_coverage"] for r in buckets["full"])
        mr = statistics.mean(r["misconception_coverage"] for r in buckets["rag_mc"])
        cell = fmt([r["misconception_coverage"] for r in buckets["full"]])
        lines.append(
            f"| {backbone} | {course} | {len(buckets['full'])} | {cf - cr:+.3f}"
            f" | {mf - mr:+.3f} | {cell} |"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--latex", action="store_true")
    parser.add_argument("--main", default="", help="main-table directory; the newest one by default")
    parser.add_argument("--abl", default="", help="ablation directory")
    parser.add_argument("--cross", default="", help="second-backbone directory, e.g. outputs/bench_kimi")
    parser.add_argument("--course-b", default="", help="second-course directory, e.g. outputs/bench_cpp")
    parser.add_argument(
        "--sweep",
        default="",
        help='backbone × course sweep: semicolon-separated "backbone|course|dir", e.g. '
             '"DeepSeek V4|Python|outputs/main_v1;Kimi K3|Python|outputs/bench_kimi"',
    )
    args = parser.parse_args()

    def pick(explicit: str, *candidates: str) -> Path:
        if explicit:
            return Path(explicit) / "results.csv"
        for name in candidates:
            path = ROOT / "outputs" / name / "results.csv"
            if path.exists():
                return path
        return ROOT / "outputs" / candidates[0] / "results.csv"

    main_csv = pick(args.main, "main_v1", "bench_main")
    abl_csv = pick(args.abl, "ablation_v1", "bench_ablation")

    blocks: list[str] = []
    if main_csv.exists():
        rows = load(main_csv)
        blocks.append(summary_markdown(rows, "Table 1  Main results (mean (sd), n = lectures × resamplings)"))
        blocks.append(per_unit_markdown(rows, ("full", "rag_mc", "rag", "zero_shot")))
        blocks.append(cost_markdown(rows))
        if args.latex:
            blocks.append("```latex\n" + to_latex(rows, "Main results", "tab:main") + "\n```")
    else:
        blocks.append(f"(missing {main_csv}; run the main experiment first)")

    if abl_csv.exists():
        rows = load(abl_csv)
        blocks.append(summary_markdown(rows, "Table 2  Ablations (one part of the graph removed at a time)"))
        if args.latex:
            blocks.append("```latex\n" + to_latex(rows, "Ablation", "tab:ablation") + "\n```")
            attrib = attribution_latex(rows)
            (ROOT / "paper" / "latex" / "attribution.tex").write_text(
                attrib + "\n", encoding="utf-8"
            )
            blocks.append("```latex\n" + attrib + "\n```")
    else:
        blocks.append(f"(missing {abl_csv}; run the ablation first)")

    out = ROOT / "paper" / "tables.md"
    out.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    print("\n\n".join(blocks))

    if args.course_b:
        cb_csv = Path(args.course_b) / "results.csv"
        if cb_csv.exists():
            cb_rows = load(cb_csv)
            tex = course_b_latex(cb_rows)
            (ROOT / "paper" / "latex" / "course_b.tex").write_text(tex + "\n", encoding="utf-8")
            with out.open("a", encoding="utf-8") as handle:
                handle.write("\n\n" + summary_markdown(cb_rows, "Table 3  Second course (C++ arrays)") + "\n")
            print("\nwrote paper/latex/course_b.tex")
        else:
            print(f"\n(missing {cb_csv})")

    if args.cross:
        cross_csv = Path(args.cross) / "results.csv"
        if cross_csv.exists() and main_csv.exists():
            base_rows, other_rows = load(main_csv), load(cross_csv)
            block = cross_model_markdown(base_rows, other_rows)
            tex = cross_model_latex(base_rows, other_rows)
            (ROOT / "paper" / "latex" / "cross_model.tex").write_text(
                tex + "\n", encoding="utf-8"
            )
            with out.open("a", encoding="utf-8") as handle:
                handle.write("\n\n" + block + "\n")
            print("\n\n" + block)
            print("\nwrote paper/latex/cross_model.tex")
        else:
            print(f"\n(missing {cross_csv})")

    if args.sweep:
        specs: list[tuple[str, str, list[dict]]] = []
        for chunk in args.sweep.split(";"):
            if not chunk.strip():
                continue
            backbone, course, directory = (part.strip() for part in chunk.split("|"))
            csv_path = Path(directory) / "results.csv"
            if csv_path.exists():
                specs.append((backbone, course, load(csv_path)))
            else:
                print(f"(missing {csv_path})")
        if specs:
            tex = sweep_latex(specs)
            (ROOT / "paper" / "latex" / "sweep.tex").write_text(tex + "\n", encoding="utf-8")
            with out.open("a", encoding="utf-8") as handle:
                handle.write("\n\n" + sweep_markdown(specs) + "\n")
            print("\nwrote paper/latex/sweep.tex")

    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
