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
            f"concepts {len(concepts):>2} | page budget {unit.get('slide_budget', '-'):>2}"
        )
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    graph = _load(args)
    issues = graph.validate()
    if not issues:
        print("Graph validation passed, no issues found.")
        return 0
    for issue in issues:
        print(issue)
    errors = sum(1 for i in issues if i.level == "error")
    print(f"\n{len(issues)} issues in total, {errors} of them errors.")
    return 1 if errors else 0


def cmd_inspect(args: argparse.Namespace) -> int:
    graph = _load(args)
    constraints = build_constraints(graph, args.unit)
    print(constraints.to_prompt_block())
    print("\n---\nconstraint summary (JSON)")
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
        print(f"[{unit_id}] generating {constraints.unit_name} ...", flush=True)

        payload = client.generate_slides(constraints, mode=args.mode)
        suffix = "" if args.mode == "full" else f"__{args.mode}"
        output = Path(args.out) / f"{unit_id}{suffix}.pptx"
        result = render(payload, output, unit_name=constraints.unit_name)

        report = evaluate(payload, constraints, graph, native_ratio=result.native_ratio)
        print(f"[{unit_id}] -> {output}  ({result.slide_count} slides)")
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
        print(f"summary written to {args.summary}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kgslide", description="knowledge-graph-constrained courseware generation")
    parser.add_argument("--kg", default=str(DEFAULT_KG), help="path to the graph JSON")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("info", help="show a summary of the graph").set_defaults(func=cmd_info)
    sub.add_parser("check-graph", help="run the structural checks").set_defaults(func=cmd_check)

    p_inspect = sub.add_parser("inspect", help="show the generation contract for one lecture")
    p_inspect.add_argument("--unit", required=True)
    p_inspect.set_defaults(func=cmd_inspect)

    p_gen = sub.add_parser("generate", help="generate courseware")
    p_gen.add_argument("--unit", default="all", help="lecture ID, or all")
    p_gen.add_argument("--out", default=str(DEFAULT_OUT), help="output directory")
    p_gen.add_argument("--mock", action="store_true", help="offline demo, no API calls")
    p_gen.add_argument(
        "--mode",
        default="full",
        choices=list(MODES),
        help="full = this method; zero_shot / rag / cot are the baselines",
    )
    p_gen.add_argument("--provider", default="deepseek", choices=["deepseek", "kimi", "mock"])
    p_gen.add_argument("--model", default="", help="model ID; left empty, the provider default is used")
    p_gen.add_argument("--temperature", type=float, default=0.3)
    p_gen.add_argument("--dump-json", action="store_true", help="also save the raw model output")
    p_gen.add_argument("--summary", default="", help="write the per-lecture metrics to JSON")
    p_gen.set_defaults(func=cmd_generate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (KeyError, ValueError, LLMError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
