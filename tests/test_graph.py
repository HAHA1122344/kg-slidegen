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
