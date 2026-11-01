"""Post-hoc validation of generated slides against the knowledge graph.

Three of the five metrics are computed at the *text* level rather than trusting
the model's self-reported ``concept_ids``.  A model that silently introduces an
out-of-graph concept usually omits it from ``concept_ids``, so text scanning is
what actually catches the violation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from .constraints import UnitConstraints
from .graph import Graph

TEXT_FIELDS = ("title", "bullets")


@dataclass
class Finding:
    level: str  # "error" | "warning" | "info"
    code: str
    message: str


@dataclass
class Report:
    metrics: dict[str, float] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    uncovered: list[str] = field(default_factory=list)
    out_of_graph: list[str] = field(default_factory=list)
    background_terms: list[str] = field(default_factory=list)
    violated_pairs: list[tuple[str, str]] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not any(f.level == "error" for f in self.findings)

    def to_markdown(self) -> str:
        lines = ["| 指标 | 值 |", "| --- | --- |"]
        for key, value in self.metrics.items():
            lines.append(f"| {key} | {value:.3f} |")

        if self.uncovered:
            lines += ["", "**未覆盖的必需概念**", ""]
            lines += [f"- {item}" for item in self.uncovered]
        if self.out_of_graph:
            lines += ["", "**图谱外或禁用概念**", ""]
            lines += [f"- {item}" for item in self.out_of_graph]
        if self.background_terms:
            lines += ["", "**作为背景回顾的概念（允许但有比例上限）**", ""]
            lines += [f"- {item}" for item in self.background_terms]
        if self.violated_pairs:
            lines += ["", "**先修顺序违例**", ""]
            lines += [f"- {a} 出现在 {b} 之后，但 {a} 是 {b} 的先修" for a, b in self.violated_pairs]

        if self.findings:
            lines += ["", "**检查结果**", ""]
            lines += [f"- `{f.level}` {f.code}: {f.message}" for f in self.findings]
        return "\n".join(lines)


def _net_occurrences(term: str, corpus: str, vocabulary: Iterable[str]) -> int:
    """Count occurrences of ``term`` that are not inside a longer known term.

    Chinese has no word boundaries, so "队列" would otherwise match inside
    "循环队列" and inflate the background-reference metric.
    """
    raw = corpus.count(term)
    if raw == 0:
        return 0
    longer = [w for w in vocabulary if w != term and term in w and len(w) > len(term)]
    consumed = sum(corpus.count(w) for w in longer)
    return max(0, raw - consumed)


def _bigrams(text: str) -> set[str]:
    cleaned = re.sub(r"\s+", "", text)
    return {cleaned[i : i + 2] for i in range(len(cleaned) - 1)}


def _identifier_tokens(text: str) -> set[str]:
    """English identifiers such as ``rear``, ``front``, ``list``."""
    return {t.lower() for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text)}


def _covers_misconception(
    mc: dict[str, Any],
    slides: list[dict[str, Any]],
    anchors: set[str],
) -> bool:
    """Decide whether a misconception was actually addressed.

    Literal matching is too brittle: a model may write "rear == front 表示队满"
    where the graph stores "循环队列判满的条件是 rear == front".  Three signals
    are combined, in decreasing order of reliability:

    1. structural -- a misconception slide cites a concept the graph links to
       this misconception;
    2. identifier overlap -- a misconception slide shares an English identifier
       (``rear``, ``list``) with the statement;
    3. character bigram overlap -- fuzzy Chinese matching without a tokenizer.
    """
    statement = mc.get("statement", "")
    statement_ids = _identifier_tokens(statement)
    statement_bigrams = _bigrams(statement)

    for slide in slides:
        ids = set(slide.get("concept_ids") or [])
        text = _slide_text(slide)
        is_mc_slide = slide.get("layout") == "misconception"

        if statement and statement in text:
            return True
        if is_mc_slide and (mc["id"] in ids or ids & anchors):
            return True
        if is_mc_slide:
            shared = statement_ids & _identifier_tokens(text)
            if shared:
                return True
            if statement_bigrams:
                overlap = len(statement_bigrams & _bigrams(text)) / len(statement_bigrams)
                if overlap >= 0.35:
                    return True
        elif statement_bigrams:
            # A non-misconception slide can still correct the error inline.
            overlap = len(statement_bigrams & _bigrams(text)) / len(statement_bigrams)
            if overlap >= 0.6:
                return True
    return False


def _slide_text(slide: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in TEXT_FIELDS:
        value = slide.get(key, "")
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
        else:
            parts.append(str(value))
    return " \n".join(parts)


def _reachable(graph: Graph, start: str, goal: str, max_depth: int = 32) -> bool:
    """True if ``goal`` is reachable from ``start`` along prerequisites_for."""
    stack, visited = [start], {start}
    depth = 0
    while stack and depth < max_depth:
        nxt: list[str] = []
        for current in stack:
            for target in graph.targets(current, "prerequisites_for"):
                if target == goal:
                    return True
                if target not in visited:
                    visited.add(target)
                    nxt.append(target)
        stack, depth = nxt, depth + 1
    return False


def _flatten_sequence(slides: Iterable[dict[str, Any]]) -> list[str]:
    sequence: list[str] = []
    for slide in slides:
        for cid in slide.get("concept_ids", []) or []:
            if cid not in sequence:
                sequence.append(cid)
    return sequence


def evaluate(
    payload: dict[str, Any],
    constraints: UnitConstraints,
    graph: Graph,
    *,
    native_ratio: float = 1.0,
) -> Report:
    """Compute the five metrics and collect findings."""
    slides: list[dict[str, Any]] = payload.get("slides", [])
    report = Report()

    required = constraints.required
    required_ids = [c["id"] for c in required]
    allowed_ids = set(constraints.all_ids)

    # ---------------------------------------------------------- coverage
    corpus = "\n".join(_slide_text(s) for s in slides)
    mentioned: set[str] = set()
    for slide in slides:
        mentioned.update(slide.get("concept_ids", []) or [])
    for node in required:
        if node.get("name") and node["name"] in corpus:
            mentioned.add(node["id"])

    covered = [cid for cid in required_ids if cid in mentioned]
    coverage = len(covered) / len(required_ids) if required_ids else 1.0
    report.uncovered = [
        f"{c['id']} {c['name']}" for c in required if c["id"] not in mentioned
    ]

    # ------------------------------------------------------ out-of-graph
    vocabulary = {n.get("name", "") for n in graph} | {
        n.get("statement", "") for n in graph.of_type("Misconception")
    }
    vocabulary |= set(constraints.siblings) | set(constraints.forbidden)
    vocabulary = {word for word in vocabulary if len(word) >= 2}

    # 1) IDs reported by the model that do not exist in the graph at all.
    declared_oog = {
        cid
        for slide in slides
        for cid in (slide.get("concept_ids", []) or [])
        if not graph.exists(cid)
    }
    # 2) Explicitly forbidden terms used in prose.
    forbidden_hits = {
        term
        for term in constraints.forbidden
        if len(term) >= 2 and _net_occurrences(term, corpus, vocabulary) > 0
    }
    # 3) Sibling concepts used as recap, measured as a share of characters.
    #    Counting concepts is too coarse: a one-line comparison table legitimately
    #    names three siblings without re-teaching any of them.
    background_terms = {
        term
        for term in constraints.siblings
        if len(term) >= 2 and _net_occurrences(term, corpus, vocabulary) > 0
    }
    cleaned = re.sub(r"\s+", "", corpus)
    total_chars = max(len(cleaned), 1)
    background_chars = sum(
        _net_occurrences(term, corpus, vocabulary) * len(term) for term in background_terms
    )

    oog_total = len(declared_oog) + len(forbidden_hits)
    mention_total = len(covered) + oog_total
    oog_rate = oog_total / mention_total if mention_total else 0.0
    background_rate = min(background_chars / total_chars, 1.0)

    report.out_of_graph = sorted(declared_oog | forbidden_hits)
    report.background_terms = sorted(background_terms)

    # ------------------------------------------------- prerequisite order
    sequence = _flatten_sequence(slides)
    pairs = 0
    violations: list[tuple[str, str]] = []
    for i in range(len(sequence)):
        for j in range(i + 1, len(sequence)):
            pairs += 1
            later, earlier = sequence[j], sequence[i]
            if _reachable(graph, later, earlier):
                violations.append((later, earlier))
    violation_rate = len(violations) / pairs if pairs else 0.0
    report.violated_pairs = violations

    # --------------------------------------------------- misconception
    mc_items = constraints.misconceptions
    hit = 0
    for mc in mc_items:
        anchors = {e["source"] for e in graph.in_edges(mc["id"], "addresses_misconception")}
        if _covers_misconception(mc, slides, anchors):
            hit += 1
    mc_coverage = hit / len(mc_items) if mc_items else 1.0

    # ------------------------------------------------------------ ratios
    page_ratio = len(slides) / constraints.slide_budget if constraints.slide_budget else 1.0

    report.metrics = {
        "coverage_rate": round(coverage, 4),
        "oog_rate": round(oog_rate, 4),
        "background_rate": round(background_rate, 4),
        "prerequisite_violation": round(violation_rate, 4),
        "misconception_coverage": round(mc_coverage, 4),
        "editability": round(native_ratio, 4),
        "page_budget_ratio": round(page_ratio, 4),
    }

    # ----------------------------------------------------------- findings
    if report.uncovered:
        report.findings.append(
            Finding("error", "MISSING_CONCEPT", f"{len(report.uncovered)} 个必需概念未覆盖")
        )
    if oog_total:
        names = "、".join(sorted(report.out_of_graph))
        report.findings.append(
            Finding("warning", "OUT_OF_GRAPH", f"出现图谱外或禁用概念：{names}")
        )
    if background_rate > constraints.allowed_background_ratio:
        report.findings.append(
            Finding(
                "warning",
                "BACKGROUND_OVERUSE",
                f"背景回顾占比 {background_rate:.0%}，超过上限 "
                f"{constraints.allowed_background_ratio:.0%}",
            )
        )
    if violations:
        report.findings.append(
            Finding("error", "PREREQ_VIOLATION", f"{len(violations)} 处先修顺序倒置")
        )
    if mc_items and mc_coverage < 1.0:
        report.findings.append(
            Finding("warning", "MISCONCEPTION_MISS", "存在未处理的典型误区")
        )
    if abs(page_ratio - 1.0) > 0.34:
        report.findings.append(
            Finding(
                "warning",
                "PAGE_BUDGET",
                f"生成 {len(slides)} 页，预算 {constraints.slide_budget} 页",
            )
        )
    if not report.findings:
        report.findings.append(Finding("info", "OK", "全部约束满足"))
    return report
