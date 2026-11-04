"""In-memory course knowledge graph with structural validation.

The graph is loaded from a JSON file following ``schema.yaml``.  Node and edge
records are intentionally kept as plain dictionaries so that downstream modules
(constraint extraction, validation, rendering) can access domain-specific
attributes without a rigid class hierarchy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

# Node types that represent knowledge points which must be grounded in a Unit.
GROUNDED_TYPES = ("Concept", "Skill", "Lab", "Misconception", "Exercise")

# Edges that must carry an ``evidence`` field pointing back to source material.
EVIDENCE_REQUIRED_EDGES = (
    "is_a",
    "prerequisites_for",
    "relates_to",
    "implements",
    "verified_by",
)

IMPORTANCE_RANK = {"了解": 0, "理解": 1, "掌握": 2, "熟练": 3}


@dataclass(frozen=True)
class Issue:
    """A validation finding."""

    level: str  # "error" | "warning"
    code: str
    message: str
    subject: str = ""

    def __str__(self) -> str:
        prefix = "ERROR" if self.level == "error" else "WARN "
        subject = f" [{self.subject}]" if self.subject else ""
        return f"{prefix} {self.code}{subject}: {self.message}"


@dataclass
class Graph:
    """Course knowledge graph."""

    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    edges: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    # ---------------------------------------------------------------- loading
    @classmethod
    def load(cls, path: str | Path) -> "Graph":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Graph":
        """Build from an already-parsed document (used by the mutation tests)."""
        nodes = {node["id"]: node for node in raw.get("nodes", [])}
        duplicated = len(raw.get("nodes", [])) - len(nodes)
        if duplicated:
            raise ValueError(f"duplicate node ids detected: {duplicated}")
        return cls(nodes=nodes, edges=raw.get("edges", []), meta=raw.get("meta", {}))

    # ---------------------------------------------------------------- basics
    def __len__(self) -> int:
        return len(self.nodes)

    def node(self, node_id: str) -> dict[str, Any]:
        try:
            return self.nodes[node_id]
        except KeyError as exc:
            raise KeyError(f"unknown node id: {node_id}") from exc

    def of_type(self, *node_types: str) -> list[dict[str, Any]]:
        wanted = set(node_types)
        return [n for n in self.nodes.values() if n.get("type") in wanted]

    def out_edges(self, node_id: str, edge_type: str | None = None) -> list[dict[str, Any]]:
        return [
            e
            for e in self.edges
            if e["source"] == node_id and (edge_type is None or e["type"] == edge_type)
        ]

    def in_edges(self, node_id: str, edge_type: str | None = None) -> list[dict[str, Any]]:
        return [
            e
            for e in self.edges
            if e["target"] == node_id and (edge_type is None or e["type"] == edge_type)
        ]

    def targets(self, node_id: str, edge_type: str) -> list[str]:
        return [e["target"] for e in self.out_edges(node_id, edge_type)]

    def sources(self, node_id: str, edge_type: str) -> list[str]:
        return [e["source"] for e in self.in_edges(node_id, edge_type)]

    def exists(self, node_id: str) -> bool:
        return node_id in self.nodes

    # ------------------------------------------------------------ unit views
    def unit_concepts(self, unit_id: str, include_skills: bool = True) -> list[dict[str, Any]]:
        """Return knowledge points grounded in ``unit_id`` ordered by sequence."""
        wanted = ("Concept", "Skill") if include_skills else ("Concept",)
        items: list[tuple[int, dict[str, Any]]] = []
        for edge in self.in_edges(unit_id, "appears_in"):
            node = self.nodes.get(edge["source"])
            if node and node.get("type") in wanted:
                items.append((int(edge.get("sequence", 999)), node))
        items.sort(key=lambda pair: pair[0])
        return [node for _, node in items]

    def unit_misconceptions(self, unit_id: str) -> list[dict[str, Any]]:
        """Misconceptions either grounded in the unit or explicitly addressed by it."""
        found: dict[str, dict[str, Any]] = {}
        for edge in self.in_edges(unit_id, "appears_in"):
            node = self.nodes.get(edge["source"])
            if node and node.get("type") == "Misconception":
                found[node["id"]] = node
        for edge in self.out_edges(unit_id, "addresses_misconception"):
            node = self.nodes.get(edge["target"])
            if node:
                found[node["id"]] = node
        return list(found.values())

    def unit_labs(self, unit_id: str) -> list[dict[str, Any]]:
        return [
            self.nodes[e["source"]]
            for e in self.in_edges(unit_id, "appears_in")
            if self.nodes.get(e["source"], {}).get("type") == "Lab"
        ]

    # --------------------------------------------------------- prerequisites
    def prerequisite_pairs(self, node_ids: Iterable[str]) -> list[tuple[str, str]]:
        """Prerequisite edges whose both endpoints are inside ``node_ids``."""
        scope = set(node_ids)
        return [
            (e["source"], e["target"])
            for e in self.edges
            if e["type"] == "prerequisites_for"
            and e["source"] in scope
            and e["target"] in scope
        ]

    def topological_order(self, node_ids: Iterable[str]) -> list[str]:
        """Kahn topological sort restricted to ``node_ids``.

        Raises ``ValueError`` when a cycle is present.
        """
        scope = list(dict.fromkeys(node_ids))
        scope_set = set(scope)
        indegree = {nid: 0 for nid in scope}
        adjacency: dict[str, list[str]] = {nid: [] for nid in scope}
        for src, dst in self.prerequisite_pairs(scope):
            adjacency[src].append(dst)
            indegree[dst] += 1

        # Stable ordering: keep original position as tie-breaker.
        position = {nid: i for i, nid in enumerate(scope)}
        ready = sorted((n for n in scope if indegree[n] == 0), key=position.__getitem__)
        ordered: list[str] = []
        while ready:
            current = ready.pop(0)
            ordered.append(current)
            for nxt in adjacency[current]:
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    ready.append(nxt)
            ready.sort(key=position.__getitem__)

        if len(ordered) != len(scope):
            cyclic = [n for n in scope if n not in set(ordered)]
            raise ValueError(f"prerequisite cycle detected among: {cyclic}")
        return ordered

    def find_cycles(self) -> list[list[str]]:
        """Return all cycles found in the ``prerequisites_for`` subgraph (DFS)."""
        adjacency: dict[str, list[str]] = {}
        for edge in self.edges:
            if edge["type"] != "prerequisites_for":
                continue
            adjacency.setdefault(edge["source"], []).append(edge["target"])

        WHITE, GRAY, BLACK = 0, 1, 2
        color = {nid: WHITE for nid in adjacency}
        stack: list[str] = []
        cycles: list[list[str]] = []

        def visit(nid: str) -> None:
            color[nid] = GRAY
            stack.append(nid)
            for nxt in adjacency.get(nid, []):
                state = color.get(nxt, WHITE)
                if state == WHITE:
                    color[nxt] = WHITE
                    visit(nxt)
                elif state == GRAY:
                    start = stack.index(nxt)
                    cycles.append(stack[start:] + [nxt])
            stack.pop()
            color[nid] = BLACK

        for nid in list(adjacency):
            if color.get(nid, WHITE) == WHITE:
                visit(nid)
        return cycles

    # ----------------------------------------------------------- validation
    def validate(self, max_concepts_per_unit: int = 8) -> list[Issue]:
        """Run structural checks defined in ``schema.yaml``."""
        issues: list[Issue] = []

        # 1. dangling edges
        for edge in self.edges:
            for side in ("source", "target"):
                if edge[side] not in self.nodes:
                    issues.append(
                        Issue(
                            "error",
                            "DANGLING_EDGE",
                            f"{edge['type']} edge points to undefined node",
                            edge[side],
                        )
                    )

        # 2. prerequisite cycles
        for cycle in self.find_cycles():
            issues.append(
                Issue("error", "PREREQ_CYCLE", "cycle: " + " -> ".join(cycle), cycle[0])
            )

        # 3. grounding: every knowledge point belongs to at least one Unit
        for node in self.nodes.values():
            if node.get("type") not in GROUNDED_TYPES:
                continue
            if not self.out_edges(node["id"], "appears_in"):
                issues.append(
                    Issue("error", "NOT_GROUNDED", "node has no appears_in edge", node["id"])
                )

        # 4. evidence required on semantic edges
        for edge in self.edges:
            if edge["type"] in EVIDENCE_REQUIRED_EDGES and not edge.get("evidence"):
                issues.append(
                    Issue(
                        "error",
                        "MISSING_EVIDENCE",
                        f"{edge['type']} edge lacks evidence",
                        f"{edge['source']}->{edge['target']}",
                    )
                )

        # 5. unit capacity and importance coverage
        for unit in self.of_type("Unit"):
            concepts = [
                n
                for n in self.unit_concepts(unit["id"], include_skills=False)
                if n.get("type") == "Concept"
            ]
            if not 3 <= len(concepts) <= max_concepts_per_unit:
                issues.append(
                    Issue(
                        "warning",
                        "UNIT_CAPACITY",
                        f"unit holds {len(concepts)} concepts, expected 3-{max_concepts_per_unit}",
                        unit["id"],
                    )
                )
            if not any(IMPORTANCE_RANK.get(c.get("importance", ""), 0) >= 2 for c in concepts):
                issues.append(
                    Issue(
                        "warning",
                        "NO_CORE_CONCEPT",
                        "unit has no concept at the 掌握/熟练 level",
                        unit["id"],
                    )
                )

        # 6. duplicate names inside one module
        seen: dict[str, str] = {}
        for node in self.of_type(*GROUNDED_TYPES):
            key = node.get("name", "")
            if not key:  # Misconception nodes carry `statement` instead of `name`
                continue
            if key in seen and seen[key] != node["id"]:
                issues.append(
                    Issue(
                        "error",
                        "DUPLICATE_NAME",
                        f"name '{key}' already used by {seen[key]}",
                        node["id"],
                    )
                )
            seen.setdefault(key, node["id"])

        # 7-10. consistency of the contract's own ingredients.  These are the
        # checks that make the knowledge base verifiable rather than merely
        # well-formed: a graph can be acyclic, grounded and evidenced and still
        # contradict itself at the level of what a session is told to do.
        for unit in self.of_type("Unit"):
            unit_id = unit["id"]
            required = {
                n.get("name", "")
                for n in self.unit_concepts(unit_id, include_skills=False)
                if IMPORTANCE_RANK.get(n.get("importance", ""), 0) >= 2
            }
            forbidden = {str(t) for t in unit.get("forbidden_terms", [])}

            # 7. F ∩ R: a term cannot be both mandatory and banned in one session
            for term in sorted(required & forbidden):
                issues.append(
                    Issue(
                        "error",
                        "FORBIDDEN_REQUIRED_OVERLAP",
                        f"'{term}' is required by importance and also forbidden",
                        unit_id,
                    )
                )

            # 8. F ∩ B: a term cannot be both "may recap in one sentence" and
            # "not taught in this course at all"
            siblings = self.sibling_concept_names(unit_id)
            for term in sorted(forbidden & siblings):
                issues.append(
                    Issue(
                        "error",
                        "FORBIDDEN_SIBLING_OVERLAP",
                        f"'{term}' is both forbidden here and admissible as sibling recap",
                        unit_id,
                    )
                )

        # 9. orphan misconception: no session is responsible for correcting it,
        # so it can never enter any contract and the metric can never see it
        for node in self.of_type("Misconception"):
            if not self.in_edges(node["id"], "addresses_misconception"):
                issues.append(
                    Issue(
                        "warning",
                        "ORPHAN_MISCONCEPTION",
                        "misconception is targeted by no unit, lab or concept",
                        node["id"],
                    )
                )

        # 10. implements edge whose target is not an executable artefact, or
        # whose source is never grounded in a session
        for edge in [e for e in self.edges if e["type"] == "implements"]:
            target = self.nodes.get(edge["target"], {})
            if target.get("type") not in ("Skill", "Lab", "Exercise", "Concept"):
                issues.append(
                    Issue(
                        "warning",
                        "IMPLEMENTS_TARGET_TYPE",
                        f"implements points at a {target.get('type', 'missing')} node",
                        edge["target"],
                    )
                )
            if not self.out_edges(edge["source"], "appears_in"):
                issues.append(
                    Issue(
                        "warning",
                        "IMPLEMENTS_SOURCE_UNGROUNDED",
                        "implements source has no appears_in edge",
                        edge["source"],
                    )
                )

        return issues

    def sibling_concept_names(self, unit_id: str) -> set[str]:
        """Concept names of other Units in the same Module.

        Mirrors the sibling rule used by ``build_constraints`` so that check 8
        tests the same set the contract will actually carry.
        """
        module_id = None
        for edge in self.out_edges(unit_id, "is_part_of"):
            module_id = edge["target"]
        if module_id is None:
            return set()
        names: set[str] = set()
        for edge in self.in_edges(module_id, "is_part_of"):
            other = edge["source"]
            if other == unit_id:
                continue
            for node in self.unit_concepts(other, include_skills=False):
                names.add(node.get("name", ""))
        names.discard("")
        return names

    def assert_valid(self, max_concepts_per_unit: int = 8) -> None:
        """Raise if the graph carries any ``error``-level issue."""
        errors = [i for i in self.validate(max_concepts_per_unit) if i.level == "error"]
        if errors:
            raise ValueError("graph validation failed:\n" + "\n".join(map(str, errors)))

    # -------------------------------------------------------------- helpers
    def describe(self) -> str:
        counts: dict[str, int] = {}
        for node in self.nodes.values():
            counts[node["type"]] = counts.get(node["type"], 0) + 1
        parts = [f"{name}={count}" for name, count in sorted(counts.items())]
        return f"Graph({len(self.nodes)} nodes, {len(self.edges)} edges: " + ", ".join(parts) + ")"

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self.nodes.values())
