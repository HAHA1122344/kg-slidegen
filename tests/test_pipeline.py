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


def test_overview_pages_do_not_decide_order(graph: Graph) -> None:
    """A title page that lists every concept must not create violations.

    Outlines name the whole concept list on one slide, so all first-mention
    positions tie and the tie-break -- not the deck -- would pick a winner.
    """
    constraints = build_constraints(graph, "U10")
    payload = {
        "unit_id": "U10",
        "slides": [
            {
                "layout": "title",
                "title": "队列的概念与假溢出",
                "bullets": [
                    "队列", "队头与队尾", "顺序队列", "入队与出队操作", "假溢出",
                    "用 Python 列表实现队列",
                ],
            },
            {
                "layout": "concept",
                "title": "队列",
                "bullets": ["一端插入、另一端删除的线性表"],
            },
            {
                "layout": "concept",
                "title": "队头与队尾",
                "bullets": ["front 指示队头，rear 指示队尾"],
            },
            {
                "layout": "concept",
                "title": "顺序队列",
                "bullets": ["用一段连续单元存放元素"],
            },
            {
                "layout": "concept",
                "title": "入队与出队操作",
                "bullets": ["先判满再写入，先判空再取出"],
            },
            {
                "layout": "concept",
                "title": "假溢出",
                "bullets": ["rear 到末端而后端仍有空位"],
            },
            {
                "layout": "concept",
                "title": "用 Python 列表实现队列",
                "bullets": ["用 front 下标避免 pop(0)"],
            },
            {"layout": "summary", "title": "小结", "bullets": ["回顾本讲要点"]},
        ],
    }
    report = evaluate(payload, constraints, graph)
    assert report.metrics["prerequisite_violation"] == 0.0, report.violated_pairs
    assert report.metrics["coverage_rate"] == 1.0


def test_outline_only_mention_is_not_coverage(graph: Graph) -> None:
    """Naming a concept on the summary page is not teaching it."""
    constraints = build_constraints(graph, "U11")
    payload = {
        "unit_id": "U11",
        "slides": [
            {
                "layout": "title",
                "title": "循环队列",
                "bullets": ["循环队列", "取模运算", "循环队列的实现"],
            },
            {
                "layout": "concept",
                "title": "循环队列",
                "bullets": ["用取模复用空间"],
            },
            {"layout": "summary", "title": "小结", "bullets": ["循环队列的实现", "队空条件"]},
        ],
    }
    report = evaluate(payload, constraints, graph)
    uncovered_ids = {item.split()[0] for item in report.uncovered}
    assert "C1106" in uncovered_ids, "循环队列的实现 只出现在概览页，不应算作已覆盖"
    assert "C1101" not in uncovered_ids, "循环队列 在正文页讲过，应算覆盖"


def test_objectives_page_is_not_a_teaching_slide(graph: Graph) -> None:
    """The objectives page lists every goal, so it must not set the order.

    Observed on a real baseline deck: a five-page U10 deck looked clean, but
    the objectives page named 顺序队列 and 假溢出 before 队头与队尾 had been
    taught, which the order metric reported as two prerequisite inversions.
    The inversions were real *in the page sequence* but not in the teaching
    sequence, because nothing is taught on that page.
    """
    constraints = build_constraints(graph, "U10")
    payload = {
        "unit_id": "U10",
        "slides": [
            {"layout": "title", "title": "队列的概念与假溢出", "bullets": ["第 10 讲"]},
            {
                "layout": "objectives",
                "title": "本讲学习目标",
                "bullets": [
                    "说出队列的 FIFO 特性",
                    "用列表实现顺序队列的入队与出队",
                    "解释假溢出的成因",
                ],
            },
            {
                "layout": "concept",
                "title": "队列：先进先出的受限线性表",
                "bullets": ["只允许在队尾 rear 插入", "只允许在队头 front 删除"],
            },
            {
                "layout": "concept",
                "title": "顺序队列",
                "bullets": ["用固定长度列表加 front、rear 两个指针"],
            },
            {
                "layout": "concept",
                "title": "入队与出队操作",
                "bullets": ["入队 data[rear] = x；出队取 data[front]"],
            },
            {
                "layout": "concept",
                "title": "假溢出",
                "bullets": ["rear 到底而前端空位废弃"],
            },
            {
                "layout": "concept",
                "title": "用 Python 列表实现队列",
                "bullets": ["用 front 下标避免 pop(0)"],
            },
            {"layout": "summary", "title": "小结", "bullets": ["回顾"]},
        ],
    }
    report = evaluate(payload, constraints, graph)
    assert report.metrics["prerequisite_violation"] == 0.0, report.violated_pairs


