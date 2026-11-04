"""Post-hoc validation of generated slides against the knowledge graph.

Every metric except ``editability`` is computed from the slide *text* rather
than from what the model reports about itself.  Two reasons, both learned the
hard way:

* a model that silently introduces an out-of-graph concept usually omits it
  from ``concept_ids``, so text scanning is what actually catches the drift;
* the unconstrained baselines are never told that ``concept_ids`` exists, so
  scoring self-reports would let a completely blank answer register as
  perfect compliance.

The same reasoning drives :data:`PREVIEW_LAYOUTS`: title, objectives and
summary pages name every concept at once, so they say nothing about what was
taught in what order.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from .constraints import UnitConstraints
from .graph import Graph

TEXT_FIELDS = ("title", "bullets")

# Preview layouts announce what is coming ("本讲学习目标：说出队列的 FIFO 特性……").
# They name every concept at once, so reading teaching order or coverage off
# them is meaningless: all positions tie, and it is the tie-break -- not the
# deck -- that decides who comes first.  Every condition produces all three
# pages, so excluding them is symmetric across the comparison.
PREVIEW_LAYOUTS = {"title", "objectives", "summary"}


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
        lines = ["| metric | value |", "| --- | --- |"]
        for key, value in self.metrics.items():
            lines.append(f"| {key} | {value:.3f} |")

        if self.uncovered:
            lines += ["", "**required concepts not covered**", ""]
            lines += [f"- {item}" for item in self.uncovered]
        if self.out_of_graph:
            lines += ["", "**out-of-graph or forbidden concepts**", ""]
            lines += [f"- {item}" for item in self.out_of_graph]
        if self.background_terms:
            lines += ["", "**concepts used as background review (allowed, but capped)**", ""]
            lines += [f"- {item}" for item in self.background_terms]
        if self.violated_pairs:
            lines += ["", "**prerequisite-order violations**", ""]
            lines += [
                f"- {a} appears after {b}, but {a} is a prerequisite of {b}"
                for a, b in self.violated_pairs
            ]

        if self.findings:
            lines += ["", "**findings**", ""]
            lines += [f"- `{f.level}` {f.code}: {f.message}" for f in self.findings]
        return "\n".join(lines)


def _net_occurrences(term: str, corpus: str, vocabulary: Iterable[str]) -> int:
    """Count occurrences of ``term`` that are not inside a longer known term.

    Chinese has no word boundaries, so "队列" would otherwise match inside
    "循环队列" and inflate the background-reference metric.  ASCII terms such as
    ``rear`` or ``BFS`` are compared case-insensitively, since slides freely
    write ``Rear`` or ``bfs``.
    """
    if not term:
        return 0
    if term.isascii():
        needle, haystack = term.lower(), corpus.lower()
        longer = [
            w.lower()
            for w in vocabulary
            if w and w.lower() != needle and needle in w.lower() and len(w) > len(term)
        ]
    else:
        needle, haystack = term, corpus
        longer = [w for w in vocabulary if w and w != term and term in w and len(w) > len(term)]

    raw = haystack.count(needle)
    if raw == 0:
        return 0
    # Subtract inside each line, not across the whole text.  A slide titled
    # "队列" and a later slide titled "顺序队列" are two independent mentions;
    # subtracting globally would let the second one cancel the first and report
    # the concept as never taught.
    total = 0
    for line in haystack.splitlines():
        hits = line.count(needle)
        if not hits:
            continue
        explained = sum(line.count(w) for w in longer)
        total += max(0, hits - explained)
    return total


def _surface_forms(node: dict[str, Any]) -> list[str]:
    """Every wording a concept may legitimately appear under.

    Matching on the canonical name alone is not a neutral measurement: the
    constrained condition is handed those exact strings and copies them,
    while an unconstrained model says "入队" where the graph says
    "入队与出队操作" and gets marked as having skipped the concept.  Aliases
    live in the graph, so all four conditions are scored against the same
    vocabulary.
    """
    forms = [node.get("name") or ""] + list(node.get("aliases") or [])
    return [form for form in forms if form]


def _present(forms: list[str], text: str, vocabulary: set[str]) -> bool:
    return any(_net_occurrences(form, text, vocabulary) > 0 for form in forms)


def _looks_like_graph_id(node_id: str) -> bool:
    """True for IDs drawn from the graph's own numbering scheme (C1005, U10)."""
    return bool(re.fullmatch(r"[A-Z]{1,3}\d{2,4}", node_id or ""))


