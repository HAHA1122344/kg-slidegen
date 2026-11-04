#!/usr/bin/env python3
"""Are the graph's structural checks vacuous?

The shipped graph passes all ten checks with zero findings, which on its own
proves only that the checks did not complain -- not that they could.  A review
of an earlier draft made exactly this point ("the graph is a lookup table, not
a reasoning structure"): a knowledge base that is merely well-formed is not a
knowledge base anyone should rely on.

This script answers the objection by mutation.  For each of the twelve codes
the validator can emit, one minimal defect is injected into a copy of the
shipped graph, and we record whether the intended code fires and what else
goes off alongside it.  A check that never fires under a targeted defect is
decorative; a check that fires on everything is noise.

Usage
    python paper/graph_checks.py                # human-readable report
    python paper/graph_checks.py --latex        # LaTeX table for the paper
    python paper/graph_checks.py --csv out.csv
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kgslide.graph import Graph  # noqa: E402

KG_PATH = ROOT / "data" / "kg_pyds_m4.json"

# Codes grouped by the numbered check that emits them, in schema order.
CHECK_ORDER = [
    ("1", ["DANGLING_EDGE"]),
    ("2", ["PREREQ_CYCLE"]),
    ("3", ["NOT_GROUNDED"]),
    ("4", ["MISSING_EVIDENCE"]),
    ("5", ["UNIT_CAPACITY", "NO_CORE_CONCEPT"]),
    ("6", ["DUPLICATE_NAME"]),
    ("7", ["FORBIDDEN_REQUIRED_OVERLAP"]),
    ("8", ["FORBIDDEN_SIBLING_OVERLAP"]),
    ("9", ["ORPHAN_MISCONCEPTION"]),
    ("10", ["IMPLEMENTS_TARGET_TYPE", "IMPLEMENTS_SOURCE_UNGROUNDED"]),
]
CHECK_OF = {code: number for number, codes in CHECK_ORDER for code in codes}


# --------------------------------------------------------------- mutations
def _edge(raw: dict, edge_type: str, source: str, target: str, evidence: str = "mutant") -> None:
    raw["edges"].append(
        {"type": edge_type, "source": source, "target": target, "evidence": evidence}
    )


def _unit(raw: dict, unit_id: str) -> dict:
    for node in raw["nodes"]:
        if node["id"] == unit_id:
            return node
    raise KeyError(unit_id)


def m_dangling(raw: dict) -> str:
    _edge(raw, "relates_to", "C1001", "C9999")
    return "add relates_to edge to undefined node C9999"


def m_cycle(raw: dict) -> str:
    base = next(e for e in raw["edges"] if e["type"] == "prerequisites_for")
    _edge(raw, "prerequisites_for", base["target"], base["source"])
    return f"reverse prerequisites_for {base['source']}->{base['target']}"


def m_not_grounded(raw: dict) -> str:
    raw["nodes"].append(
        {
            "id": "C9001",
            "type": "Concept",
            "name": "orphan concept",
            "definition": "no session teaches this",
            "importance": "掌握",
        }
    )
    return "add Concept with no appears_in edge"


def m_missing_evidence(raw: dict) -> str:
    base = next(e for e in raw["edges"] if e["type"] == "is_a")
    base.pop("evidence", None)
    return f"strip evidence from is_a {base['source']}->{base['target']}"


def m_unit_capacity(raw: dict) -> str:
    for i in range(6):
        node_id = f"C910{i}"
        raw["nodes"].append(
            {
                "id": node_id,
                "type": "Concept",
                "name": f"filler concept {i}",
                "definition": "padding to overflow the unit",
                "importance": "了解",
            }
        )
        _edge(raw, "appears_in", node_id, "U12", evidence="mutant")
        raw["edges"][-1].pop("evidence")
    return "add 6 filler concepts to U12 (5 present, cap 8)"


def m_no_core(raw: dict) -> str:
    downgraded = []
    for node in raw["nodes"]:
        if node.get("importance") == "掌握":
            grounded = [
                e for e in raw["edges"] if e["source"] == node["id"] and e["type"] == "appears_in"
            ]
            if any(e["target"] == "U12" for e in grounded):
                node["importance"] = "理解"
                downgraded.append(node["id"])
    return f"downgrade the {len(downgraded)} mastery concepts of U12 ({downgraded[0]}...)"


def m_duplicate_name(raw: dict) -> str:
    for node in raw["nodes"]:
        if node["id"] == "C1204":
            node["name"] = "队列"
            return "rename C1204 to the name already used by C1001"
    raise KeyError("C1204")


def m_forbidden_required(raw: dict) -> str:
    _unit(raw, "U11")["forbidden_terms"].append("循环队列")
    return "forbid 'circular queue' in U11, where it is a core concept"


def m_forbidden_sibling(raw: dict) -> str:
    _unit(raw, "U11")["forbidden_terms"].append("假溢出")
    return "forbid 'false overflow' in U11, where it is a sibling recap term"


def m_orphan_misconception(raw: dict) -> str:
    raw["nodes"].append(
        {
            "id": "MC99",
            "type": "Misconception",
            "statement": "a queue is faster on a stack",
            "correction": "no session corrects this",
        }
    )
    _edge(raw, "appears_in", "MC99", "U12")
    return "add Misconception with no addresses_misconception in-edge"


def m_implements_target(raw: dict) -> str:
    _edge(raw, "implements", "C1101", "MC03")
    return "point implements at a Misconception node"


def m_implements_source(raw: dict) -> str:
    raw["nodes"].append(
        {
            "id": "S9999",
            "type": "Skill",
            "name": "未挂靠技能",
            "definition": "not taught in any session",
        }
    )
    _edge(raw, "implements", "S9999", "C1101")
    return "implements from a Skill with no appears_in edge"


MUTATIONS = [
    ("DANGLING_EDGE", m_dangling),
    ("PREREQ_CYCLE", m_cycle),
    ("NOT_GROUNDED", m_not_grounded),
    ("MISSING_EVIDENCE", m_missing_evidence),
    ("UNIT_CAPACITY", m_unit_capacity),
    ("NO_CORE_CONCEPT", m_no_core),
    ("DUPLICATE_NAME", m_duplicate_name),
    ("FORBIDDEN_REQUIRED_OVERLAP", m_forbidden_required),
    ("FORBIDDEN_SIBLING_OVERLAP", m_forbidden_sibling),
    ("ORPHAN_MISCONCEPTION", m_orphan_misconception),
    ("IMPLEMENTS_TARGET_TYPE", m_implements_target),
    ("IMPLEMENTS_SOURCE_UNGROUNDED", m_implements_source),
]


# ------------------------------------------------------------------- driver
def baseline(raw: dict) -> list[str]:
    return sorted({issue.code for issue in Graph.from_dict(raw).validate()})


def run() -> list[dict[str, object]]:
    raw = json.loads(KG_PATH.read_text(encoding="utf-8"))
    base = baseline(copy.deepcopy(raw))
    if base:
        raise SystemExit(
            "the shipped graph is not clean, so mutation results would be "
            "uninterpretable: " + ", ".join(base)
        )

    rows: list[dict[str, object]] = []
    for target, mutate in MUTATIONS:
        mutant = copy.deepcopy(raw)
        description = mutate(mutant)
        codes = baseline(mutant)
        rows.append(
            {
                "check": CHECK_OF[target],
                "target": target,
                "mutation": description,
                "fired": target in codes,
                "all_codes": codes,
                "collateral": [c for c in codes if c != target],
            }
        )
    return rows


def report(rows: list[dict[str, object]]) -> None:
    hits = sum(1 for r in rows if r["fired"])
    width = max(len(str(r["mutation"])) for r in rows)
    print(f"shipped graph: 0 findings on {len(CHECK_ORDER)} checks "
          f"({sum(len(c) for _, c in CHECK_ORDER)} codes)")
    print(f"mutants: {len(rows)}   target code fired: {hits}/{len(rows)}\n")
    print(f"{'chk':>3}  {'code':<30} {'fired':<6} {'+extra':<7} mutation")
    print("-" * (3 + 2 + 30 + 1 + 6 + 1 + 7 + 1 + width))
    for r in rows:
        extra = ",".join(r["collateral"]) or "-"
        print(
            f"{r['check']:>3}  {r['target']:<30} {'yes' if r['fired'] else 'NO':<6} "
            f"{extra:<7} {r['mutation']}"
        )
    missed = [r["target"] for r in rows if not r["fired"]]
    print()
    if missed:
        print("NOT DETECTED: " + ", ".join(missed))
    else:
        print("Every injected defect was caught by the check that owns it.")


def latex(rows: list[dict[str, object]]) -> None:
    print(r"\begin{table}[t]")
    print(r"\centering")
    print(
        r"\caption{Are the checks vacuous? Each of the twelve codes the validator"
        r" can emit is exercised by one minimal defect injected into a copy of the"
        r" shipped graph. ``Also fires'' lists codes that respond in addition to"
        r" the intended one; a check that failed to fire here would be"
        r" decorative.}"
    )
    print(r"\label{tab:graph-checks}")
    print(r"\footnotesize")
    print(r"\begin{tabularx}{\columnwidth}{@{}c l L{0.33\columnwidth} L{0.15\columnwidth}@{}}")
    print(r"\toprule")
    print(r"Chk & Code & Injected defect & Also fires \\")
    print(r"\midrule")
    for i, r in enumerate(rows):
        if i and r["check"] != rows[i - 1]["check"]:
            print(r"\addlinespace[1pt]")
        code = str(r["target"]).replace("_", r"\_")
        mutation = str(r["mutation"]).replace("_", r"\_").replace("%", r"\%")
        extra = ", ".join(r["collateral"]) or "--"
        extra = extra.replace("_", r"\_")
        print(f"{r['check']} & \\texttt{{{code}}} & {mutation} & {extra} \\\\")
    print(r"\bottomrule")
    print(r"\end{tabularx}")
    print(r"\end{table}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latex", action="store_true", help="emit LaTeX table")
    parser.add_argument("--csv", type=Path, help="write rows to CSV")
    args = parser.parse_args()

    rows = run()
    if args.latex:
        latex(rows)
    else:
        report(rows)
    if args.csv:
        with args.csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["check", "code", "mutation", "fired", "collateral"])
            for r in rows:
                writer.writerow(
                    [r["check"], r["target"], r["mutation"], r["fired"], ";".join(r["collateral"])]
                )
        print(f"\nwrote {args.csv}")


if __name__ == "__main__":
    main()
