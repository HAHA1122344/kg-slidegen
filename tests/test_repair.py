"""The repair loop's two moving parts: the feedback text and the re-prompt.

The loop itself costs model calls, so it is exercised here against the mock
provider: what is tested is that the instruction names the right thing and that
a repaired deck is scored by the same code path as a first attempt.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kgslide.constraints import build_constraints
from kgslide.graph import Graph
from kgslide.llm import LLMClient, LLMConfig
from kgslide.validator import evaluate, repair_instruction

KG_PATH = Path(__file__).resolve().parents[1] / "data" / "kg_pyds_m4.json"


@pytest.fixture(scope="module")
def graph() -> Graph:
    return Graph.load(KG_PATH)


def test_instruction_names_the_missing_concept(graph: Graph) -> None:
    """A finding has to be actionable: the id alone is not.

    "C1106 was not covered" sends the model looking for an id it may not have
    written down; the concept name is what lets it add a page.
    """
    constraints = build_constraints(graph, "U11")
    payload = {
        "unit_id": "U11",
        "slides": [
            {"layout": "concept", "title": "循环队列", "bullets": ["环形结构"], "concept_ids": []},
        ],
    }
    report = evaluate(payload, constraints, graph)
    text = repair_instruction(report, constraints)

    assert "C1106" in text
    assert "循环队列的实现" in text
    # The name must not be duplicated by looking it up a second time.
    assert text.count("C1106 循环队列的实现") == 1


def test_instruction_states_the_direction_of_an_inversion(graph: Graph) -> None:
    """Which of the two concepts is the prerequisite has to survive the wording.

    An instruction that says "C1105 and C1106 are in the wrong order" is a coin
    flip for the model; the sentence has to say that C1105 is the prerequisite.
    """
    constraints = build_constraints(graph, "U11")
    payload = {
        "unit_id": "U11",
        "slides": [
            {"layout": "concept", "title": "循环队列的实现", "bullets": ["代码"], "concept_ids": []},
            {"layout": "concept", "title": "队列长度计算", "bullets": ["取模"], "concept_ids": []},
        ],
    }
    report = evaluate(payload, constraints, graph)
    assert ("C1105", "C1106") in report.violated_pairs

    text = repair_instruction(report, constraints)
    line = next(l for l in text.splitlines() if "C1105" in l)
    assert "是 C1106" in line
    assert "先修" in line


def test_instruction_ignores_warnings(graph: Graph) -> None:
    """Warnings must not appear: repairing them would change the pass criterion.

    Out-of-graph content and a missed misconception are warnings by design, so a
    repair that answered them would be held to a stricter criterion than the
    first pass was scored against.
    """
    constraints = build_constraints(graph, "U11")
    payload = {
        "unit_id": "U11",
        "slides": [
            {"layout": "concept", "title": "循环队列", "bullets": ["环形"], "concept_ids": ["C1101"]},
            {"layout": "concept", "title": "取模运算", "bullets": ["% maxsize"], "concept_ids": ["C1102"]},
            {"layout": "concept", "title": "队空条件", "bullets": ["front == rear"], "concept_ids": ["C1103"]},
            {"layout": "concept", "title": "队满条件", "bullets": ["(rear+1) % n"], "concept_ids": ["C1104"]},
            {"layout": "concept", "title": "队列长度计算", "bullets": ["取模"], "concept_ids": ["C1105"]},
            {"layout": "concept", "title": "循环队列的实现", "bullets": ["代码"], "concept_ids": ["C1106"]},
            {"layout": "code", "title": "取模计算示例", "bullets": ["取模计算：(rear + 1) % maxsize"], "concept_ids": ["S1002"]},
        ],
    }
    report = evaluate(payload, constraints, graph)
    assert report.passed, "this deck is expected to clear the error-level bar"
    assert any(f.code == "MISCONCEPTION_MISS" for f in report.findings)

    text = repair_instruction(report, constraints)
    assert "没有 error 级问题" in text
    assert "误区" not in text


def test_mock_repair_returns_a_scoreable_deck(graph: Graph) -> None:
    constraints = build_constraints(graph, "U11")
    client = LLMClient(LLMConfig(provider="mock"), force_mock=True)
    payload = client.repair_slides(constraints, "full", "未覆盖的必讲概念：\n- C1106 循环队列的实现")
    report = evaluate(payload, constraints, graph)
    assert payload["slides"]
    assert 0.0 <= report.metrics["coverage_rate"] <= 1.0
