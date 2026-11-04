"""Command line interface.

Examples
--------
    python -m kgslide.cli info
    python -m kgslide.cli check-graph
    python -m kgslide.cli inspect --unit U11
    python -m kgslide.cli generate --unit U11 --mock
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .constraints import build_constraints
from .graph import Graph
from .llm import MODES, LLMClient, LLMConfig, LLMError
from .renderer import render
from .validator import evaluate

DEFAULT_KG = Path(__file__).resolve().parents[2] / "data" / "kg_pyds_m4.json"
DEFAULT_OUT = Path(__file__).resolve().parents[2] / "outputs"


def _load(args: argparse.Namespace) -> Graph:
    return Graph.load(Path(args.kg))


def cmd_info(args: argparse.Namespace) -> int:
    graph = _load(args)
    print(graph.describe())
    print()
    for unit in graph.of_type("Unit"):
        concepts = graph.unit_concepts(unit["id"], include_skills=False)
        print(
            f"  {unit['id']:<5} {unit['name']:<16} "
            f"概念 {len(concepts):>2} 个 | 页数预算 {unit.get('slide_budget', '-'):>2}"
        )
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    graph = _load(args)
    issues = graph.validate()
    if not issues:
        print("图谱校验通过，未发现问题。")
        return 0
    for issue in issues:
        print(issue)
    errors = sum(1 for i in issues if i.level == "error")
    print(f"\n合计 {len(issues)} 条，其中 error {errors} 条。")
    return 1 if errors else 0


def cmd_inspect(args: argparse.Namespace) -> int:
    graph = _load(args)
    constraints = build_constraints(graph, args.unit)
    print(constraints.to_prompt_block())
    print("\n---\n约束摘要（JSON）")
    print(json.dumps(constraints.to_dict(), ensure_ascii=False, indent=2))
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    graph = _load(args)
    graph.assert_valid()

    targets = [u["id"] for u in graph.of_type("Unit")] if args.unit == "all" else [args.unit]

    config = LLMConfig(
        provider="mock" if args.mock else args.provider,
        model=args.model,
        temperature=args.temperature,
    )
    client = LLMClient(config, force_mock=args.mock)

    summary: list[dict[str, Any]] = []
    for unit_id in targets:
        constraints = build_constraints(graph, unit_id)
        print(f"[{unit_id}] 生成 {constraints.unit_name} ...", flush=True)

        payload = client.generate_slides(constraints, mode=args.mode)
        suffix = "" if args.mode == "full" else f"__{args.mode}"
        output = Path(args.out) / f"{unit_id}{suffix}.pptx"
        result = render(payload, output, unit_name=constraints.unit_name)

        report = evaluate(payload, constraints, graph, native_ratio=result.native_ratio)
        print(f"[{unit_id}] -> {output}  ({result.slide_count} 页)")
        print(report.to_markdown())
        print()

        if args.dump_json:
            dump = Path(args.out) / f"{unit_id}{suffix}.json"
            dump.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        summary.append(
            {
                "unit": unit_id,
                "pptx": str(output),
                "passed": report.passed,
                **report.metrics,
            }
        )

    if args.summary:
        Path(args.summary).write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"汇总已写入 {args.summary}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kgslide", description="知识图谱约束的课件生成")
    parser.add_argument("--kg", default=str(DEFAULT_KG), help="图谱 JSON 路径")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("info", help="显示图谱概况").set_defaults(func=cmd_info)
    sub.add_parser("check-graph", help="运行结构校验").set_defaults(func=cmd_check)

    p_inspect = sub.add_parser("inspect", help="查看某讲次的生成约束")
    p_inspect.add_argument("--unit", required=True)
    p_inspect.set_defaults(func=cmd_inspect)

    p_gen = sub.add_parser("generate", help="生成课件")
    p_gen.add_argument("--unit", default="all", help="讲次 ID，或 all")
    p_gen.add_argument("--out", default=str(DEFAULT_OUT), help="输出目录")
    p_gen.add_argument("--mock", action="store_true", help="离线演示，不调用 API")
    p_gen.add_argument(
        "--mode",
        default="full",
        choices=list(MODES),
        help="full=本方法；zero_shot / rag / cot 为对照组",
    )
    p_gen.add_argument("--provider", default="deepseek", choices=["deepseek", "kimi", "mock"])
    p_gen.add_argument("--model", default="", help="模型 ID；留空则用 provider 默认值")
    p_gen.add_argument("--temperature", type=float, default=0.3)
    p_gen.add_argument("--dump-json", action="store_true", help="同时保存模型原始输出")
    p_gen.add_argument("--summary", default="", help="将各讲次指标写入 JSON")
    p_gen.set_defaults(func=cmd_generate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (KeyError, ValueError, LLMError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
