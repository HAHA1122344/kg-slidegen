"""Turn ``results.csv`` into the tables the manuscript needs.

    python paper/tables.py            # 主表 + 消融表 + 逐讲次表
    python paper/tables.py --latex    # 额外输出 LaTeX

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
    ("coverage_rate", "覆盖 ↑"),
    ("oog_rate", "跑题 ↓"),
    ("background_rate", "背景 ↓"),
    ("prerequisite_violation", "顺序违例 ↓"),
    ("misconception_coverage", "误区 ↑"),
    ("editability", "可编辑 ↑"),
]

ORDER = ["full", "rag_mc", "rag", "cot", "zero_shot", "no_order", "no_misconception", "no_forbidden"]

LABEL = {
    "full": "**full（本文）**",
    "rag_mc": "rag_mc",
    "rag": "rag",
    "cot": "cot",
    "zero_shot": "zero_shot",
    "no_order": "− 顺序约束",
    "no_misconception": "− 误区注入",
    "no_forbidden": "− 禁列词表",
}


def load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for key, _ in METRICS:
            row[key] = float(row[key])
        row["passed"] = row["passed"] in ("True", "true", "1")
        row["completion_tokens"] = int(row.get("completion_tokens") or 0)
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
    head = "| 条件 | n | " + " | ".join(label for _, label in METRICS) + " | 通过率 | 输出 tok |"
    sep = "| --- | :-: | " + " | ".join(":-:" for _ in METRICS) + " | :-: | :-: |"
    lines = [f"**{title}**", "", head, sep]
    for mode in ORDER:
        if mode not in buckets:
            continue
        subset = buckets[mode]
        cells = [fmt([r[key] for r in subset]) for key, _ in METRICS]
        rate = sum(1 for r in subset if r["passed"]) / len(subset)
        tokens = statistics.mean(r["completion_tokens"] for r in subset)
        lines.append(
            f"| {LABEL[mode]} | {len(subset)} | " + " | ".join(cells)
            + f" | {rate:.0%} | {tokens:.0f} |"
        )
    return "\n".join(lines)


def per_unit_markdown(rows: list[dict], modes: tuple[str, ...]) -> str:
    head = "| 讲次 | 条件 | n | " + " | ".join(label for _, label in METRICS) + " |"
    sep = "| :-: | --- | :-: | " + " | ".join(":-:" for _ in METRICS) + " |"
    lines = ["**逐讲次**", "", head, sep]
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
        "**成本与延迟**",
        "",
        "| 条件 | 输入 tok | 输出 tok | reasoning tok | 延迟 (s) |",
        "| --- | :-: | :-: | :-: | :-: |",
    ]
    for mode in ORDER:
        if mode not in buckets:
            continue
        subset = buckets[mode]
        cells = [
            f"{statistics.mean(r.get('prompt_tokens') or 0 for r in subset):.0f}",
            f"{statistics.mean(r['completion_tokens'] for r in subset):.0f}",
            f"{statistics.mean(r.get('reasoning_tokens') or 0 for r in subset):.0f}",
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
        "条件 & " + " & ".join(label for _, label in METRICS) + r" & 通过率 & 输出 tok \\",
        r"\midrule",
    ]
    for mode in ORDER:
        if mode not in buckets:
            continue
        subset = buckets[mode]
        cells = [fmt([r[key] for r in subset]) for key, _ in METRICS]
        rate = sum(1 for r in subset if r["passed"]) / len(subset)
        tokens = statistics.mean(r["completion_tokens"] for r in subset)
        name = LABEL[mode].replace("**", "").replace("（本文）", " (ours)")
        lines.append(
            f"{name} & " + " & ".join(cells) + f" & {rate:.0%} & {tokens:.0f} \\\\"
        )
    lines += [r"\bottomrule", r"\end{tabular}", r"\end{table}"]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--latex", action="store_true")
    args = parser.parse_args()

    main_csv = ROOT / "outputs" / "bench_main" / "results.csv"
    abl_csv = ROOT / "outputs" / "bench_ablation" / "results.csv"

    blocks: list[str] = []
    if main_csv.exists():
        rows = load(main_csv)
        blocks.append(summary_markdown(rows, "表 1  主结果（均值（标准差），n = 讲次 × 重采样）"))
        blocks.append(per_unit_markdown(rows, ("full", "rag_mc", "rag", "zero_shot")))
        blocks.append(cost_markdown(rows))
        if args.latex:
            blocks.append("```latex\n" + to_latex(rows, "Main results", "tab:main") + "\n```")
    else:
        blocks.append(f"（缺少 {main_csv}，先跑主表实验）")

    if abl_csv.exists():
        rows = load(abl_csv)
        blocks.append(summary_markdown(rows, "表 2  消融（每次只删掉图谱的一个部分）"))
        if args.latex:
            blocks.append("```latex\n" + to_latex(rows, "Ablation", "tab:ablation") + "\n```")
    else:
        blocks.append(f"（缺少 {abl_csv}，先跑消融实验）")

    out = ROOT / "paper" / "tables.md"
    out.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    print("\n\n".join(blocks))
    print(f"\n已写入 {out}")


if __name__ == "__main__":
    main()
