"""One regression test per row of the measurement-defect table (Table 9).

Section 6.1 of the manuscript lists seven defects we found in our own metrics,
each of which made the constrained condition win without cause.  Every one is
represented here by the deck that used to fool it, written against the shipped
graph so that the test fails if the graph data or the scorer drifts back.

The rows, in the order the table prints them:

  1  verbatim coverage matching       -> test_defect_1_alias_counts_as_coverage
  2  order scored from self-reports   -> test_defect_2_order_is_read_from_text
  3  preview slides counted as body   -> test_defect_3_outline_does_not_set_order
  4  forward reference as teaching    -> test_defect_4_forward_reference_is_not_a_position
  5  cross-slide subtraction          -> test_defect_5_compound_term_does_not_cancel
  6  misconception anchors too broad  -> test_defect_6_only_concept_anchors_count
  7  out-of-graph test too strict     -> test_defect_7_foreign_ids_are_not_drift

Each test states the number it used to produce.  Those numbers are the point:
the metrics kept emitting plausible values while measuring the wrong thing, so a
regression here would otherwise be invisible.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kgslide.constraints import build_constraints
from kgslide.graph import Graph
from kgslide.validator import _misconception_anchors, _net_occurrences, _vocabulary, evaluate

KG_PATH = Path(__file__).resolve().parents[1] / "data" / "kg_pyds_m4.json"


@pytest.fixture(scope="module")
def graph() -> Graph:
    return Graph.load(KG_PATH)


@pytest.fixture(scope="module")
def u10(graph: Graph):
    return build_constraints(graph, "U10")


@pytest.fixture(scope="module")
def u11(graph: Graph):
    return build_constraints(graph, "U11")


def test_defect_1_alias_counts_as_coverage(graph: Graph, u10) -> None:
    """Defect 1: matching the graph's exact wording, which only ``full`` copies.

    The graph calls the concept 入队与出队操作 and the deck says 入队与出队; a
    baseline paraphrases as 入队 / 出队.  Scored on the canonical name alone the
    deck is marked as having skipped a concept it taught on its own slide, and
    the gap lands entirely on the conditions that were not handed the wording.
    Was: coverage_rate 0.833, 入队与出队操作 listed as uncovered.
    """
    payload = {
        "unit_id": "U10",
        "slides": [
            {"layout": "title", "title": "队列", "bullets": ["队列"], "concept_ids": []},
            {"layout": "concept", "title": "队列", "bullets": ["先进先出"], "concept_ids": []},
            {
                "layout": "concept",
                "title": "队头与队尾",
                "bullets": ["front 指向队头，rear 指向队尾"],
                "concept_ids": [],
            },
            {"layout": "concept", "title": "顺序队列", "bullets": ["用连续单元存放"], "concept_ids": []},
            {
                "layout": "concept",
                "title": "入队与出队",
                "bullets": ["入队写入 rear，出队读取 front"],
                "concept_ids": [],
            },
            {"layout": "concept", "title": "假溢出", "bullets": ["rear 到末端"], "concept_ids": []},
            {
                "layout": "concept",
                "title": "用 Python 列表实现队列",
                "bullets": ["用下标前移代替 pop(0)"],
                "concept_ids": [],
            },
        ],
    }
    report = evaluate(payload, u10, graph)

    # The canonical string never appears; the aliases do.  Confirm that the
    # canonical string really is absent, so this test cannot pass by accident.
    corpus = "\n".join(
        f"{slide.get('title', '')} {' '.join(slide.get('bullets', []))}"
        for slide in payload["slides"]
    )
    assert "入队与出队操作" not in corpus
    assert "C1005" not in {item.split()[0] for item in report.uncovered}
    assert report.metrics["coverage_rate"] == 1.0


def test_defect_2_order_is_read_from_text(graph: Graph, u11) -> None:
    """Defect 2: trusting ``concept_ids``, which only the constrained arm emits.

    A baseline never fills the field, so the sequence was empty, no pair was
    compared, and the violation rate came out at a perfect 0.00 -- an unanswered
    script scoring full marks.  Order must be read off where concepts appear.
    Was: prerequisite_violation 0.000 on this deck.
    """
    payload = {
        "unit_id": "U11",
        "slides": [
            {"layout": "concept", "title": "队满条件", "bullets": ["(rear + 1) % maxsize == front"], "concept_ids": []},
            {"layout": "concept", "title": "循环队列", "bullets": ["用环形结构复用空间"], "concept_ids": []},
        ],
    }
    report = evaluate(payload, u11, graph)

    assert all(not slide["concept_ids"] for slide in payload["slides"])
    assert report.metrics["prerequisite_violation"] > 0.0
    assert ("C1101", "C1104") in report.violated_pairs


def test_defect_3_outline_does_not_set_order(graph: Graph, u11) -> None:
    """Defect 3: the outline names every concept, so it decided the sequence.

    The title page below lists the unit in reverse.  Read as teaching content it
    puts 队列长度计算 first and 循环队列 last, inventing inversions that the
    body slides do not contain.  Title, objectives and summary pages are now
    excluded from every position and from the coverage corpus.
    Was: prerequisite_violation 0.429 on this deck.
    """
    payload = {
        "unit_id": "U11",
        "slides": [
            {
                "layout": "title",
                "title": "本讲目录",
                "bullets": ["队列长度计算", "队满条件", "队空条件", "取模运算", "循环队列"],
                "concept_ids": [],
            },
            {"layout": "concept", "title": "循环队列", "bullets": ["用环形结构复用空间"], "concept_ids": []},
            {"layout": "concept", "title": "取模运算", "bullets": ["% maxsize 让下标回绕"], "concept_ids": []},
            {"layout": "concept", "title": "队空条件", "bullets": ["front == rear"], "concept_ids": []},
            {"layout": "concept", "title": "队满条件", "bullets": ["(rear + 1) % maxsize == front"], "concept_ids": []},
            {
                "layout": "concept",
                "title": "队列长度计算",
                "bullets": ["(rear - front + maxsize) % maxsize"],
                "concept_ids": [],
            },
        ],
    }
    report = evaluate(payload, u11, graph)

    assert report.violated_pairs == []
    assert report.metrics["prerequisite_violation"] == 0.0


def test_defect_4_forward_reference_is_not_a_position(graph: Graph, u11) -> None:
    """Defect 4: a passing mention counted as the place a concept is taught.

    Slide 1 says 队满条件 is what the rest of the session is about.  Taken as a
    position, that places 队满条件 before 取模运算 and 队空条件, which are its
    prerequisites, and reports two inversions of a deck that is in order.  The
    first pass now looks at slide titles, and only falls back to body mentions
    when no title names the concept.
    Was: prerequisite_violation 0.100 on this deck.
    """
    payload = {
        "unit_id": "U11",
        "slides": [
            {
                "layout": "concept",
                "title": "循环队列",
                "bullets": ["判断队满要用到取模，队满条件是本节后面再讲的重点"],
                "concept_ids": [],
            },
            {"layout": "concept", "title": "取模运算", "bullets": ["% maxsize 让下标回绕"], "concept_ids": []},
            {"layout": "concept", "title": "队空条件", "bullets": ["front == rear"], "concept_ids": []},
            {"layout": "concept", "title": "队满条件", "bullets": ["(rear + 1) % maxsize == front"], "concept_ids": []},
            {
                "layout": "concept",
                "title": "队列长度计算",
                "bullets": ["(rear - front + maxsize) % maxsize"],
                "concept_ids": [],
            },
        ],
    }
    report = evaluate(payload, u11, graph)

    assert report.violated_pairs == []


def test_defect_5_compound_term_does_not_cancel(graph: Graph, u11) -> None:
    """Defect 5: subtracting compound terms across the whole deck, not per line.

    队列 is taught on its own slide and appears again inside 队列长度计算.  The
    vocabulary knows both 队列长度计算 and 队列长度, so a global count finds two
    occurrences of 队列 and two longer terms to subtract and cancels to zero:
    the deck is scored as never teaching the concept it opens with.  The
    subtraction has to happen inside one line.
    Was: _net_occurrences("队列", ...) == 0.
    """
    vocabulary = _vocabulary(graph, u11)
    corpus = "队列\n队列长度计算"

    # The invariant, measured directly.
    assert _net_occurrences("队列", corpus, vocabulary) == 1

    # And the arithmetic that produced the defect, so the test says what it is
    # protecting against rather than only what it expects.
    raw = corpus.count("队列")
    longer = [w for w in vocabulary if w != "队列" and "队列" in w and len(w) > len("队列")]
    assert raw - sum(corpus.count(w) for w in longer) == 0, "the naive count still cancels"

    # End to end: the concept is covered because one slide is about it.  The
    # unit is U10, where 队列 is the concept itself rather than a substring of
    # one; the vocabulary is graph-wide, so 队列长度计算 is a longer term here
    # exactly as it is in U11.
    payload = {
        "unit_id": "U10",
        "slides": [
            {"layout": "concept", "title": "队列", "bullets": ["先进先出"], "concept_ids": []},
            {"layout": "concept", "title": "队列长度计算", "bullets": ["(rear - front + maxsize) % maxsize"], "concept_ids": []},
        ],
    }
    u10 = build_constraints(graph, "U10")
    assert "C1001" not in {item.split()[0] for item in evaluate(payload, u10, graph).uncovered}


def test_defect_6_only_concept_anchors_count(graph: Graph, u11) -> None:
    """Defect 6: unit-level ``addresses_misconception`` edges used as anchors.

    Every misconception the graph stores is also owned by a Unit, so treating
    those edges as anchors made any misconception-styled page in the unit count
    as having addressed the misconception -- which zeroed out the ablation and
    nearly made the paper's central claim false.  Only concept-level anchors
    count.
    Was: anchors for MC03 were {U11, C1104}, so any concept in U11 matched.
    """
    assert _misconception_anchors(graph, "MC03") == {"C1104"}

    # A misconception page about a different error, citing a concept that is not
    # an anchor and sharing no identifier with the statement.
    neighbour = {
        "unit_id": "U11",
        "slides": [
            {
                "layout": "misconception",
                "title": "常见错误：下标越界",
                "bullets": ["不会用取模就让下标越界了"],
                "concept_ids": ["C1105"],
            }
        ],
    }
    assert evaluate(neighbour, u11, graph).metrics["misconception_coverage"] == 0.0

    # The anchor itself does count, so the test cannot pass by refusing
    # everything.
    anchored = {
        "unit_id": "U11",
        "slides": [
            {
                "layout": "misconception",
                "title": "常见错误：判满",
                "bullets": ["判满条件是 (rear + 1) % maxsize == front"],
                "concept_ids": ["C1104"],
            }
        ],
    }
    assert evaluate(anchored, u11, graph).metrics["misconception_coverage"] == 1.0


def test_defect_7_foreign_ids_are_not_drift(graph: Graph, u11) -> None:
    """Defect 7: any unresolvable ``concept_ids`` entry counted as drift.

    Baselines invent their own slug scheme (``queue-def``) because nothing told
    them the graph has one; scoring those as out-of-graph reported 0.67 drift on
    decks that never left the syllabus.  Only ids written in the graph's own
    format can be fabricated references to it.
    Was: oog_rate 0.667 on the first deck below.
    """
    foreign = {
        "unit_id": "U11",
        "slides": [
            {
                "layout": "concept",
                "title": "循环队列",
                "bullets": ["用环形结构复用空间"],
                "concept_ids": ["queue-def", "queue-front"],
            }
        ],
    }
    first = evaluate(foreign, u11, graph)
    assert first.metrics["oog_rate"] == 0.0
    assert first.out_of_graph == []

    # A fabricated id in the graph's numbering scheme is still drift.
    fabricated = {
        "unit_id": "U11",
        "slides": [
            {
                "layout": "concept",
                "title": "循环队列",
                "bullets": ["用环形结构复用空间"],
                "concept_ids": ["C9999"],
            }
        ],
    }
    second = evaluate(fabricated, u11, graph)
    assert second.metrics["oog_rate"] > 0.0
    assert second.out_of_graph == ["C9999"]