def _bigrams(text: str) -> set[str]:
    cleaned = re.sub(r"\s+", "", text)
    return {cleaned[i : i + 2] for i in range(len(cleaned) - 1)}


def _identifier_tokens(text: str) -> set[str]:
    """English identifiers such as ``rear``, ``front``, ``list``."""
    return {t.lower() for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text)}


def _misconception_anchors(graph: Graph, mc_id: str) -> set[str]:
    """Concepts whose presence on a misconception page counts as coverage.

    Unit-level ``addresses_misconception`` edges are excluded on purpose.  They
    record *which unit owns* a misconception, not that every page of that unit
    addresses it; treating them as anchors made any misconception-styled page
    in the unit score as a hit, which silently zeroed out the ablation.
    """
    anchors: set[str] = set()
    for edge in graph.in_edges(mc_id, "addresses_misconception"):
        if not graph.exists(edge["source"]):
            continue
        if graph.node(edge["source"]).get("type") == "Unit":
            continue
        anchors.add(edge["source"])
    return anchors


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
    # A payload can arrive with a bare string where a slide object belongs; the
    # renderer turns it into a one-line page, and the scorer must read it the
    # same way rather than raising four frames deep in a generator expression.
    if not isinstance(slide, dict):
        slide = {"title": str(slide)}
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


def _content_slides(slides: list[dict[str, Any]]) -> list[tuple[int, dict[str, Any]]]:
    """Slides that actually teach, i.e. everything but title/objectives/summary."""
    picked = [
        (i, s) for i, s in enumerate(slides) if s.get("layout") not in PREVIEW_LAYOUTS
    ]
    return picked or list(enumerate(slides))


def _vocabulary(graph: Graph, constraints: UnitConstraints) -> set[str]:
    """Every term the text scanner knows about, for substring disambiguation.

    Built once and passed down: the order metric, the coverage metric and the
    background metric must agree on what counts as a longer term, otherwise
    "队列" is standalone in one metric and nested in another.
    """
    words = {n.get("name", "") for n in graph} | {
        n.get("statement", "") for n in graph.of_type("Misconception")
    }
    for node in graph:
        words |= set(node.get("aliases") or [])
    words |= set(constraints.siblings) | set(constraints.forbidden)
    return {word for word in words if len(word) >= 2}


def _mention_positions(
    concepts: list[dict[str, Any]],
    slides: list[dict[str, Any]],
    vocabulary: set[str],
) -> dict[str, tuple[int, int]]:
    """First ``(slide, offset)`` at which each concept is visibly mentioned.

    Order must be judged from where a concept appears, not from the order the
    model lists in ``concept_ids``: the unconstrained baselines are never told
    that field exists, so scoring self-reports would let an empty answer pass
    as "no violations".  Text positions are the only model-agnostic signal.

    Matching uses :func:`_net_occurrences` so that "队列" inside "循环队列" does
    not count as a mention of the shorter concept.  The character offset breaks
    ties inside one slide, which keeps two concepts introduced on the same page
    in the order the reader meets them instead of in dictionary order.

    """
    positions: dict[str, tuple[int, int]] = {}
    content = _content_slides(slides)
    texts = [(idx, _slide_text(slide)) for idx, slide in content]
    titles = [(idx, str(slide.get("title") or "")) for idx, slide in content]

    for node in concepts:
        forms = _surface_forms(node)
        if not forms:
            continue

        # Pass 1: the slide that *headlines* this concept.  A passing forward
        # reference in someone else's bullet ("... is the key to implementing
        # a circular queue") does not make that slide the place where the
        # concept is taught; the slide whose title names it does.
        for idx, title in titles:
            offsets = [
                title.find(form)
                for form in forms
                if _net_occurrences(form, title, vocabulary) > 0
            ]
            offsets = [offset for offset in offsets if offset >= 0]
            if offsets:
                positions[node["id"]] = (idx, min(offsets))
                break
        else:
            # Pass 2: never headlined, so fall back to the first body mention.
            for idx, text in texts:
                offsets = [
                    text.find(form)
                    for form in forms
                    if _net_occurrences(form, text, vocabulary) > 0
                ]
                offsets = [offset for offset in offsets if offset >= 0]
                if offsets:
                    positions[node["id"]] = (idx, min(offsets))
                    break

    # A concept whose wording differs from the graph but which the model did
    # declare still gets a position, so that omissions are not silently
    # rewarded either.
    in_scope = {c["id"] for c in concepts}
    for idx, slide in content:
        for cid in slide.get("concept_ids", []) or []:
            if cid in in_scope and cid not in positions:
                positions[cid] = (idx, 0)
    return positions


