"""Syntactic validity of the code blocks the decks emit.

The paper reports that all 117 code blocks across the 54 main runs parse as
Python, in every condition, and that a syntax check therefore discriminates
nothing.  This script produces that number.

It deliberately checks syntax only.  Parsing is not running: a block can parse
and still implement the wrong wrap-around, and the paper says so.

Usage:
    python paper/code_check.py
"""

from __future__ import annotations

import ast
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "outputs" / "main_v1"


def blocks(payload: dict) -> list[str]:
    return [str(s.get("code") or "").strip() for s in payload.get("slides", []) if str(s.get("code") or "").strip()]


def main() -> None:
    per_condition: dict[str, list[tuple[int, int]]] = defaultdict(list)
    failures: list[tuple[str, int, str]] = []

    for path in sorted(MAIN.glob("*__*__r*.json")):
        unit, mode, rep = path.stem.split("__")
        found = blocks(json.loads(path.read_text(encoding="utf-8")))
        ok = 0
        for i, block in enumerate(found):
            try:
                ast.parse(block)
                ok += 1
            except SyntaxError as exc:
                failures.append((path.name, i, str(exc)))
        per_condition[mode].append((len(found), ok))

    print(f"{'condition':<11}{'decks':>6}{'blocks':>8}{'parse ok':>10}{'rate':>7}")
    total = ok_total = 0
    for mode in sorted(per_condition):
        rows = per_condition[mode]
        n = sum(b for b, _ in rows)
        ok = sum(o for _, o in rows)
        total += n
        ok_total += ok
        print(f"{mode:<11}{len(rows):>6}{n:>8}{ok:>10}{ok / n:>7.2f}")

    print(f"{'all':<11}{sum(len(v) for v in per_condition.values()):>6}"
          f"{total:>8}{ok_total:>10}{ok_total / total:>7.2f}")

    if failures:
        print("\nFailures:")
        for name, i, message in failures:
            print(f"  {name} block {i}: {message}")
    else:
        print("\nNo syntax failures: the check is saturated and cannot rank conditions.")


if __name__ == "__main__":
    main()
