"""Translate a Unit subgraph into an explicit generation contract.

The contract is the interface between the knowledge graph and the language
model: it states what must be covered, in what order, what must be corrected,
and what is forbidden.  Keeping it as data (not prompt prose) lets the same
object drive both generation and post-hoc validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .graph import IMPORTANCE_RANK, Graph

CORE_LEVEL = 2  # 掌握 and above


def _normalize(node: dict[str, Any]) -> dict[str, Any]:
    """Give every knowledge point a ``definition`` field.

    Skills and Labs carry ``description`` / ``objective`` instead, and the prompt
    builder should not have to branch on node type.
    """
    normalized = dict(node)
    if not normalized.get("definition"):
        normalized["definition"] = (
            normalized.get("description") or normalized.get("objective") or ""
        )
    return normalized


@dataclass
class UnitConstraints:
    """Hard constraints for generating the slides of one Unit."""

    unit_id: str
    unit_name: str
    objective: str
    slide_budget: int
    course_name: str = ""
    # Programming language of the course, so the output contract asks for the
    # right kind of code block.  A second course in another language would
    # otherwise be silently asked for Python.
    language: str = "Python"
    unit_order: int = 0
    required: list[dict[str, Any]] = field(default_factory=list)
    optional: list[dict[str, Any]] = field(default_factory=list)
    order: list[str] = field(default_factory=list)
    misconceptions: list[dict[str, Any]] = field(default_factory=list)
    lab: dict[str, Any] | None = None
    evidence: dict[str, str] = field(default_factory=dict)
    # Concepts from sibling units in the same module: allowed as a brief recap,
    # but they must not be re-taught.  Tracked as ``background_rate``.
    siblings: list[str] = field(default_factory=list)
    # Terms that must never appear (out-of-scope for this course).
    forbidden: list[str] = field(default_factory=list)
    allowed_background_ratio: float = 0.25

    # ------------------------------------------------------------- helpers
    @property
    def required_ids(self) -> list[str]:
        return [c["id"] for c in self.required]

    @property
    def all_ids(self) -> list[str]:
        return [c["id"] for c in self.required + self.optional]

    def name_of(self, node_id: str) -> str:
        for node in self.required + self.optional:
            if node["id"] == node_id:
                return node.get("name", node_id)
        return node_id

    # -------------------------------------------------------------- prompt
    def to_prompt_block(
        self,
        *,
        include_order: bool = True,
        include_misconceptions: bool = True,
        include_forbidden: bool = True,
        include_siblings: bool = True,
    ) -> str:
        """Render the contract as a deterministic prompt fragment.

        The flags exist for the ablation study: dropping exactly one block lets
        a metric be attributed to a specific part of the graph instead of to
        "the prompt" as a whole.
        """
        lines: list[str] = []
        lines.append(f"## 讲次\n{self.unit_id} {self.unit_name}（{self.slide_budget} 页）")
        lines.append(f"\n## 教学目标\n{self.objective}")

        lines.append("\n## 必须覆盖的概念（缺一不可）")
        for concept in self.required:
            complexity = f"，复杂度 {concept['complexity']}" if concept.get("complexity") else ""
            lines.append(
                f"- {concept['id']} {concept['name']}（{concept['importance']}{complexity}）："
                f"{concept['definition']}"
            )

        if self.optional:
            lines.append("\n## 可选补充概念（按页数余量选用）")
            for concept in self.optional:
                lines.append(f"- {concept['id']} {concept['name']}（{concept['importance']}）")

        if include_order:
            lines.append("\n## 讲解顺序（必须遵守，这是先修关系决定的拓扑序）")
            lines.append(" → ".join(f"{nid} {self.name_of(nid)}" for nid in self.order))

        if include_misconceptions and self.misconceptions:
            lines.append("\n## 必须纠正的典型误区")
            for mc in self.misconceptions:
                lines.append(f"- {mc['id']} 错误说法：{mc['statement']}")
                lines.append(f"  正确理解：{mc['correction']}")

        if self.lab:
            lines.append(f"\n## 配套上机实验\n{self.lab['name']}：{self.lab['objective']}")

        if self.evidence:
            lines.append("\n## 证据锚点（便于教师核对，非生成内容）")
            for node_id, text in self.evidence.items():
                lines.append(f"- {node_id}: {text}")

        if include_siblings and self.siblings:
            preview = "、".join(self.siblings)
            lines.append(
                f"\n## 可简要回顾、但不要展开的先前概念\n{preview}"
                f"\n这些概念学生已经学过，最多用一句话带过，"
                f"篇幅不得超过全文的 {self.allowed_background_ratio:.0%}。"
            )

        if include_forbidden and self.forbidden:
            lines.append(f"\n## 严禁引入的概念\n{'、'.join(self.forbidden)}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "unit_name": self.unit_name,
            "objective": self.objective,
            "slide_budget": self.slide_budget,
            "required": [c["id"] for c in self.required],
            "optional": [c["id"] for c in self.optional],
            "order": self.order,
            "misconceptions": [m["id"] for m in self.misconceptions],
            "lab": self.lab["id"] if self.lab else None,
            "siblings": self.siblings,
            "forbidden": self.forbidden,
        }


def build_constraints(graph: Graph, unit_id: str) -> UnitConstraints:
    """Build the generation contract for ``unit_id``."""
    unit = graph.node(unit_id)
    if unit.get("type") != "Unit":
        raise ValueError(f"{unit_id} is not a Unit node")

    concepts = [_normalize(c) for c in graph.unit_concepts(unit_id, include_skills=True)]

    required = [
        c for c in concepts if IMPORTANCE_RANK.get(c.get("importance", ""), 0) >= CORE_LEVEL
    ]
    optional = [
        c for c in concepts if IMPORTANCE_RANK.get(c.get("importance", ""), 0) < CORE_LEVEL
    ]

    try:
        order = graph.topological_order([c["id"] for c in concepts])
    except ValueError:
        # Fall back to graph declaration order; the validator reports the cycle.
        order = [c["id"] for c in concepts]

    # Evidence anchors: prefer prerequisite edges, then implements/verified_by.
    evidence: dict[str, str] = {}
    for node in concepts:
        for edge in graph.in_edges(node["id"], "prerequisites_for"):
            evidence.setdefault(node["id"], edge.get("evidence", ""))
        for edge in graph.in_edges(node["id"], "implements"):
            evidence.setdefault(node["id"], edge.get("evidence", ""))
        for edge in graph.in_edges(node["id"], "verified_by"):
            evidence.setdefault(node["id"], edge.get("evidence", ""))
    evidence = {k: v for k, v in evidence.items() if v}

    # Sibling concepts belong to other units of the same module.  They may be
    # referenced as a callback, but should not be re-taught in this unit.
    module_id = None
    for edge in graph.out_edges(unit_id, "is_part_of"):
        module_id = edge["target"]
    siblings: list[str] = []
    if module_id:
        unit_ids = [
            u["id"]
            for u in graph.of_type("Unit")
            if graph.targets(u["id"], "is_part_of") == [module_id]
        ]
        in_scope = {c["id"] for c in concepts}
        for other_unit in unit_ids:
            if other_unit == unit_id:
                continue
            for node in graph.unit_concepts(other_unit, include_skills=False):
                if node["id"] not in in_scope:
                    siblings.append(node.get("name", node["id"]))

    # Explicitly out-of-scope terms are declared per unit, not inferred.
    forbidden = [str(term) for term in unit.get("forbidden_terms", [])]

    labs = graph.unit_labs(unit_id)

    return UnitConstraints(
        unit_id=unit_id,
        unit_name=unit.get("name", unit_id),
        objective=unit.get("objective", ""),
        slide_budget=int(unit.get("slide_budget", 6)),
        course_name=str(graph.meta.get("course_name", "")),
        language=str(graph.meta.get("language", "Python")),
        unit_order=int(unit.get("order", 0)),
        required=required,
        optional=optional,
        order=order,
        misconceptions=graph.unit_misconceptions(unit_id),
        lab=labs[0] if labs else None,
        evidence=evidence,
        siblings=sorted(set(siblings)),
        forbidden=forbidden,
    )