def evaluate(
    payload: dict[str, Any],
    constraints: UnitConstraints,
    graph: Graph,
    *,
    native_ratio: float = 1.0,
) -> Report:
    """Compute the five metrics and collect findings."""
    raw_slides = payload.get("slides", [])
    # Normalise once, here: a payload can arrive with a bare string where a
    # slide object belongs, and every downstream helper indexes into a mapping.
    # The renderer makes the same substitution, so the score describes the deck
    # that was actually written.
    slides: list[dict[str, Any]] = [
        s if isinstance(s, dict) else {"title": str(s)} for s in raw_slides
    ]
    report = Report()

    required = constraints.required
    required_ids = [c["id"] for c in required]
    allowed_ids = set(constraints.all_ids)

    # ---------------------------------------------------------- coverage
    corpus = "\n".join(_slide_text(s) for s in slides)
    # Coverage is judged on teaching slides only.  A concept that the model
    # merely lists on the outline or the summary page was named, not taught,
    # and must not be scored as covered.
    content_slides = [s for _, s in _content_slides(slides)]
    taught_corpus = "\n".join(_slide_text(s) for s in content_slides)

    # ------------------------------------------------------ out-of-graph
    vocabulary = _vocabulary(graph, constraints)

    # Coverage is judged on teaching slides only.  A concept that the model
    # merely lists on the outline or the summary page was named, not taught,
    # and must not be scored as covered.
    mentioned: set[str] = set()
    for slide in content_slides:
        mentioned.update(slide.get("concept_ids", []) or [])
    for node in required:
        if _present(_surface_forms(node), taught_corpus, vocabulary):
            mentioned.add(node["id"])

    covered = [cid for cid in required_ids if cid in mentioned]
    coverage = len(covered) / len(required_ids) if required_ids else 1.0
    report.uncovered = [
        f"{c['id']} {c['name']}" for c in required if c["id"] not in mentioned
    ]

    # 1) IDs reported by the model that use the graph's own numbering scheme but
    #    resolve to nothing -- a fabricated node reference.  Free-form slugs
    #    ("queue-def") are a different identifier space, not drift, so they are
    #    not penalised.
    declared_oog = {
        cid
        for slide in slides
        for cid in (slide.get("concept_ids", []) or [])
        if not graph.exists(cid) and _looks_like_graph_id(cid)
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
    # Order is read off the text, so the metric applies to every condition --
    # including the baselines that never emit `concept_ids`.
    positions = _mention_positions(required + constraints.optional, slides, vocabulary)
    sequence = [cid for cid, _ in sorted(positions.items(), key=lambda kv: kv[1])]
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
        anchors = _misconception_anchors(graph, mc["id"])
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
            Finding("error", "MISSING_CONCEPT", f"{len(report.uncovered)} required concepts not covered")
        )
    if oog_total:
        names = ", ".join(sorted(report.out_of_graph))
        report.findings.append(
            Finding("warning", "OUT_OF_GRAPH", f"out-of-graph or forbidden concepts present: {names}")
        )
    if background_rate > constraints.allowed_background_ratio:
        report.findings.append(
            Finding(
                "warning",
                "BACKGROUND_OVERUSE",
                f"background review is {background_rate:.0%} of the deck, above the "
                f"{constraints.allowed_background_ratio:.0%} cap",
            )
        )
    if violations:
        report.findings.append(
            Finding("error", "PREREQ_VIOLATION", f"{len(violations)} prerequisite-order inversions")
        )
    if mc_items and mc_coverage < 1.0:
        report.findings.append(
            Finding("warning", "MISCONCEPTION_MISS", "a required misconception was not addressed")
        )
    if abs(page_ratio - 1.0) > 0.34:
        report.findings.append(
            Finding(
                "warning",
                "PAGE_BUDGET",
                f"{len(slides)} slides generated against a budget of {constraints.slide_budget}",
            )
        )
    if not report.findings:
        report.findings.append(Finding("info", "OK", "all constraints satisfied"))
    return report
