"""End-to-end tests using the offline mock provider."""

from __future__ import annotations

from pathlib import Path

import pytest

from kgslide.constraints import build_constraints
from kgslide.graph import Graph
from kgslide.llm import LLMClient, LLMConfig
from kgslide.renderer import render
from kgslide.validator import evaluate

KG_PATH = Path(__file__).resolve().parents[1] / "data" / "kg_pyds_m4.json"


@pytest.fixture(scope="module")
def graph() -> Graph:
    return Graph.load(KG_PATH)


@pytest.fixture(scope="module")
def mock_client() -> LLMClient:
    return LLMClient(LLMConfig(provider="mock"), force_mock=True)


def test_mock_payload_shape(graph: Graph, mock_client: LLMClient) -> None:
    constraints = build_constraints(graph, "U11")
    payload = mock_client.generate_slides(constraints)
    assert payload["unit_id"] == "U11"
    assert payload["slides"]
    for slide in payload["slides"]:
        assert "title" in slide and "layout" in slide
        assert isinstance(slide.get("bullets", []), list)


def test_render_produces_editable_pptx(graph: Graph, mock_client: LLMClient, tmp_path: Path) -> None:
    constraints = build_constraints(graph, "U11")
    payload = mock_client.generate_slides(constraints)
    out = tmp_path / "U11.pptx"
    result = render(payload, out, unit_name=constraints.unit_name)

    assert out.exists() and out.stat().st_size > 10_000
    assert result.slide_count == len(payload["slides"])
    assert result.native_ratio == 1.0


def test_metrics_within_range(graph: Graph, mock_client: LLMClient) -> None:
    constraints = build_constraints(graph, "U11")
    payload = mock_client.generate_slides(constraints)
    report = evaluate(payload, constraints, graph)

    metrics = report.metrics
    for key in ("coverage_rate", "oog_rate", "prerequisite_violation", "misconception_coverage"):
        assert 0.0 <= metrics[key] <= 1.0, key
    assert metrics["coverage_rate"] >= 0.9, "mock should cover nearly all required concepts"
    assert metrics["misconception_coverage"] == 1.0


def test_background_reference_is_tracked(graph: Graph, mock_client: LLMClient) -> None:
    """Recapping a sibling concept is allowed but must be measured."""
    constraints = build_constraints(graph, "U11")
    payload = mock_client.generate_slides(constraints)
    report = evaluate(payload, constraints, graph)
    assert report.background_terms, "definition text recaps sibling concepts"
    assert report.metrics["background_rate"] > 0


def test_prerequisite_violation_detected(graph: Graph) -> None:
    constraints = build_constraints(graph, "U11")
    payload = {
        "unit_id": "U11",
        "slides": [
            {
                "layout": "concept",
                "title": "判满",
                "bullets": ["队满条件"],
                "concept_ids": ["C1104"],
            },
            {
                "layout": "concept",
                "title": "循环队列",
                "bullets": ["循环队列定义"],
                "concept_ids": ["C1101"],
            },
        ],
    }
    report = evaluate(payload, constraints, graph)
    assert report.metrics["prerequisite_violation"] > 0
    assert report.violated_pairs


def test_missing_concept_flagged(graph: Graph) -> None:
    constraints = build_constraints(graph, "U11")
    payload = {
        "unit_id": "U11",
        "slides": [
            {"layout": "concept", "title": "循环队列", "bullets": ["定义"], "concept_ids": ["C1101"]}
        ],
    }
    report = evaluate(payload, constraints, graph)
    assert report.metrics["coverage_rate"] < 1.0
    assert report.uncovered
    assert not report.passed
