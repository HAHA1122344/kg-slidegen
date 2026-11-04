"""Close the acceptance loop: regenerate the runs that failed, and count again.

The paper reports a first-pass pass rate of 6/9 for the constrained condition,
and a third of its runs still need a human.  The obvious question is whether the
validator is only a scoreboard or can also drive a repair.  This script answers
it on the runs that already exist, so no new condition enters the comparison:

    python paper/repair_loop.py --source outputs/main_v1 --modes full

For every cell whose stored payload fails acceptance, the validator's
error-level findings are appended to the *same* condition prompt and the deck is
regenerated; the result is scored again, up to ``--rounds`` times.  A run that
passed first time is not touched, so the repaired rate has the same denominator
as the first-pass rate and the two are directly comparable.

Why this is run on ``full`` and not on the baselines.  The feedback names the
concepts a deck missed.  For ``full`` that list is already in the prompt: the
contract says which concepts must be covered, so the finding restates a
requirement rather than adding one.  For ``zero_shot`` or ``rag`` the same
sentence would hand over the syllabus those conditions were designed to lack,
and the repaired baseline would no longer be a baseline.  A repair loop is only
fair where the feedback does not exceed what the condition was given, and that
is a property of the condition, not of the loop.

Outputs go to ``outputs/repair``: one JSON, one deck and one report per attempt,
plus ``results.csv`` / ``results.md``.  Nothing under ``outputs/main_v1`` is
modified -- the first-pass table must stay exactly as it was scored.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kgslide.constraints import build_constraints  # noqa: E402
from kgslide.graph import Graph  # noqa: E402
from kgslide.llm import LLMClient, LLMConfig  # noqa: E402
from kgslide.renderer import render  # noqa: E402
from kgslide.validator import evaluate, repair_instruction  # noqa: E402

METRIC_KEYS = [
    "coverage_rate",
    "oog_rate",
    "background_rate",
    "prerequisite_violation",
    "misconception_coverage",
]


def _cells(source: Path, modes: list[str]) -> list[tuple[str, str, int, Path]]:
    cells = []
    for path in sorted(source.glob("*__r*.json")):
        unit, mode, rep = path.stem.split("__")
        if mode in modes:
            cells.append((unit, mode, int(rep[1:]), path))
    return cells


def _write_table(rows: list[dict], out: Path) -> str:
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with (out / "results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    lines = [
        "| unit | condition | rep | first pass | rounds used | final pass | "
        + " | ".join(METRIC_KEYS) + " |",
        "| --- | --- | --- | --- | --- | --- | " + " | ".join("---" for _ in METRIC_KEYS) + " |",
    ]
    for row in rows:
        cells = " | ".join(f"{row[k]:.3f}" for k in METRIC_KEYS)
        lines.append(
            f"| {row['unit']} | {row['mode']} | {row['rep']} | "
            f"{'yes' if row['first_pass'] else 'no'} | {row['rounds_used']} | "
            f"{'yes' if row['final_pass'] else 'no'} | {cells} |"
        )

    by_mode: dict[str, list[dict]] = {}
    for row in rows:
        by_mode.setdefault(row["mode"], []).append(row)
    summary = [
        "| condition | n | first-pass | after repair | runs repaired | "
        "mean coverage (first -> final) |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for mode, subset in by_mode.items():
        n = len(subset)
        first = sum(1 for r in subset if r["first_pass"])
        final = sum(1 for r in subset if r["final_pass"])
        repaired = sum(1 for r in subset if r["rounds_used"] > 0)
        cov_first = statistics.mean(
            r.get("coverage_first", r["coverage_rate"]) for r in subset
        )
        cov_final = statistics.mean(r["coverage_rate"] for r in subset)
        summary.append(
            f"| {mode} | {n} | {first}/{n} | {final}/{n} | {repaired} | "
            f"{cov_first:.3f} -> {cov_final:.3f} |"
        )

    text = "\n\n".join(
        [
            "# repair loop on the stored runs",
            "\n".join(summary),
            "## per-run detail",
            "\n".join(lines),
        ]
    )
    (out / "results.md").write_text(text + "\n", encoding="utf-8")
    return "\n".join(summary)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="repair_loop", description=__doc__)
    parser.add_argument("--source", default="outputs/main_v1")
    parser.add_argument("--out", default="outputs/repair")
    parser.add_argument("--modes", default="full")
    parser.add_argument("--kg", default="data/kg_pyds_m4.json")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--provider", default="deepseek")
    parser.add_argument("--model", default="")
    parser.add_argument("--temperature", type=float, default=0.3)
    parser.add_argument(
        "--max-calls",
        type=int,
        default=12,
        help="hard stop on model calls, so a loop with a bug cannot run up a bill",
    )
    parser.add_argument("--mock", action="store_true")
    args = parser.parse_args(argv)

    graph = Graph.load(Path(args.kg))
    source = Path(args.source)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    cells = _cells(source, modes)
    if not cells:
        print(f"no stored payloads for {modes} under {source}")
        return 1

    client = LLMClient(
        LLMConfig(
            provider="mock" if args.mock else args.provider,
            model=args.model,
            temperature=args.temperature,
        ),
        force_mock=args.mock,
    )

    calls = 0
    rows: list[dict] = []
    for unit, mode, rep, path in cells:
        constraints = build_constraints(graph, unit)
        payload = json.loads(path.read_text(encoding="utf-8"))
        report = evaluate(payload, constraints, graph)
        first_pass = report.passed
        coverage_first = report.metrics["coverage_rate"]
        rounds_used = 0
        print(
            f"[{unit}/{mode}#{rep}] first pass: {'yes' if first_pass else 'no'}"
            f"  {[f.code for f in report.findings if f.level == 'error']}",
            flush=True,
        )

        while not report.passed and rounds_used < args.rounds:
            if calls >= args.max_calls:
                print(f"  stopped at --max-calls {args.max_calls}", flush=True)
                break
            feedback = repair_instruction(report, constraints)
            rounds_used += 1
            calls += 1
            print(f"  round {rounds_used}: re-prompting", flush=True)
            try:
                payload = client.repair_slides(constraints, mode, feedback)
            except Exception as exc:  # noqa: BLE001 - a failed call is a result
                print(f"  !! {type(exc).__name__}: {str(exc)[:200]}", flush=True)
                rounds_used -= 1
                break

            stem = f"{unit}__{mode}__r{rep}__fix{rounds_used}"
            (out / f"{stem}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            rendered = render(payload, out / f"{stem}.pptx", unit_name=constraints.unit_name)
            report = evaluate(payload, constraints, graph, native_ratio=rendered.native_ratio)
            (out / f"{stem}.report.md").write_text(
                f"# {unit} / {mode} / r{rep} / repair round {rounds_used}\n\n"
                f"## feedback sent\n\n{feedback}\n\n## report\n\n{report.to_markdown()}\n",
                encoding="utf-8",
            )
            print(
                f"  -> {'pass' if report.passed else 'fail'} "
                f"coverage={report.metrics['coverage_rate']:.3f} "
                f"prereq={report.metrics['prerequisite_violation']:.3f}"
            )

        rows.append(
            {
                "unit": unit,
                "mode": mode,
                "rep": rep,
                "first_pass": first_pass,
                "final_pass": report.passed,
                "rounds_used": rounds_used,
                "coverage_first": coverage_first,
                **{k: report.metrics[k] for k in METRIC_KEYS},
                "latency_s": client.last_usage.get("latency_s", 0) if rounds_used else 0,
            }
        )

    print()
    print(_write_table(rows, out))
    print(f"\n{calls} model calls; wrote {out}/results.csv and results.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
