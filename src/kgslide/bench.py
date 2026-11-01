"""Batch runner for the baseline comparison.

Produces the table that the paper actually needs: every unit x every
experimental condition, six quality metrics plus token cost and latency.

    python -m kgslide.bench --units U10,U11,U12 --modes full,zero_shot,rag,cot

Because the constrained prompt *states* which concepts to cover, a single run
cannot distinguish "the graph works" from "the model followed instructions".
Two extra knobs make the comparison meaningful:

* ``--repeat N`` re-samples each cell N times.  Coverage alone is a weak
  signal; its variance across draws is not, and a syllabus constraint is
  supposed to remove that variance.
* ``--thinking disabled`` pins the model's internal reasoning pass off, so the
  ``cot`` baseline is not confounded by reasoning tokens the model emits anyway.

Outputs ``results.csv``, ``results.md`` and ``results.json`` under
``outputs/bench``.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path
from typing import Any

from .constraints import build_constraints
from .graph import Graph
from .llm import BASELINE_MODES, MODES, LLMClient, LLMConfig
from .renderer import render
from .validator import evaluate

METRIC_KEYS = [
    "coverage_rate",
    "oog_rate",
    "background_rate",
    "prerequisite_violation",
    "misconception_coverage",
    "editability",
]

USAGE_KEYS = ["prompt_tokens", "completion_tokens", "reasoning_tokens", "latency_s"]

DEFAULT_KG = Path(__file__).resolve().parents[2] / "data" / "kg_pyds_m4.json"


def _coerce(row: dict) -> dict:
    """CSV gives back strings; the summary code needs numbers again."""
    out = dict(row)
    for key, _ in [(k, None) for k in METRIC_KEYS] + [(k, None) for k in USAGE_KEYS]:
        if key in out:
            try:
                out[key] = float(out[key])
            except (TypeError, ValueError):
                out[key] = 0.0
    out["pages"] = int(float(out.get("pages") or 0))
    out["repeat"] = int(float(out.get("repeat") or 0))
    out["passed"] = str(out.get("passed")).lower() in ("true", "1")
    return out


def _summary_table(rows: list[dict]) -> str:
    """Per-condition aggregate: mean (sd) for each metric."""
    lines = [
        "| 组别 | n | " + " | ".join(METRIC_KEYS) + " | 通过率 | 输出 token |",
        "| --- | --- | " + " | ".join("---" for _ in METRIC_KEYS) + " | --- | --- |",
    ]
    for mode in MODES:
        subset = [r for r in rows if r["mode"] == mode]
        if not subset:
            continue
        cells = []
        for key in METRIC_KEYS:
            values = [r[key] for r in subset]
            mean = statistics.mean(values)
            sd = statistics.stdev(values) if len(values) > 1 else 0.0
            cells.append(f"{mean:.3f} ({sd:.3f})")
        pass_rate = sum(1 for r in subset if r["passed"]) / len(subset)
        tokens = statistics.mean(r["completion_tokens"] for r in subset)
        lines.append(
            f"| {mode} | {len(subset)} | " + " | ".join(cells)
            + f" | {pass_rate:.0%} | {tokens:.0f} |"
        )
    return "\n".join(lines)


def _detail_table(rows: list[dict]) -> str:
    header = "| 讲次 | 组别 | 重复 | 页数 | " + " | ".join(METRIC_KEYS) + " | 判定 |"
    sep = "| --- | --- | --- | --- | " + " | ".join("---" for _ in METRIC_KEYS) + " | --- |"
    lines = [header, sep]
    for row in rows:
        cells = " | ".join(f"{row[k]:.3f}" for k in METRIC_KEYS)
        verdict = "通过" if row["passed"] else "未通过"
        lines.append(
            f"| {row['unit']} | {row['mode']} | {row['repeat']} | {row['pages']} "
            f"| {cells} | {verdict} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kgslide.bench", description="基线对比实验")
    parser.add_argument("--kg", default=str(DEFAULT_KG))
    parser.add_argument("--units", default="U10,U11,U12")
    parser.add_argument("--modes", default=",".join(BASELINE_MODES))
    parser.add_argument("--repeat", type=int, default=1, help="每个单元格重采样次数")
    parser.add_argument("--thinking", default="default", choices=("default", "disabled"))
    parser.add_argument("--temperature", type=float, default=0.3)
    parser.add_argument("--out", default=str(DEFAULT_KG.parent.parent / "outputs" / "bench"))
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--mock", action="store_true")
    parser.add_argument(
        "--append",
        action="store_true",
        help="把本次结果并入已有 results.csv（补跑个别条件时用，不要覆盖整张表）",
    )
    parser.add_argument(
        "--reuse",
        action="store_true",
        help="复用已有的 .json 原始输出重新算指标，不调用 API（改指标时用，省钱且结果可比）",
    )
    args = parser.parse_args(argv)

    graph = Graph.load(Path(args.kg))
    graph.assert_valid()

    units = [u.strip() for u in args.units.split(",") if u.strip()]
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    unknown = set(modes) - set(MODES)
    if unknown:
        parser.error(f"unknown modes: {unknown}")

    client = None
    if not args.reuse:
        client = LLMClient(
            LLMConfig(
                provider="mock" if args.mock else "deepseek",
                model=args.model,
                temperature=args.temperature,
                thinking=args.thinking,
            ),
            force_mock=args.mock,
        )

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for unit in units:
        constraints = build_constraints(graph, unit)
        for mode in modes:
            for rep in range(1, args.repeat + 1):
                tag = f"[{unit}/{mode}#{rep}]"
                payload_path = out_dir / f"{unit}__{mode}__r{rep}.json"

                if args.reuse:
                    if not payload_path.exists():
                        print(f"{tag} 跳过：缺少 {payload_path.name}", flush=True)
                        continue
                    payload = json.loads(payload_path.read_text(encoding="utf-8"))
                    usage = {}
                else:
                    assert client is not None
                    print(f"{tag} ...", flush=True)
                    payload = client.generate_slides(constraints, mode=mode)
                    usage = client.last_usage

                pptx = out_dir / f"{unit}__{mode}__r{rep}.pptx"
                # Keep the raw model output next to the deck: every metric claim
                # in the paper has to be traceable back to a concrete payload.
                if not args.reuse:
                    payload_path.write_text(
                        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                rendered = render(payload, pptx, unit_name=constraints.unit_name)
                report = evaluate(
                    payload, constraints, graph, native_ratio=rendered.native_ratio
                )
                (out_dir / f"{unit}__{mode}__r{rep}.report.md").write_text(
                    f"# {unit} / {mode} / r{rep}\n\n{report.to_markdown()}\n",
                    encoding="utf-8",
                )

                row = {
                    "unit": unit,
                    "mode": mode,
                    "repeat": rep,
                    "pages": rendered.slide_count,
                    "passed": report.passed,
                    **report.metrics,
                    **{k: usage.get(k, 0) for k in USAGE_KEYS},
                }
                rows.append(row)
                print(
                    f"  -> {pptx.name} | coverage={report.metrics['coverage_rate']:.2f} "
                    f"oog={report.metrics['oog_rate']:.2f} "
                    f"prereq={report.metrics['prerequisite_violation']:.2f} "
                    f"mc={report.metrics['misconception_coverage']:.2f} "
                    f"tok={usage.get('completion_tokens', 0)} "
                    f"{usage.get('latency_s', 0)}s"
                )

    if not rows:
        print(f"{out_dir} 下没有可评估的输出，先跑一次生成。")
        return 1

    csv_path = out_dir / "results.csv"
    if args.append and csv_path.exists():
        with csv_path.open(encoding="utf-8") as handle:
            existing = [_coerce(row) for row in csv.DictReader(handle)]
        # New rows win: re-running a condition should correct it, not duplicate it.
        fresh = {(r["unit"], r["mode"], str(r["repeat"])) for r in rows}
        kept = [
            r for r in existing
            if (r["unit"], r["mode"], str(r["repeat"])) not in fresh
        ]
        rows = kept + rows

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    md = "\n\n".join(
        [
            "# 基线对比（各条件均值，括号内为标准差）",
            _summary_table(rows),
            "## 逐条明细",
            _detail_table(rows),
            f"配置：model={args.model} thinking={args.thinking} "
            f"temperature={args.temperature} repeat={args.repeat}",
        ]
    )
    md_path = out_dir / "results.md"
    md_path.write_text(md, encoding="utf-8")

    (out_dir / "results.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print()
    print(_summary_table(rows))
    print(f"\n已写入 {csv_path} / {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