def test_forward_reference_does_not_move_a_concept(graph: Graph) -> None:
    """A passing mention in someone else's bullet is not where it is taught.

    Real case: a U11 deck said "取模是循环队列实现的关键" inside the 取模 slide.
    Counting that as the position of 循环队列的实现 placed it three slides early
    and manufactured two prerequisite inversions that did not exist.
    """
    from kgslide.validator import _mention_positions, _vocabulary

    constraints = build_constraints(graph, "U11")
    slides = [
        {
            "layout": "concept",
            "title": "取模运算：指针回绕的数学表达",
            "bullets": ["取模是循环队列实现的关键", "(rear + 1) % maxsize"],
        },
        {
            "layout": "concept",
            "title": "循环队列的实现与取模计算",
            "bullets": ["维护 front、rear、maxsize 三个变量"],
        },
    ]
    positions = _mention_positions(
        constraints.required + constraints.optional,
        slides,
        _vocabulary(graph, constraints),
    )
    assert positions["C1106"][0] == 1, "循环队列的实现 应定位在标题点名的第 2 页"
    assert positions["C1102"][0] == 0


def test_unrelated_misconception_page_is_not_a_hit(graph: Graph) -> None:
    """A misconception-styled page about another topic must not count.

    Real case: a U12 deck put 链队列的队空判断 on a `misconception` slide.  Because
    a data edge wrongly connected that concept to the BFS/stack misconception,
    the structural rule scored it as covered and the ablation lost its effect.
    """
    from kgslide.validator import _misconception_anchors

    anchors = _misconception_anchors(graph, "MC13")
    assert "C1202" not in anchors, "队空判断 与「BFS 用栈」这条误区无教学关系"
    assert "U12" not in anchors, "讲次级 addresses_misconception 不能当作页面锚点"

    constraints = build_constraints(graph, "U12")
    payload = {
        "unit_id": "U12",
        "slides": [
            {
                "layout": "misconception",
                "title": "队空判断：front 与 rear 同指头结点",
                "bullets": ["链队列队空：front 与 rear 同时指向头结点"],
                "concept_ids": ["C1202"],
            },
            {
                "layout": "concept",
                "title": "链队列",
                "bullets": ["头出尾入，均 O(1)"],
                "concept_ids": ["C1201"],
            },
        ],
    }
    report = evaluate(payload, constraints, graph)
    assert report.metrics["misconception_coverage"] == 0.0


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


def test_prerequisite_order_is_judged_from_text(graph: Graph) -> None:
    """Order must not depend on self-reported ``concept_ids``.

    The unconstrained baselines are never told that field exists, so a payload
    with no ``concept_ids`` at all used to score a perfect 0.0 violation rate.
    Text positions have to carry the metric on their own.
    """
    constraints = build_constraints(graph, "U11")
    payload = {
        "unit_id": "U11",
        "slides": [
            {"layout": "concept", "title": "队满条件", "bullets": ["(rear + 1) % maxsize == front"]},
            {"layout": "concept", "title": "循环队列", "bullets": ["用取模复用空间"]},
        ],
    }
    report = evaluate(payload, constraints, graph)
    assert not any(s.get("concept_ids") for s in payload["slides"])
    assert report.metrics["prerequisite_violation"] > 0, (
        "队满条件 出现在 循环队列 之前，属先修倒置，应被发现"
    )


def test_ablation_prompt_drops_exactly_one_block(graph: Graph) -> None:
    """Each ablation must remove its own block and nothing else."""
    from kgslide.llm import _build_prompt

    constraints = build_constraints(graph, "U11")
    full = _build_prompt(constraints, "full")
    assert "讲解顺序" in full and "必须纠正的典型误区" in full and "严禁引入" in full

    no_order = _build_prompt(constraints, "no_order")
    assert "讲解顺序" not in no_order
    assert "必须纠正的典型误区" in no_order and "严禁引入" in no_order

    no_mc = _build_prompt(constraints, "no_misconception")
    assert "必须纠正的典型误区" not in no_mc
    assert "讲解顺序" in no_mc and "严禁引入" in no_mc

    no_forbidden = _build_prompt(constraints, "no_forbidden")
    assert "严禁引入" not in no_forbidden
    assert "讲解顺序" in no_forbidden and "必须纠正的典型误区" in no_forbidden


def test_forbidden_terms_are_out_of_graph_only(graph: Graph) -> None:
    """A term cannot be both a reviewer-allowed recap and a forbidden concept.

    ``forbidden`` feeds the out-of-graph metric while ``siblings`` feeds the
    background-recap metric; overlapping them would count one mention twice and
    make the two metrics contradict each other.
    """
    names = {node.get("name") for node in graph if node.get("name")}
    for unit in ("U10", "U11", "U12"):
        constraints = build_constraints(graph, unit)
        assert not set(constraints.forbidden) & set(constraints.siblings), unit
        for term in constraints.forbidden:
            assert term not in names, f"{term} 在图谱内，应走 siblings 而非 forbidden"
