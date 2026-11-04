"""Structural tests for the knowledge graph layer."""

from __future__ import annotations

from pathlib import Path

import pytest

from kgslide.constraints import build_constraints
from kgslide.graph import Graph

KG_PATH = Path(__file__).resolve().parents[1] / "data" / "kg_pyds_m4.json"


@pytest.fixture(scope="module")
def graph() -> Graph:
    return Graph.load(KG_PATH)


def test_graph_loads(graph: Graph) -> None:
    assert len(graph) > 20
    assert len(graph.of_type("Unit")) == 3
    assert len(graph.of_type("Misconception")) >= 3


def test_graph_is_structurally_valid(graph: Graph) -> None:
    errors = [issue for issue in graph.validate() if issue.level == "error"]
    assert errors == [], "\n".join(map(str, errors))


def test_no_prerequisite_cycle(graph: Graph) -> None:
    assert graph.find_cycles() == []


def test_unit_concepts_follow_declared_sequence(graph: Graph) -> None:
    concepts = graph.unit_concepts("U11", include_skills=False)
    ids = [c["id"] for c in concepts]
    assert ids == ["C1101", "C1102", "C1103", "C1104", "C1105", "C1106"]


def test_topological_order_respects_prerequisites(graph: Graph) -> None:
    constraints = build_constraints(graph, "U11")
    order = constraints.order
    position = {nid: i for i, nid in enumerate(order)}
    for src, dst in graph.prerequisite_pairs(constraints.all_ids):
        assert position[src] < position[dst], f"{src} must precede {dst}"


def test_constraints_split_by_importance(graph: Graph) -> None:
    constraints = build_constraints(graph, "U11")
    assert constraints.required, "U11 must have core concepts"
    assert all(c["importance"] in {"掌握", "熟练"} for c in constraints.required)
    assert all(c["importance"] in {"了解", "理解"} for c in constraints.optional)


def test_constraints_carry_misconception_and_evidence(graph: Graph) -> None:
    constraints = build_constraints(graph, "U11")
    assert any(mc["id"] == "MC03" for mc in constraints.misconceptions)
    assert constraints.evidence, "evidence anchors should not be empty"


def test_forbidden_list_excludes_own_concepts(graph: Graph) -> None:
    constraints = build_constraints(graph, "U11")
    own = {c["name"] for c in constraints.required + constraints.optional}
    assert not (own & set(constraints.forbidden))


def test_cycle_detection_actually_works(graph: Graph) -> None:
    graph.edges.append(
        {"type": "prerequisites_for", "source": "C1104", "target": "C1101", "evidence": "test"}
    )
    try:
        assert graph.find_cycles(), "injected cycle should be detected"
        with pytest.raises(ValueError):
            graph.topological_order(["C1101", "C1102", "C1103", "C1104"])
    finally:
        graph.edges.pop()


def test_prompt_block_contains_hard_constraints(graph: Graph) -> None:
    text = build_constraints(graph, "U11").to_prompt_block()
    assert "必须覆盖" in text
    assert "讲解顺序" in text
    assert "MC03" in text
    assert "可简要回顾" in text


# --------------------------------------------------------------- self-consistency
# The graph's own contract ingredients can contradict one another while the
# graph stays acyclic, grounded and evidenced.  These four checks are the
# answer to "the graph is a lookup table": each is exercised by a mutant so
# that a passing suite means the checks could have failed.


def _mutant(raw: dict) -> Graph:
    return Graph.from_dict(__import__("copy").deepcopy(raw))


@pytest.fixture(scope="module")
def raw() -> dict:
    import json

    return json.loads(KG_PATH.read_text(encoding="utf-8"))


def test_shipped_graph_is_clean(raw: dict) -> None:
    assert [i.code for i in Graph.from_dict(raw).validate()] == []


def test_forbidden_may_not_be_required(raw: dict) -> None:
    mutant = _mutant(raw)
    for node in mutant.nodes.values():
        if node["id"] == "U11":
            node["forbidden_terms"] = list(node["forbidden_terms"]) + ["循环队列"]
    codes = {i.code for i in mutant.validate()}
    assert "FORBIDDEN_REQUIRED_OVERLAP" in codes


def test_forbidden_may_not_be_sibling_recap(raw: dict) -> None:
    mutant = _mutant(raw)
    for node in mutant.nodes.values():
        if node["id"] == "U11":
            node["forbidden_terms"] = list(node["forbidden_terms"]) + ["假溢出"]
    codes = {i.code for i in mutant.validate()}
    assert "FORBIDDEN_SIBLING_OVERLAP" in codes
    assert "FORBIDDEN_REQUIRED_OVERLAP" not in codes, "this term is not core to U11"


def test_orphan_misconception_is_flagged(raw: dict) -> None:
    mutant = _mutant(raw)
    mutant.nodes["MC99"] = {
        "id": "MC99",
        "type": "Misconception",
        "statement": "队列用栈实现更快",
        "correction": "nothing corrects this",
    }
    mutant.edges.append({"type": "appears_in", "source": "MC99", "target": "U12"})
    codes = {i.code for i in mutant.validate()}
    assert "ORPHAN_MISCONCEPTION" in codes


def test_implements_must_point_at_an_artefact(raw: dict) -> None:
    mutant = _mutant(raw)
    mutant.edges.append(
        {"type": "implements", "source": "C1101", "target": "MC03", "evidence": "test"}
    )
    codes = {i.code for i in mutant.validate()}
    assert "IMPLEMENTS_TARGET_TYPE" in codes

